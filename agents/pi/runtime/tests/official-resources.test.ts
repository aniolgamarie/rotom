import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialResources } from "../official-resources.ts";
import { selectResources, loaderOptions } from "../resource-selection.ts";
import { installPackagePolicy } from "../resource-loader.ts";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "official-resources-"));
  const instanceRoot = join(root, "instance"), runtimeRoot = join(root, "runtime"), cwd = join(root, "project");
  for (const path of [instanceRoot, runtimeRoot, cwd]) mkdirSync(path);
  const put = (base, path, text = "selected content") => { const target = join(base, path); mkdirSync(join(target, ".."), { recursive: true }); writeFileSync(target, text); return target; };
  const extension = join(runtimeRoot, "packages/chosen"); put(runtimeRoot, "packages/chosen/index.mjs");
  const skill = join(instanceRoot, "pi-home/skills/chosen"); put(instanceRoot, "pi-home/skills/chosen/SKILL.md");
  const prompt = put(instanceRoot, "pi-home/prompts/chosen.md"), theme = put(instanceRoot, "pi-home/themes/chosen.json", "{}");
  const rules = put(instanceRoot, "pi-home/AGENTS.md", "selected rules"), append = put(instanceRoot, "pi-home/APPEND_SYSTEM.md", "selected append");
  for (const base of [root, cwd, instanceRoot]) {
    put(base, ".pi/extensions/decoy.mjs"); put(base, "AGENTS.md", "decoy rules"); put(base, "APPEND_SYSTEM.md", "decoy append");
  }
  const paths = { extensions: [], roles: [], skills: ["pi-home/skills/chosen"], prompts: ["pi-home/prompts/chosen.md"], themes: ["pi-home/themes/chosen.json"] };
  const ids = { extensions: {}, roles: {}, skills: { chosen: paths.skills[0] }, prompts: { chosen: paths.prompts[0] }, themes: { chosen: paths.themes[0] } };
  const manifest = { schema_version: 1, engine: "node", bootstrap: false, plugins: ["chosen"], resources: paths, resource_ids: ids,
    options: { discovery: { project_resources: false } }, project_resources: [], external_skills: [] };
  const installed = { resources: { extensions: [{ id: "chosen", capability_id: "chosen", path: "packages/chosen" }], skills: [], prompts: [], themes: [], roles: [] } };
  const settings = { packages: [], extensions: [], skills: [], prompts: [], themes: [] };
  const settingsManager = Object.freeze({ getPackages: () => settings.packages, getExtensionPaths: () => settings.extensions,
    getSkillPaths: () => settings.skills, getPromptTemplatePaths: () => settings.prompts, getThemePaths: () => settings.themes });
  const state = new WeakMap(), observations = { options: null, reloads: 0, extensions: 0 };
  let loaded;
  class Loader {
    constructor(options) { observations.options = options; state.set(this, null); Object.freeze(this); }
    async reload() {
      observations.reloads++;
      await observations.reloadGate?.();
      const options = observations.options;
      for (const input of options.extensionFactories) { observations.extensions++; await input.factory({}); }
      loaded = {
        extensions: { extensions: [...options.additionalExtensionPaths.map(path => ({ path, resolvedPath: join(path, "index.mjs") })),
          ...options.extensionFactories.map(input => ({ path: "<inline:" + input.name + ">", resolvedPath: "<inline:" + input.name + ">" }))], errors: [] },
        skills: { skills: [{ filePath: join(skill, "SKILL.md") }], diagnostics: [] },
        prompts: { prompts: [{ filePath: prompt }], diagnostics: [] }, themes: { themes: [{ sourcePath: theme }], diagnostics: [] },
        agents: options.agentsFilesOverride({ agentsFiles: [] }), system: options.systemPrompt || undefined, systemSource: undefined,
        append: ["selected append"], appendSources: [{ path: append }],
      }; state.set(this, loaded); observations.afterLoad?.(loaded);
    }
    getExtensions() { return state.get(this).extensions; }
    getSkills() { return state.get(this).skills; }
    getPrompts() { return state.get(this).prompts; }
    getThemes() { return state.get(this).themes; }
    getAgentsFiles() { return state.get(this).agents; }
    getSystemPrompt() { return state.get(this).system; }
    getSystemPromptSource() { return state.get(this).systemSource; }
    getAppendSystemPrompt() { return state.get(this).append; }
    getAppendSystemPromptSources() { return state.get(this).appendSources; }
    extendResources(paths) { observations.extended = paths; }
  }
  Object.freeze(Loader.prototype); Object.freeze(Loader);
  const sdk = Object.freeze({ DefaultResourceLoader: Loader, get DefaultPackageManager() { throw Error("package manager touched"); } });
  return { sdk, manifest, installed, instanceRoot, runtimeRoot, cwd, engine: "node", settingsManager, settings, observations,
    paths: { extension, skill, prompt, theme, rules, append }, put, mutate: fn => fn(loaded) };
}

