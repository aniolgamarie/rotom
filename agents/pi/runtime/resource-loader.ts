// 只把预先选择并核验的路径交给 SDK；禁止解析器扫描、下载或扩充资源。
import { createHash } from "node:crypto";
import { lstatSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, join, parse, relative, resolve, sep } from "node:path";

const groups = ["extensions", "skills", "prompts", "themes", "roles"];
const approved = new WeakSet();
const hash = value => createHash("sha256").update(value).digest("hex");
const fail = (code = "pi-resource-invalid") => { throw new Error(code); };

function inside(root, path) {
  const rel = relative(root, path);
  return rel !== ".." && !rel.startsWith(".." + sep) && !isAbsolute(rel);
}

function snapshot(root, name) {
  if (typeof name !== "string" || !name || isAbsolute(name) || name.includes("\\")
      || name.includes("\0") || name.split("/").some(p => !p || p === "." || p === "..") || /^(npm|git|https?):/.test(name)) fail();
  root = realpathSync(root);
  const path = resolve(root, name);
  const entries = [];
  function walk(current) {
    const info = lstatSync(current);
    if (info.isSymbolicLink() || (!info.isFile() && !info.isDirectory()) || !inside(root, realpathSync(current))) fail();
    if (info.isDirectory()) {
      for (const child of readdirSync(current).sort()) walk(join(current, child));
    } else {
      entries.push([relative(path, current), info.mode & 0o111, hash(readFileSync(current))]);
    }
  }
  // 每个父组件都核验，不能用指向树外的目录链接逃逸。
  let current = root;
  for (const part of name.split("/")) {
    current = join(current, part);
    if (lstatSync(current).isSymbolicLink()) fail();
  }
  walk(path);
  return { path, digest: hash(JSON.stringify(entries)) };
}

