// 只组合官方公共ResourceLoader；不导入旧启动器、不改SDK实例或prototype。
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { selectResources, verifySelection } from "./resource-selection.ts";
import { types } from "node:util";

const fail = (code = "pi-resource-invalid") => { throw new Error(code); };
const settingsMethods = ["getPackages", "getExtensionPaths", "getSkillPaths", "getPromptTemplatePaths", "getThemePaths"];
const stripBom = text => text.replace(/^\uFEFF/, "");
const mapHas = Map.prototype.has, mapGet = Map.prototype.get;
function freezeObservation(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freezeObservation); Object.freeze(value); }
  return value;
}

const guardInvalid = () => fail("pi-resource-command-guard-invalid");
function guardData(value) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) guardInvalid();
  const result = Object.create(null);
  for (const key of Reflect.ownKeys(value)) {
    const property = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !property?.enumerable || !Object.hasOwn(property, "value")) guardInvalid();
    result[key] = property.value;
  }
  return result;
}
function guardArray(value) {
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype || !Array.isArray(value)) guardInvalid();
  const length = Object.getOwnPropertyDescriptor(value, "length")?.value;
  if (!Number.isSafeInteger(length) || Reflect.ownKeys(value).length !== length + 1) guardInvalid();
  const result = [];
  for (let index = 0; index < length; index++) {
    const property = Object.getOwnPropertyDescriptor(value, String(index));
    if (!property?.enumerable || !Object.hasOwn(property, "value")) guardInvalid();
    result.push(property.value);
  }
  return result;
}
function validateCommandGuard(extensions, guard) {
  const loaded = guardData(extensions), rows = guardArray(loaded.extensions);
  const path = "<inline:" + guard.name + ">";
  let guards = 0;
  for (const row of rows) {
    const entry = guardData(row), handlers = entry.handlers;
    if (!handlers || types.isProxy(handlers) || Object.getPrototypeOf(handlers) !== Map.prototype
        || !types.isMap(handlers) || Reflect.ownKeys(handlers).length) guardInvalid();
    const present = mapHas.call(handlers, "user_bash");
    const list = present ? guardArray(mapGet.call(handlers, "user_bash")) : [];
    if (list.some(fn => typeof fn !== "function" || types.isProxy(fn))) guardInvalid();
    if (entry.path === path) {
      guards++;
      // 官方pi.on保存自有包装函数；公开元数据不暴露包装内的原callback身份。
      // 这里只验唯一注册形状，执行回调由下方自有guard投影固定，不能调用此包装取得权限。
      if (entry.resolvedPath !== path || list.length !== 1) guardInvalid();
    } else if (list.length) fail("pi-resource-command-guard-conflict");
  }
  if (guards !== 1) guardInvalid();
}

function emptySettings(settings) {
  for (const name of settingsMethods) {
    if (typeof settings?.[name] !== "function") fail("pi-sdk-incompatible");
    const values = settings[name]();
    if (!Array.isArray(values) || values.length) fail("pi-resource-settings-not-empty");
  }
}

function selectedFile(entry, group) {
  let path = entry.path;
  try {
    if (lstatSync(path).isDirectory() && group === "skills") path = join(path, "SKILL.md");
    if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink() || realpathSync(path) !== path) fail();
  } catch { fail("pi-resource-sdk-path-unrepresentable"); }
  return path;
}

function exactPaths(actual, expected) {
  if (!Array.isArray(actual) || actual.some(path => typeof path !== "string") || new Set(actual).size !== actual.length
      || JSON.stringify([...actual].sort()) !== JSON.stringify([...expected].sort())) fail("pi-resource-loaded-path");
}

function diagnostics(value) {
  if (!Array.isArray(value) || value.some(item => item?.type !== "warning")) fail("pi-resource-load-failed");
}