test("unselected global ancestor project and package injections cannot enlarge the explicit loaded set", async () => {
  const f = fixture(), own = createOfficialResources(f);
  await own.resourceLoader.reload();
  const before = own.observeLoadedResources();
  for (const [base, prefix] of [[f.instanceRoot, "pi-home"], [join(f.cwd, ".."), ".pi"], [f.cwd, ".pi"]]) {
    f.put(base, prefix + "/extensions/injected.mjs", "throw Error('INERT-UNSELECTED')");
    f.put(base, prefix + "/skills/injected/SKILL.md", "synthetic unselected skill");
    f.put(base, prefix + "/prompts/injected.md", "synthetic unselected prompt");
    f.put(base, prefix + "/themes/injected.json", "{}");
  }
  const unselected = f.put(f.runtimeRoot, "packages/unselected/index.mjs", "throw Error('INERT-PACKAGE')");
  f.installed.resources.extensions.push({ id: "unselected", capability_id: "unselected", path: "packages/unselected" });
  await own.resourceLoader.reload();
  assert.deepEqual(own.observeLoadedResources(), before);
  const fresh = createOfficialResources(f);
  await fresh.resourceLoader.reload();
  assert.deepEqual(fresh.observeLoadedResources(), before);
  assert.deepEqual(f.observations.options.additionalExtensionPaths, [f.paths.extension]);
  f.mutate(state => state.extensions.extensions.push({ path: unselected, resolvedPath: unselected }));
  assert.throws(() => fresh.observeLoadedResources(), /pi-resource-loaded-path/);
});

test("Full explicit project prompt is loaded with project scope and undeclared project selection is rejected", async () => {
  const f = fixture();
  f.manifest.profile_id = "pi-full";
  f.manifest.plugin_capabilities = { chosen: { capability_id: "chosen", model_tools: [] } };
  const projectPrompt = f.put(f.cwd, ".pi/prompts/project-chosen.md", "synthetic explicit project prompt");
  f.put(f.cwd, ".pi/prompts/project-decoy.md", "synthetic unselected project prompt");
  f.manifest.project_resources = [{ id: "project-chosen", kind: "prompts", path: ".pi/prompts/project-chosen.md" }];
  assert.throws(() => createOfficialResources(f), /pi-resource-invalid/);
  f.manifest.options.discovery.project_resources = true;
  f.observations.afterLoad = state => state.prompts.prompts.push({ filePath: projectPrompt });
  const own = createOfficialResources(f);
  await own.resourceLoader.reload();
  assert.deepEqual(f.observations.options.additionalPromptTemplatePaths, [f.paths.prompt, projectPrompt]);
  assert.deepEqual(own.observeLoadedResources().resources.prompts,
    [{ id: "chosen", scope: "instance" }, { id: "project-chosen", scope: "project" }]);
});

test("official loader uses only explicit selected options and frozen public SDK composition", async () => {
  const f = fixture(), { resourceLoader, selection } = createOfficialResources(f);
  await resourceLoader.reload();
  const options = f.observations.options;
  for (const key of ["noExtensions", "noSkills", "noPromptTemplates", "noThemes", "noContextFiles"]) assert.equal(options[key], true);
  assert.deepEqual(options.additionalExtensionPaths, [f.paths.extension]);
  assert.deepEqual(options.additionalSkillPaths, [f.paths.skill]); assert.deepEqual(options.additionalPromptTemplatePaths, [f.paths.prompt]);
  assert.deepEqual(options.additionalThemePaths, [f.paths.theme]);
  assert.equal(options.systemPrompt, ""); assert.deepEqual(options.appendSystemPrompt, [f.paths.append]);
  assert.equal(resourceLoader.getAgentsFiles().agentsFiles[0].path, f.paths.rules);
  assert.equal(resourceLoader.getSystemPrompt(), undefined);
  assert.equal(resourceLoader.getSystemPromptSource(), undefined);
  assert.deepEqual(resourceLoader.getAppendSystemPromptSources(), [{ path: f.paths.append }]);
  assert.equal(resourceLoader.getThemes().themes[0].sourcePath, f.paths.theme);
  assert.equal(selection.resources.extensions[0].path, f.paths.extension);
  assert.equal(Object.isFrozen(f.sdk.DefaultResourceLoader.prototype), true);
  assert.equal(Object.isFrozen(f.sdk), true);
});

