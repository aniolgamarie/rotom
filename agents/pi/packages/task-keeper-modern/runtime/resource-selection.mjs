import { createHash } from "node:crypto";
import { lstatSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
const groups = [
    "extensions",
    "skills",
    "prompts",
    "themes",
    "roles"
];
const approved = new WeakSet();
const hash = (value)=>createHash("sha256").update(value).digest("hex");
const fail = (code = "pi-resource-invalid")=>{
    throw new Error(code);
};
function inside(root, path) {
    const rel = relative(root, path);
    return rel !== ".." && !rel.startsWith(".." + sep) && !isAbsolute(rel);
}
function snapshot(root, name) {
    if (typeof name !== "string" || !name || isAbsolute(name) || name.includes("\\") || name.includes("\0") || name.split("/").some((p)=>!p || p === "." || p === "..") || /^(npm|git|https?):/.test(name)) fail();
    root = realpathSync(root);
    const path = resolve(root, name);
    const entries = [];
    function walk(current) {
        const info = lstatSync(current);
        if (info.isSymbolicLink() || !info.isFile() && !info.isDirectory() || !inside(root, realpathSync(current))) fail();
        if (info.isDirectory()) {
            for (const child of readdirSync(current).sort())walk(join(current, child));
        } else {
            entries.push([
                relative(path, current),
                info.mode & 0o111,
                hash(readFileSync(current))
            ]);
        }
    }
    let current = root;
    for (const part of name.split("/")){
        current = join(current, part);
        if (lstatSync(current).isSymbolicLink()) fail();
    }
    walk(path);
    return {
        path,
        digest: hash(JSON.stringify(entries))
    };
}
export function selectResources({ manifest, installed, instanceRoot, runtimeRoot, cwd, engine }) {
    if (manifest.engine !== engine || ![
        "node",
        "bun"
    ].includes(engine)) fail("pi-engine-mismatch");
    try {
        if (manifest.schema_version !== 1 || typeof manifest.bootstrap !== "boolean" || !Array.isArray(manifest.plugins) || new Set(manifest.plugins).size !== manifest.plugins.length) fail();
        const modern = [
            "pi-base",
            "pi-full"
        ].includes(manifest.profile_id);
        let selectedCapabilities = manifest.plugins, bootstrapCapabilities = manifest.bootstrap_plugins ?? [];
        if (modern) {
            const mapping = manifest.plugin_capabilities === undefined && manifest.plugins.length === 0 ? {} : manifest.plugin_capabilities;
            if (!mapping || typeof mapping !== "object" || Array.isArray(mapping) || JSON.stringify(Object.keys(mapping).sort()) !== JSON.stringify([
                ...manifest.plugins
            ].sort())) fail();
            const capabilities = new Set(), tools = new Set();
            for (const plugin of manifest.plugins){
                if (typeof plugin !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(plugin)) fail();
                const row = mapping[plugin];
                if (!row || Object.keys(row).sort().join(",") !== "capability_id,model_tools" || typeof row.capability_id !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(row.capability_id) || capabilities.has(row.capability_id) || !Array.isArray(row.model_tools) || row.model_tools.length > 64) fail();
                capabilities.add(row.capability_id);
                for (const name of row.model_tools){
                    if (typeof name !== "string" || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(name) || tools.has(name)) fail();
                    tools.add(name);
                }
            }
            selectedCapabilities = [
                ...capabilities
            ];
            if (!Array.isArray(bootstrapCapabilities) || bootstrapCapabilities.some((plugin)=>!manifest.plugins.includes(plugin))) fail();
            bootstrapCapabilities = bootstrapCapabilities.map((plugin)=>mapping[plugin].capability_id);
        }
        const installedCapabilities = new Set(groups.flatMap((group)=>(installed[group] ?? []).map((item)=>item.capability_id)));
        if (selectedCapabilities.some((id)=>!installedCapabilities.has(id))) fail("pi-resource-selected-plugin-missing");
        const resources = Object.fromEntries(groups.map((group)=>[
                group,
                []
            ]));
        const paths = new Set();
        function add(group, id, base, name, scope, override) {
            if (!groups.includes(group) || typeof id !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(id)) fail();
            const existing = resources[group].findIndex((entry)=>entry.id === (override ?? id));
            if (existing >= 0) {
                if (scope !== "project" || !override || group !== "roles" || override.startsWith("task-keeper-")) fail("pi-resource-conflict");
                paths.delete(resources[group][existing].path);
                resources[group].splice(existing, 1);
            } else if (override) fail("pi-resource-conflict");
            const item = snapshot(base, name);
            if (paths.has(item.path)) fail("pi-resource-conflict");
            paths.add(item.path);
            resources[group].push({
                id: override ?? id,
                ...item,
                scope
            });
        }
        for (const group of groups){
            const mapping = manifest.resource_ids[group];
            if (!Array.isArray(manifest.resources[group]) || !mapping || JSON.stringify([
                ...manifest.resources[group]
            ].sort()) !== JSON.stringify(Object.values(mapping).sort())) fail();
            for (const [id, path] of Object.entries(mapping)){
                if (manifest.bootstrap && group === "extensions") continue;
                add(group, id, instanceRoot, path, "instance");
            }
            for (const item of installed[group] ?? []){
                if (Object.keys(item).some((k)=>![
                        "id",
                        "path",
                        "capability_id"
                    ].includes(k))) fail();
                if (!selectedCapabilities.includes(item.capability_id) || manifest.bootstrap && group === "extensions" && !bootstrapCapabilities.includes(item.capability_id)) continue;
                add(group, item.id, runtimeRoot, item.path, "runtime");
            }
        }
        for (const item of manifest.project_resources ?? []){
            if (!manifest.options.discovery?.project_resources) fail();
            if (Object.keys(item).some((k)=>![
                    "id",
                    "kind",
                    "path",
                    "override"
                ].includes(k))) fail();
            if (manifest.bootstrap && item.kind === "extensions") continue;
            add(item.kind, item.id, cwd, item.path, "project", item.override);
        }
        for (const item of manifest.external_skills ?? []){
            if (Object.keys(item).some((k)=>![
                    "id",
                    "root",
                    "path"
                ].includes(k)) || !isAbsolute(item.root)) fail();
            add("skills", item.id, item.root, item.path, "external");
        }
        const rules = snapshot(instanceRoot, "pi-home/AGENTS.md");
        const append = snapshot(instanceRoot, "pi-home/APPEND_SYSTEM.md");
        const record = {
            schema_version: 1,
            engine,
            bootstrap: manifest.bootstrap,
            resources,
            rules,
            append
        };
        const result = {
            ...record,
            digest: hash(JSON.stringify(record))
        };
        for (const entries of Object.values(resources)){
            entries.forEach(Object.freeze);
            Object.freeze(entries);
        }
        Object.freeze(resources);
        Object.freeze(rules);
        Object.freeze(append);
        approved.add(result);
        return Object.freeze(result);
    } catch (error) {
        if (error instanceof Error && error.message.startsWith("pi-resource-")) throw error;
        fail();
    }
}
export function restrictExtensions(selection, ids) {
    if (!approved.has(selection) || !Array.isArray(ids) || new Set(ids).size !== ids.length || ids.some((id)=>!selection.resources.extensions.some((entry)=>entry.id === id))) fail("pi-validation-extension-scope");
    const resources = Object.freeze({
        ...selection.resources,
        extensions: Object.freeze(selection.resources.extensions.filter((entry)=>ids.includes(entry.id)))
    });
    const record = {
        schema_version: selection.schema_version,
        engine: selection.engine,
        bootstrap: selection.bootstrap,
        resources,
        rules: selection.rules,
        append: selection.append
    };
    const result = Object.freeze({
        ...record,
        digest: hash(JSON.stringify(record))
    });
    approved.add(result);
    return result;
}
export function loaderOptions(selection) {
    if (!approved.has(selection)) fail();
    return {
        noExtensions: true,
        noSkills: true,
        noPromptTemplates: true,
        noThemes: true,
        noContextFiles: true,
        additionalExtensionPaths: selection.resources.extensions.map((entry)=>entry.path),
        additionalSkillPaths: selection.resources.skills.map((entry)=>entry.path),
        additionalPromptTemplatePaths: selection.resources.prompts.map((entry)=>entry.path),
        additionalThemePaths: selection.resources.themes.map((entry)=>entry.path),
        agentsFilesOverride: ()=>({
                agentsFiles: [
                    {
                        path: selection.rules.path,
                        content: readFileSync(selection.rules.path, "utf8")
                    }
                ]
            }),
        appendSystemPrompt: [
            readFileSync(selection.append.path, "utf8")
        ]
    };
}
export function assertApprovedSelection(selection) {
    if (!approved.has(selection)) fail();
    return selection;
}
export function verifySelection(selection) {
    assertApprovedSelection(selection);
    try {
        for (const entry of [
            ...Object.values(selection.resources).flat(),
            selection.rules,
            selection.append
        ]){
            const current = snapshot(resolve(entry.path, ".."), entry.path.split(sep).at(-1));
            if (current.path !== entry.path || current.digest !== entry.digest) fail("pi-resource-selection-stale");
        }
    } catch  {
        fail("pi-resource-selection-stale");
    }
    return selection;
}