export function selectResources({ manifest, installed, instanceRoot, runtimeRoot, cwd, engine }) {
  if (manifest.engine !== engine || !["node", "bun"].includes(engine)) fail("pi-engine-mismatch");
  try {
    if (manifest.schema_version !== 1 || typeof manifest.bootstrap !== "boolean"
        || !Array.isArray(manifest.plugins) || new Set(manifest.plugins).size !== manifest.plugins.length) fail();
    const installedCapabilities = new Set(groups.flatMap(group => (installed[group] ?? []).map(item => item.capability_id)));
    if (manifest.plugins.some(id => !installedCapabilities.has(id))) fail("pi-resource-selected-plugin-missing");
    const resources = Object.fromEntries(groups.map(group => [group, []]));
    const paths = new Set();
    function add(group, id, base, name, scope, override) {
      if (!groups.includes(group) || typeof id !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(id)) fail();
      const existing = resources[group].findIndex(entry => entry.id === (override ?? id));
      if (existing >= 0) {
        if (scope !== "project" || !override || group !== "roles" || override.startsWith("task-keeper-")) fail("pi-resource-conflict");
        paths.delete(resources[group][existing].path);
        resources[group].splice(existing, 1);
      } else if (override) fail("pi-resource-conflict");
      const item = snapshot(base, name);
      if (paths.has(item.path)) fail("pi-resource-conflict");
      paths.add(item.path);
      resources[group].push({ id: override ?? id, ...item, scope });
    }
    for (const group of groups) {
      const mapping = manifest.resource_ids[group];
      if (!Array.isArray(manifest.resources[group]) || !mapping
          || JSON.stringify([...manifest.resources[group]].sort()) !== JSON.stringify(Object.values(mapping).sort())) fail();
      for (const [id, path] of Object.entries(mapping)) {
        if (manifest.bootstrap && group === "extensions") continue;
        add(group, id, instanceRoot, path, "instance");
      }
      for (const item of installed[group] ?? []) {
        if (Object.keys(item).some(k => !["id", "path", "capability_id"].includes(k))) fail();
        if (!manifest.plugins.includes(item.capability_id) || (manifest.bootstrap && group === "extensions" && !(manifest.bootstrap_plugins ?? []).includes(item.capability_id))) continue;
        add(group, item.id, runtimeRoot, item.path, "runtime");
      }
    }
    for (const item of manifest.project_resources ?? []) {
      if (!manifest.options.discovery?.project_resources) fail();
      if (Object.keys(item).some(k => !["id", "kind", "path", "override"].includes(k))) fail();
      if (manifest.bootstrap && item.kind === "extensions") continue;
      add(item.kind, item.id, cwd, item.path, "project", item.override);
    }
    for (const item of manifest.external_skills ?? []) {
      if (Object.keys(item).some(k => !["id", "root", "path"].includes(k)) || !isAbsolute(item.root)) fail();
      add("skills", item.id, item.root, item.path, "external");
    }
    const rules = snapshot(instanceRoot, "pi-home/AGENTS.md");
    const append = snapshot(instanceRoot, "pi-home/APPEND_SYSTEM.md");
    const record = { schema_version: 1, engine, bootstrap: manifest.bootstrap, resources, rules, append };
    const result = { ...record, digest: hash(JSON.stringify(record)) };
    for (const entries of Object.values(resources)) {
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
  if (!approved.has(selection) || !Array.isArray(ids) || new Set(ids).size !== ids.length
      || ids.some(id => !selection.resources.extensions.some(entry => entry.id === id))) fail("pi-validation-extension-scope");
  const resources = Object.freeze({ ...selection.resources,
    extensions: Object.freeze(selection.resources.extensions.filter(entry => ids.includes(entry.id))) });
  const record = { schema_version: selection.schema_version, engine: selection.engine, bootstrap: selection.bootstrap,
    resources, rules: selection.rules, append: selection.append };
  const result = Object.freeze({ ...record, digest: hash(JSON.stringify(record)) });
  approved.add(result);
  return result;
}

export function assertResourceSelection(selection) {
  if (!approved.has(selection)) fail();
  for (const entry of [selection.rules, selection.append, ...Object.values(selection.resources).flat()]) {
    const root = parse(entry.path).root;
    const current = snapshot(root, relative(root, entry.path).split(sep).join("/"));
    if (current.path !== entry.path || current.digest !== entry.digest) fail("pi-resource-changed");
  }
}

// ResourceLoader 是公开可注入接口；包装自有对象，不改写 DefaultResourceLoader。
export function managedResourceLoader(loader, selection, beforeReload, afterReload = () => {}) {
  if (!approved.has(selection)) fail();
  const result = {};
  for (const name of ["getExtensions", "getSkills", "getPrompts", "getThemes", "getAgentsFiles", "getSystemPrompt",
      "getSystemPromptSource", "getAppendSystemPrompt", "getAppendSystemPromptSources"]) {
    result[name] = (...args) => loader[name](...args);
  }
  result.extendResources = paths => {
    for (const [key, entries] of Object.entries(paths)) {
      const kind = { skillPaths: "skills", promptPaths: "prompts", themePaths: "themes" }[key];
      if (!kind || !Array.isArray(entries) || entries.some(item => !selection.resources[kind].some(allowed => allowed.path === item.path))) fail();
    }
    return loader.extendResources(paths);
  };
  result.reload = async (...args) => {
    await beforeReload();
    assertResourceSelection(selection);
    await loader.reload(...args);
    assertResourceSelection(selection);
    afterReload(result);
  };
  return Object.freeze(result);
}

export function loaderOptions(selection) {
  if (!approved.has(selection)) fail();
  return {
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: selection.resources.extensions.map(entry => entry.path),
    additionalSkillPaths: selection.resources.skills.map(entry => entry.path),
    additionalPromptTemplatePaths: selection.resources.prompts.map(entry => entry.path),
    additionalThemePaths: selection.resources.themes.map(entry => entry.path),
    agentsFilesOverride: () => ({ agentsFiles: [{ path: selection.rules.path, content: readFileSync(selection.rules.path, "utf8") }] }),
    appendSystemPrompt: [readFileSync(selection.append.path, "utf8")],
  };
}

export function parseArguments(argv) {
  const result = { print: false, thinking: undefined, help: false, messages: [] };
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (typeof arg !== "string" || arg.includes("\0")) fail("pi-arguments-invalid");
    if (arg === "--") {
      result.messages.push(...argv.slice(index + 1));
      break;
    }
    if (arg === "--print" || arg === "-p") result.print = true;
    else if (arg === "--help" || arg === "-h") result.help = true;
    else if (arg === "--thinking") {
      const level = argv[++index];
      if (!["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(level)) fail("pi-arguments-thinking");
      result.thinking = level;
    } else if (arg.startsWith("-")) fail("pi-arguments-protected-or-unknown");
    else result.messages.push(arg);
  }
  return result;
}
