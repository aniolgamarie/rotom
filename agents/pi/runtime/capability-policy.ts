// 普通会话的压缩由一个模型调用者负责；managed helper 必须走 Task Keeper transport。
import { reject } from "./managed-types.ts";

export function requireOrdinaryHelper(runtime, capability, serviceRunId = null) {
  if (!runtime || runtime.owner?.role !== "manager") reject("CAPABILITY_MISSING", 5);
  if (runtime.manifest.bootstrap) reject("UNBOUND_MODEL", 2);
  if (runtime.managedRequestScope?.getStore()) reject("UNMETERED_PARENT_HELPER", 5);
  const manager = globalThis[Symbol.for("agentcfg.pi.managed.v1")]?.manager;
  if (serviceRunId !== null && !["pi-mcp", "pi-readseek", "pi-web"].includes(capability)) reject("HELPER_SERVICE_ID_INVALID", 4);
  const active = typeof manager?.blocksOrdinaryHelpers === "function" ? manager.blocksOrdinaryHelpers(capability === "pi-web" ? serviceRunId : null)
    : serviceRunId && typeof manager?.listAgents === "function"
    ? manager.listAgents().some(row => row.id !== serviceRunId && ["running", "queued"].includes(row.status))
    : manager?.hasRunning();
  if (runtime.manifest.options.task_keeper?.enabled && active) reject("UNMETERED_PARENT_HELPER", 5);
  const selected = new Set([...runtime.manifest.plugins, ...Object.keys(runtime.manifest.resource_ids?.extensions ?? {})]);
  if (!selected.has(capability)) reject("CAPABILITY_NOT_SELECTED", 5);
}
export function compactionOwner(manifest) {
  const owner = manifest.options.compaction?.owner ?? "native";
  if (!["native", "smart-compact"].includes(owner) || (owner === "smart-compact") !== manifest.plugins.includes("pi-smart-compact")) reject("COMPACTION_OWNER_CONFLICT", 2);
  return owner;
}
export function mayTransformHistory(runtime) {
  return runtime?.owner?.role === "manager" && !runtime.managedRequestScope?.getStore();
}

export async function assertSessionBoundary(runtime) {
  if (!runtime?.supervisor || runtime.managedRequestScope?.getStore()) reject("SESSION_ACTIVITY_PROTECTED", 4);
  const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (entry?.manager.hasRunning() || entry?.manager.listAgents().some(row => entry.manager.isControlled(row.id) && !row.resultConsumed)) reject("SESSION_ACTIVITY_PROTECTED", 4);
  const summary = await runtime.supervisor.call("activity_summary", {});
  if (!Number.isSafeInteger(summary.active_count) || summary.active_count !== 0) reject("SESSION_ACTIVITY_PROTECTED", 4);
}
