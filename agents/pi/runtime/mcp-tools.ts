// 直接工具按真实登记记录准入，不从工具名前缀推断其权限来源。
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

import { claimTool } from "./tool-ownership.ts";

const registries = new WeakMap(), defaultOwners = new WeakMap();
function defaultOwner() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime) reject("MCP_RUNTIME_UNAVAILABLE", 5);
  if (!defaultOwners.has(runtime)) defaultOwners.set(runtime, captureMcpToolOwner());
  return defaultOwners.get(runtime);
}
export function captureMcpToolOwner() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime) reject("MCP_RUNTIME_UNAVAILABLE", 5);
  return Object.freeze({ runtime, servers: new Map() });
}
function selected(runtime, server, original) {
  requireOrdinaryHelper(runtime, "pi-mcp");
  const binding = runtime.manifest.options.mcp?.servers?.[server];
  if (!binding) reject("MCP_DIRECT_TOOL_UNSELECTED", 4);
  if (original === null) return;
  const value = binding.direct_tools;
  if (value?.enabled !== true || value.tools !== undefined && !(Array.isArray(value.tools) && value.tools.includes(original))) reject("MCP_DIRECT_TOOL_UNSELECTED", 4);
}
export function registerMcpTool(name, server, original, execute, owner = defaultOwner()) {
  const runtime = owner.runtime;
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("MCP_DIRECT_TOOL_STALE", 4);
  selected(runtime, server, original);
  if (typeof execute !== "function") reject("MCP_DIRECT_TOOL_NAME", 2);
  let records = registries.get(runtime);
  if (!records) registries.set(runtime, records = new Map());
  if (records.has(name) && records.get(name).server !== server) reject("MCP_DIRECT_TOOL_CONFLICT", 4);
  if (!owner.servers.has(server)) owner.servers.set(server, {});
  const claim = claimTool(runtime, name, owner.servers.get(server), "MCP_DIRECT");
  const record = { server, original, claim, owner };
  records.set(name, record);
  return async (...args) => {
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("MCP_DIRECT_TOOL_STALE", 4);
    selected(runtime, server, original);
    if (records.get(name) !== record || !claim.current()) reject("MCP_DIRECT_TOOL_STALE", 4);
    const result = await execute(...args);
    selected(runtime, server, original);
    if (records.get(name) !== record || !claim.current()) reject("MCP_DIRECT_TOOL_STALE", 4);
    return result;
  };
}
export function registerMcpNamespace(name, server, execute, owner = defaultOwner()) {
  if (name !== "mcp__" + server.replace(/[^a-zA-Z0-9_]/g, "_")) reject("MCP_NAMESPACE_NAME", 2);
  return registerMcpTool(name, server, null, execute, owner);
}
export function unregisterMcpTool(name, owner) {
  if (!owner?.runtime) reject("MCP_TOOL_OWNER_REQUIRED", 2);
  const records = registries.get(owner.runtime), record = records?.get(name);
  if (record?.owner === owner) { record.claim.release(); records.delete(name); }
}
export function isBoundMcpTool(runtime, name) {
  const record = registries.get(runtime)?.get(name);
  if (!record) return false;
  selected(runtime, record.server, record.original);
  return true;
}
