// 模型请求占用现有 manager 的执行槽；HTTP/listener 资源不能替代模型执行记录。
import { randomUUID } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
export async function runWebModel(runtime, signal, invoke) {
  requireOrdinaryHelper(runtime, "pi-web"); signal.throwIfAborted();
  const entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (!entry?.manager || !entry.pi || !entry.getContext) reject("WEB_MANAGER_REQUIRED", 5);
  const serviceOwner = runtime.web.current().id;
  const manager = entry.manager, id = "web-model-" + randomUUID(), controller = new AbortController();
  const combined = AbortSignal.any([signal, controller.signal]);
  let started = false, settled = false, canceled = false, resolveOutcome;
  const outcome = new Promise(resolve => { resolveOutcome = resolve; });
  const proof = status => ({ response_text: "Web model request ended", terminal_status: status,
    termination_confirmed: true, external_work_empty: true });
  const cancel = async () => {
    canceled = true; controller.abort();
    if (!started) {
      settled = true; resolveOutcome({ error: new Error("WEB_MODEL_CANCELED") });
      return proof("canceled");
    }
    // 已开始的请求只在其 Promise 确实结束后释放；收到 abort 不是终止证明。
    if (settled) return proof("canceled");
    return undefined;
  };
  manager.spawnWithExecutor(entry.pi, entry.getContext(), "web-model", "WEB_MODEL_REQUEST", {
    kind: "external", activity: "model", manager_run_id: id, cancel,
    ...(serviceOwner ? { service_owner_run_id: serviceOwner } : {}),
    async execute() {
      if (settled) return proof("canceled");
      started = true;
      try {
        combined.throwIfAborted();
        if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_MODEL_STALE", 4);
        const value = await invoke(combined);
        combined.throwIfAborted();
        resolveOutcome({ value });
        return proof("completed");
      } catch (error) {
        resolveOutcome({ error }); return proof(canceled || combined.aborted ? "canceled" : "failed");
      } finally { settled = true; }
    },
  }, { description: "Web model helper", cwd: runtime.cwd, isBackground: true });
  const abort = () => { manager.abort(id); };
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  try {
    const result = await outcome;
    await manager.getRecord(id)?.promise;
    manager.consumeControlled(id); manager.removeConsumedControlled(id);
    if (result.error) throw result.error;
    return result.value;
  } finally { signal.removeEventListener("abort", abort); }
}
