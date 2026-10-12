// 历史宿主兼容入口；官方入口直接消费独立resource-selection，不导入本模块。
import { selectResources, restrictExtensions, loaderOptions, assertApprovedSelection } from "./resource-selection.ts";
export { selectResources, restrictExtensions, loaderOptions };
const policies = new WeakMap();
const fail = (code = "pi-resource-invalid") => { throw new Error(code); };
const empty = () => ({ extensions: [], skills: [], prompts: [], themes: [] });

export function installPackagePolicy(sdk, selection) {
  assertApprovedSelection(selection);
  const prototype = sdk.DefaultPackageManager?.prototype;
  if (!prototype || typeof prototype.resolve !== "function" || typeof prototype.resolveExtensionSources !== "function") fail("pi-sdk-incompatible");
  let policy = policies.get(prototype);
  if (!policy) {
    policy = { paths: new Set() };
    policies.set(prototype, policy);
    prototype.resolve = async () => empty();
    prototype.checkForAvailableUpdates = async () => [];
    prototype.resolveExtensionSources = async sources => {
      if (!Array.isArray(sources) || sources.some(path => !policy.paths.has(path))) fail();
      return { ...empty(), extensions: sources.map(path => ({ path, enabled: true,
        metadata: { source: "agentcfg", scope: "user", origin: "top-level" } })) };
    };
    // 固定 SDK 的所有安装/更新入口，UI 内部新建 package manager 也遵守同一规则。
    const methods = Object.getOwnPropertyNames(prototype).filter(name => /^(install|update|remove)/.test(name));
    for (const name of methods) prototype[name] = async () => { throw new Error("Use agentcfg lock/sync to manage packages"); };
  }
  policy.paths = new Set(selection.resources.extensions.map(entry => entry.path));
  policy.resources = selection.resources;
  const loader = sdk.DefaultResourceLoader?.prototype;
  if (loader && !policies.has(loader)) {
    policies.set(loader, policy);
    const extend = loader.extendResources;
    loader.extendResources = function (paths) {
      for (const [key, entries] of Object.entries(paths)) {
        const kind = { skillPaths: "skills", promptPaths: "prompts", themePaths: "themes" }[key];
        if (!kind || !Array.isArray(entries) || entries.some(item => !policy.resources[kind].some(allowed => allowed.path === item.path))) fail();
      }
      return extend.call(this, paths);
    };
  }
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