test("loaded observation is detached frozen public data and roles stay selection-only", async () => {
  const f = fixture();
  f.put(f.instanceRoot, "pi-home/agents/chosen-role.md", "synthetic role body");
  f.manifest.resources.roles = ["pi-home/agents/chosen-role.md"];
  f.manifest.resource_ids.roles = { "chosen-role": "pi-home/agents/chosen-role.md" };
  const resources = createOfficialResources({ ...f, extensionFactories: [{ name: "guard", factory() {} }] });
  assert.throws(() => resources.observeLoadedResources(), /pi-resource-not-loaded/);
  await resources.resourceLoader.reload();
  const observed = resources.observeLoadedResources();
  assert.deepEqual(observed, { schemaVersion: 1, scope: "in-memory-public-sdk-load", resourcesDigest: resources.selection.digest,
    resources: { extensions: [{ id: "chosen", scope: "runtime" }], skills: [{ id: "chosen", scope: "instance" }],
      prompts: [{ id: "chosen", scope: "instance" }], themes: [{ id: "chosen", scope: "instance" }] },
    inlineExtensions: ["guard"], selectedRoles: [{ id: "chosen-role", scope: "instance" }], rolesEvidence: "selection-only" });
  const frozen = value => { if (value && typeof value === "object") { assert.equal(Object.isFrozen(value), true); Object.values(value).forEach(frozen); } };
  frozen(observed);
  const raw = JSON.stringify(observed);
  assert.ok(!raw.includes(f.instanceRoot) && !raw.includes(f.runtimeRoot) && !raw.includes("selected content") && !raw.includes("synthetic role body"));
  assert.notEqual(resources.observeLoadedResources(), observed);
  f.mutate(state => { state.prompts.prompts[0].filePath = join(f.cwd, "same-count-decoy.md"); });
  assert.throws(() => resources.observeLoadedResources(), /pi-resource-loaded-path/);
  assert.equal(JSON.stringify(observed), raw);
});

test("reload is single flight and pending or failed SDK reload cannot expose observation", async () => {
  const f = fixture(), resources = createOfficialResources(f);
  let release, secondError;
  const gate = new Promise(resolve => { release = resolve; });
  f.observations.reloadGate = () => gate;
  const first = resources.resourceLoader.reload();
  const second = resources.resourceLoader.reload().catch(error => { secondError = error; });
  try {
    await Promise.resolve(); await Promise.resolve();
    assert.equal(secondError?.message, "pi-resource-reload-in-progress");
    assert.equal(f.observations.reloads, 1);
    assert.throws(() => resources.observeLoadedResources(), /pi-resource-not-loaded/);
    assert.throws(() => resources.resourceLoader.getExtensions(), /pi-resource-not-loaded/);
    assert.throws(() => resources.resourceLoader.extendResources({}), /pi-resource-not-loaded/);
  } finally { release(); await Promise.allSettled([first, second]); }
  assert.equal(resources.observeLoadedResources().resources.extensions.length, 1);
  const failure = new Error("fake-sdk-reload-failed");
  f.observations.reloadGate = async () => { throw failure; };
  await assert.rejects(resources.resourceLoader.reload(), error => error === failure);
  assert.throws(() => resources.observeLoadedResources(), /pi-resource-not-loaded/);
  delete f.observations.reloadGate;
  await resources.resourceLoader.reload();
  assert.equal(resources.observeLoadedResources().resources.prompts.length, 1);
});

