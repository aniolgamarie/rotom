// 注册记录属于具体运行时；跨插件不得接管同名入口。
import { reject } from "./managed-types.ts";
const registries = new WeakMap();
export const reservedToolNames = new Set(["read", "write", "edit", "rename", "find", "grep", "ls", "bash", "editor", "process",
  "Agent", "kernel_task", "model_delegate", "get_subagent_result", "steer_subagent", "mcp", "mcpScript",
  "smart_compact", "smart_recall", "smart_save_memory",
  ...["edit", "grep", "search", "refs", "rename", "def", "digest", "view", "write"].map(name => "readSeek_" + name)]);
export const webToolNames = new Set(["web_search", "source_check", "fetch_content", "get_search_content"]);
export function claimTool(runtime, name, owner, prefix) {
  if (typeof name !== "string" || !name || name.length > 256 || /[\x00-\x20\x7f]/.test(name)
      || reservedToolNames.has(name) || prefix !== "WEB" && webToolNames.has(name)) reject(prefix + "_TOOL_NAME", 2);
  let records = registries.get(runtime);
  if (!records) registries.set(runtime, records = new Map());
  if (records.has(name) && records.get(name).owner !== owner) reject(prefix + "_TOOL_CONFLICT", 4);
  const record = { owner };
  records.set(name, record);
  return {
    current: () => records.get(name) === record && globalThis[Symbol.for("agentcfg.pi.runtime.v1")] === runtime,
    release: () => { if (records.get(name) === record) records.delete(name); },
  };
}