export function createOfficialResources({ sdk, manifest, installed, instanceRoot, runtimeRoot, cwd, engine, settingsManager, extensionFactories = [], commandGuard }) {
  emptySettings(settingsManager);
  if (typeof sdk?.DefaultResourceLoader !== "function") fail("pi-sdk-incompatible");
  if (!installed?.resources || typeof installed.resources !== "object") fail();
  const selection = selectResources({ manifest, installed: installed.resources, instanceRoot, runtimeRoot, cwd, engine });
  if (!Array.isArray(extensionFactories)) fail("pi-resource-inline-invalid");
  const names = new Set();
  const factories = extensionFactories.map(input => {
    if (!input || Object.keys(input).sort().join(",") !== "factory,name" || typeof input.factory !== "function"
        || typeof input.name !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(input.name) || names.has(input.name)) fail("pi-resource-inline-invalid");
    names.add(input.name); return Object.freeze({ name: input.name, factory: input.factory });
  });
  let guard;
  if (commandGuard !== undefined) {
    const input = guardData(commandGuard);
    if (Object.keys(input).sort().join(",") !== "handler,name" || typeof input.name !== "string"
        || factories.filter(row => row.name === input.name).length !== 1
        || typeof input.handler !== "function" || types.isProxy(input.handler)) guardInvalid();
    guard = Object.freeze({ name: input.name, handler: input.handler });
  }
  const expected = Object.fromEntries(["skills", "prompts", "themes"].map(group => [group, selection.resources[group].map(entry => selectedFile(entry, group))]));
  for (const entry of selection.resources.extensions) {
    const info = lstatSync(entry.path);
    if (!info.isFile() && !info.isDirectory()) fail("pi-resource-sdk-path-unrepresentable");
  }
  const options = {
    cwd, agentDir: join(instanceRoot, "pi-home"), settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: selection.resources.extensions.map(entry => entry.path),
    additionalSkillPaths: selection.resources.skills.map(entry => entry.path),
    additionalPromptTemplatePaths: selection.resources.prompts.map(entry => entry.path),
    additionalThemePaths: selection.resources.themes.map(entry => entry.path), extensionFactories: factories,
    // 空字符串防止SYSTEM.md自动发现；AGENTS和APPEND均为已选择的显式输入。
    systemPrompt: "", appendSystemPrompt: [selection.append.path],
    agentsFilesOverride: () => ({ agentsFiles: [{ path: selection.rules.path, content: readFileSync(selection.rules.path, "utf8") }] }),
  };
  const native = new sdk.DefaultResourceLoader(options);
  const methods = ["getExtensions", "getSkills", "getPrompts", "getThemes", "getAgentsFiles", "getSystemPrompt", "getSystemPromptSource", "getAppendSystemPrompt", "getAppendSystemPromptSources", "extendResources", "reload"];
  if (methods.some(name => typeof native[name] !== "function")) fail("pi-sdk-incompatible");
  let ready = false;
  let reloading = false;

  function validateLoaded() {
    verifySelection(selection); emptySettings(settingsManager);
    const extensions = native.getExtensions();
    // 仅公开Extension.handlers只读检查；此时扩展已初始化，不能声称隔离其代码。
    if (guard) validateCommandGuard(extensions, guard);
    if (!Array.isArray(extensions?.errors) || extensions.errors.length) fail("pi-resource-load-failed");
    if (!Array.isArray(extensions.extensions)) fail("pi-resource-loaded-path");
    exactPaths(extensions.extensions.map(item => item.path), [...selection.resources.extensions.map(entry => entry.path), ...factories.map(input => "<inline:" + input.name + ">")]);
    for (const item of extensions.extensions) {
      const selected = selection.resources.extensions.find(entry => entry.path === item.path);
      if (!selected) { if (item.resolvedPath !== item.path) fail("pi-resource-loaded-path"); continue; }
      const path = item.resolvedPath;
      if (typeof path !== "string" || !isAbsolute(path) || resolve(path) !== path) fail("pi-resource-loaded-path");
      const rel = relative(selected.path, path);
      if (lstatSync(selected.path).isFile() ? path !== selected.path : rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel)) fail("pi-resource-loaded-path");
      try { if (!lstatSync(path).isFile() || realpathSync(path) !== path) fail(); }
      catch { fail("pi-resource-loaded-path"); }
    }
    for (const [group, getter, field] of [["skills", "getSkills", "filePath"], ["prompts", "getPrompts", "filePath"], ["themes", "getThemes", "sourcePath"]]) {
      const result = native[getter](); diagnostics(result?.diagnostics);
      if (!Array.isArray(result[group])) fail("pi-resource-loaded-path");
      exactPaths(result[group].map(item => item[field]), expected[group]);
    }
    const agents = native.getAgentsFiles()?.agentsFiles;
    if (!Array.isArray(agents) || agents.length !== 1 || agents[0]?.path !== selection.rules.path
        || agents[0].content !== readFileSync(selection.rules.path, "utf8")) fail("pi-resource-loaded-path");
    // 官方resolvePromptInput把显式空字符串归一为undefined；空字符串仍阻止自动发现。
    if (native.getSystemPrompt() !== undefined || native.getSystemPromptSource() !== undefined) fail("pi-resource-loaded-path");
    if (JSON.stringify(native.getAppendSystemPrompt()) !== JSON.stringify([stripBom(readFileSync(selection.append.path, "utf8"))])) fail("pi-resource-loaded-path");
    const appendSources = native.getAppendSystemPromptSources();
    if (!Array.isArray(appendSources)) fail("pi-resource-loaded-path");
    exactPaths(appendSources.map(item => item.path), [selection.append.path]);
    return extensions;
  }

  const resourceLoader = Object.fromEntries(methods.filter(name => !["reload", "extendResources"].includes(name)).map(name => [name, () => {
    if (!ready) fail("pi-resource-not-loaded");
    const loaded = validateLoaded();
    if (name === "getExtensions" && guard) {
      // pi.on在初始化完成后仍合法；每个runner取得自有投影，固定拒绝器始终首位。
      // 守卫使用自有Extension/Map投影及可信原回调；其它对象/顺序保持，不改SDK缓存。
      const path = "<inline:" + guard.name + ">";
      const first = loaded.extensions.find(extension => extension.path === path);
      const handlers = new Map(first.handlers);
      handlers.set("user_bash", Object.freeze([guard.handler]));
      const fixedGuard = Object.freeze({ ...first, handlers });
      return Object.freeze({ ...loaded, extensions: Object.freeze([fixedGuard,
        ...loaded.extensions.filter(extension => extension !== first)]) });
    }
    return native[name]();
  }]));
  resourceLoader.reload = async reloadOptions => {
    if (reloading) fail("pi-resource-reload-in-progress");
    reloading = true;
    ready = false;
    try {
      verifySelection(selection); emptySettings(settingsManager);
      await native.reload(reloadOptions);
      validateLoaded(); ready = true;
    } finally { reloading = false; }
  };
  resourceLoader.extendResources = paths => {
    if (!ready) fail("pi-resource-not-loaded");
    validateLoaded();
    if (!paths || typeof paths !== "object" || Array.isArray(paths)) fail("pi-resource-extension-scope");
    for (const [key, entries] of Object.entries(paths)) {
      const group = { skillPaths: "skills", promptPaths: "prompts", themePaths: "themes" }[key];
      if (!group || !Array.isArray(entries) || entries.some(item => !item || Object.keys(item).some(name => !["path", "metadata"].includes(name))
          || !selection.resources[group].some(selected => selected.path === item.path))) fail("pi-resource-extension-scope");
    }
    native.extendResources(paths); validateLoaded();
  };
  const observeLoadedResources = () => {
    if (!ready) fail("pi-resource-not-loaded");
    validateLoaded();
    const groups = ["extensions", "skills", "prompts", "themes"];
    const rows = entries => entries.map(entry => ({ id: entry.id, scope: entry.scope }));
    const count = Object.values(selection.resources).reduce((total, entries) => total + entries.length, factories.length);
    if (count > 4096) fail("pi-resource-observation-invalid");
    // 只从已重验的自有selection投影，不复制SDK缓存、路径、正文或逐文件摘要。
    const observed = { schemaVersion: 1, scope: "in-memory-public-sdk-load", resourcesDigest: selection.digest,
      resources: Object.fromEntries(groups.map(group => [group, rows(selection.resources[group])])),
      inlineExtensions: factories.map(input => input.name), selectedRoles: rows(selection.resources.roles), rolesEvidence: "selection-only" };
    if (Buffer.byteLength(JSON.stringify(observed), "utf8") > 65536) fail("pi-resource-observation-invalid");
    return freezeObservation(observed);
  };
  return Object.freeze({ resourceLoader: Object.freeze(resourceLoader), selection, observeLoadedResources });
}