test("observation count and UTF8 budgets include inline factories", async () => {
  const f = fixture();
  const factories = count => Array.from({ length: count }, (_, index) => ({ name: "f" + String(index).padStart(4, "0"), factory() {} }));
  const exact = createOfficialResources({ ...f, extensionFactories: factories(4092) });
  await exact.resourceLoader.reload();
  assert.equal(exact.observeLoadedResources().inlineExtensions.length, 4092);
  const over = createOfficialResources({ ...f, extensionFactories: factories(4093) });
  await over.resourceLoader.reload();
  assert.throws(() => over.observeLoadedResources(), /pi-resource-observation-invalid/);
  const large = createOfficialResources({ ...f, extensionFactories: factories(1000).map(row => ({ ...row, name: "n" + "x".repeat(58) + row.name.slice(1) })) });
  await large.resourceLoader.reload();
  assert.throws(() => large.observeLoadedResources(), /pi-resource-observation-invalid/);
});

test("every observation revalidates selected files settings and public SDK errors", async () => {
  for (const fault of ["settings", "files", "errors"]) {
    const f = fixture(), resources = createOfficialResources(f); await resources.resourceLoader.reload();
    resources.observeLoadedResources();
    if (fault === "settings") f.settings.packages.push("unselected");
    if (fault === "files") writeFileSync(f.paths.prompt, "changed selected input");
    if (fault === "errors") f.mutate(state => state.extensions.errors.push({ error: "SYNTHETIC_PRIVATE" }));
    assert.throws(() => resources.observeLoadedResources(), /pi-resource-/);
  }
});

for (const group of ["extensions", "skills", "prompts", "themes"]) for (const fault of ["extra", "missing", "wrong"]) test(group + " actual " + fault + " paths fail even at equal counts", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f);
  await resourceLoader.reload();
  f.mutate(state => {
    const rows = state[group][group], key = group === "extensions" ? "path" : group === "themes" ? "sourcePath" : "filePath";
    if (fault === "extra") rows.push({ [key]: join(f.cwd, "decoy"), resolvedPath: join(f.cwd, "decoy") });
    if (fault === "missing") rows.pop();
    if (fault === "wrong") rows[0][key] = join(f.cwd, "decoy");
  });
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-loaded-path/);
});

for (const group of ["extensions", "skills", "prompts", "themes"]) test(group + " public load errors are not ignored", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  f.mutate(state => { if (group === "extensions") state[group].errors.push({ path: "synthetic", error: "synthetic" });
    else state[group].diagnostics.push({ type: "error", message: "synthetic" }); });
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-load-failed/);
});

for (const key of ["packages", "extensions", "skills", "prompts", "themes"]) test("nonempty settings " + key + " is rejected before constructing SDK loader", () => {
  const f = fixture(); f.settings[key] = ["synthetic-auto-source"];
  assert.throws(() => createOfficialResources(f), /pi-resource-settings-not-empty/);
  assert.equal(f.observations.options, null);
});

test("reload checks settings again and prevents newly added discovery", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  f.settings.packages.push("synthetic-auto-source");
  await assert.rejects(resourceLoader.reload(), /pi-resource-settings-not-empty/);
  assert.equal(f.observations.reloads, 1);
  assert.throws(() => resourceLoader.getExtensions());
});

for (const group of ["skillPaths", "promptPaths", "themePaths"]) test("extendResources admits only exact selected " + group, async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  const path = { skillPaths: f.paths.skill, promptPaths: f.paths.prompt, themePaths: f.paths.theme }[group];
  const selected = { [group]: [{ path, metadata: { source: "agentcfg", scope: "user", origin: "top-level" } }] };
  resourceLoader.extendResources(selected); assert.deepEqual(f.observations.extended, selected);
  assert.throws(() => resourceLoader.extendResources({ [group]: [{ path: join(f.cwd, "decoy"), metadata: {} }] }), /pi-resource-extension-scope/);
  assert.throws(() => resourceLoader.extendResources({ arbitraryPaths: [] }), /pi-resource-extension-scope/);
});

for (const path of ["extension", "skill", "prompt", "theme", "rules", "append"]) test("reload detects changed selected " + path + " before running factories", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  const target = path === "extension" ? join(f.paths.extension, "index.mjs") : path === "skill" ? join(f.paths.skill, "SKILL.md") : f.paths[path];
  writeFileSync(target, "changed selection");
  await assert.rejects(resourceLoader.reload(), /pi-resource-selection-stale/);
  assert.equal(f.observations.reloads, 1);
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource/);
});

