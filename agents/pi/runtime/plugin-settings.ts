// 插件配置只读 agentcfg 清单；插件自己的运行状态仍保存在所选实例。
import { clone, reject } from "./managed-types.ts";
import { realpathSync } from "node:fs";
import { relative, isAbsolute, sep } from "node:path";

export function pluginSettings(capability, key) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager" || !runtime.manifest.plugins.includes(capability)) reject("CAPABILITY_NOT_SELECTED", 5);
  const value = runtime.manifest.options[key] ?? {};
  if (!value || typeof value !== "object" || Array.isArray(value)) reject("PLUGIN_CONFIG_INVALID", 2);
  return clone(value);
}
export function pluginAgentDir() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager" || typeof runtime.instanceRoot !== "string" || !isAbsolute(runtime.instanceRoot)) reject("CAPABILITY_MISSING", 5);
  return runtime.instanceRoot + "/pi-home";
}
export function managedSettingWrite() {
  throw new Error("此设置由 agentcfg 管理；请更新机器覆盖并重新部署。");
}
export function pluginProjectRoot(cwd) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") reject("CAPABILITY_MISSING", 5);
  const directory = realpathSync(cwd);
  const roots = Object.values(runtime.manifest.options.paths?.roots ?? {}).filter(row => row.purpose === "project").map(row => realpathSync(row.path))
    .filter(root => { const tail = relative(root, directory); return tail === "" || tail !== ".." && !tail.startsWith(".." + sep) && !isAbsolute(tail); });
  return roots.sort((left, right) => right.length - left.length)[0] ?? null;
}
