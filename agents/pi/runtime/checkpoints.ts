// UI代码快照与普通写工具共享同一manager和supervisor。
import { randomUUID } from "node:crypto";
import { assertSessionBoundary } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

export function checkpointClient(runtime, context) {
  const args = () => {
    if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore()
        || !Object.hasOwn(runtime.manifest.resource_ids?.extensions ?? {}, "git-checkpoint")) reject("CHECKPOINT_CONTEXT_UNAVAILABLE", 4);
    const session_id = context.sessionManager.getSessionId();
    if (!session_id) reject("CHECKPOINT_SESSION_REQUIRED", 4);
    return { cwd: context.cwd, session_id };
  };
  const run = async payload => {
    const ticket = await runtime.supervisor.call("ordinary_checkpoint_prepare", { ...args(), ...payload, operation_id: randomUUID() });
    return runtime.ordinaryOperations.write(ticket, null, null, undefined);
  };
  return {
    async capture(entry_id) { await assertSessionBoundary(runtime); return run({ operation: "capture", ...(entry_id ? { entry_id } : {}) }); },
    async list(entry_id) { return runtime.supervisor.call("ordinary_checkpoint_list", { ...args(), ...(entry_id ? { entry_id } : {}) }); },
    async preview(checkpoint_id) { await assertSessionBoundary(runtime); return runtime.supervisor.call("ordinary_checkpoint_preview", { ...args(), checkpoint_id }); },
    async restore(preview) {
      await assertSessionBoundary(runtime);
      return run({ operation: "restore", checkpoint_id: preview.checkpoint_id, before_digest: preview.before_digest, scope_digest: preview.scope_digest });
    },
  };
}