test("trusted named inline factories have exact public identities", async () => {
  const f = fixture(); let calls = 0;
  const { resourceLoader } = createOfficialResources({ ...f, extensionFactories: [{ name: "guard", factory: () => { calls++; } }] });
  await resourceLoader.reload(); assert.equal(calls, 1);
  assert.deepEqual(resourceLoader.getExtensions().extensions.map(row => row.path), [f.paths.extension, "<inline:guard>"]);
  f.mutate(state => { state.extensions.extensions[1].path = "<inline:other>"; });
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-loaded-path/);
});

for (const factory of [[{ name: "same", factory() {} }, { name: "same", factory() {} }], [{ name: "guard", factory() {}, hidden: true }], [() => {}], [{ name: "../escape", factory() {} }]]) test("invalid or ambiguous inline identity is rejected", () => {
  assert.throws(() => createOfficialResources({ ...fixture(), extensionFactories: factory }), /pi-resource-inline-invalid/);
});

for (const fault of ["resolved-outside", "extra-agents", "wrong-agents-content", "wrong-append", "auto-system", "theme-no-path"]) test("public context or resolved identity " + fault + " is rejected", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  f.mutate(state => {
    if (fault === "resolved-outside") state.extensions.extensions[0].resolvedPath = join(f.cwd, "decoy.mjs");
    if (fault === "extra-agents") state.agents.agentsFiles.push({ path: join(f.cwd, "AGENTS.md"), content: "decoy rules" });
    if (fault === "wrong-agents-content") state.agents.agentsFiles[0].content = "wrong rules";
    if (fault === "wrong-append") state.append = ["wrong append"];
    if (fault === "auto-system") state.systemSource = { path: join(f.cwd, "SYSTEM.md") };
    if (fault === "theme-no-path") delete state.themes.themes[0].sourcePath;
  });
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-/);
});

test("SDK directory expansion without one public identity is explicitly unrepresentable", () => {
  const f = fixture(); f.manifest.resources.skills = ["pi-home/skills"]; f.manifest.resource_ids.skills = { chosen: "pi-home/skills" };
  assert.throws(() => createOfficialResources(f), /pi-resource-sdk-path-unrepresentable/);
});

test("legacy policy accepts selection from extracted shared module", () => {
  const f = fixture(), selection = selectResources({ ...f, installed: f.installed.resources });
  class PackageManager { async resolve() {} async resolveExtensionSources() {} }
  installPackagePolicy({ DefaultPackageManager: PackageManager }, selection);
  assert.deepEqual(loaderOptions(selection).additionalExtensionPaths, [f.paths.extension]);
  assert.throws(() => installPackagePolicy({ DefaultPackageManager: PackageManager }, { ...selection }), /pi-resource-invalid/);
});


test("reload validates loaded paths before making public getters available", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f);
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-not-loaded/);
  f.observations.afterLoad = state => { state.prompts.prompts[0].filePath = join(f.cwd, "same-count-decoy.md"); };
  await assert.rejects(resourceLoader.reload(), /pi-resource-loaded-path/);
  assert.throws(() => resourceLoader.getPrompts(), /pi-resource-not-loaded/);
});

test("reload checks file snapshots after the public SDK reload completes", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f);
  f.observations.afterLoad = () => writeFileSync(f.paths.prompt, "changed while SDK reload was in progress");
  await assert.rejects(resourceLoader.reload(), /pi-resource-selection-stale/);
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-not-loaded/);
});

test("explicit file SKILL entry is also mapped without allowing a sibling", async () => {
  const f = fixture();
  f.manifest.resources.skills = ["pi-home/skills/chosen/SKILL.md"];
  f.manifest.resource_ids.skills = { chosen: f.manifest.resources.skills[0] };
  const { resourceLoader } = createOfficialResources(f); await resourceLoader.reload();
  assert.equal(resourceLoader.getSkills().skills[0].filePath, join(f.paths.skill, "SKILL.md"));
  assert.throws(() => resourceLoader.extendResources({ skillPaths: [{ path: f.paths.skill, metadata: {} }] }), /pi-resource-extension-scope/);
});
