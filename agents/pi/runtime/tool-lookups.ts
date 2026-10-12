// 可选适配器主动登记只读查询；普通文件模块不导入或构造任何服务适配器。
import { reject } from "./managed-types.ts";
const registries = new WeakMap();

export function registerToolLookup(runtime, capability, lookup) {
  if (!runtime || typeof runtime !== "object" || typeof capability !== "string"
      || !/^[a-z][a-z0-9_-]{0,63}$/.test(capability) || typeof lookup !== "function") reject("TOOL_LOOKUP_INVALID", 2);
  let records = registries.get(runtime);
  if (!records) registries.set(runtime, records = new Map());
  if (records.has(capability) && records.get(capability) !== lookup) reject("TOOL_LOOKUP_CONFLICT", 4);
  records.set(capability, lookup);
}

export function isBoundExtensionTool(runtime, name) {
  for (const lookup of registries.get(runtime)?.values() ?? []) {
    const value = lookup(runtime, name);
    if (typeof value !== "boolean") reject("TOOL_LOOKUP_INVALID", 5);
    if (value) return true;
  }
  return false;
}
