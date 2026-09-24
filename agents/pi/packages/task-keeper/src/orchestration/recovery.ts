// 恢复只读取监督证明；不迁移旧 session，也不把取消应答当成终止。
import type { Store, Owner } from "../store/database.ts";
import { ContractError } from "../contracts/primitives.ts";
import { importManagedUsage } from "../usage/managed.ts";

export async function reconcileManagedStep(store: Store, owner: Owner, supervisor: any, taskId: string, stepId: string) {
  store.assertOwner(owner);
  const attempts = store.list<any>("agentcfg-attempts-v1").map(row => row.value).filter(row => row.task_id === taskId && row.step_id === stepId);
  if (!attempts.length) return null;
  let neverStarted = true;
  for (const attempt of attempts) {
    const descriptor = store.get<any>("agentcfg-descriptors-v1", attempt.attempt_id);
    if (!descriptor) throw new ContractError("ATTEMPT_IDENTITY_CONFLICT");
    const observation = await supervisor.call("reconcile", { lease_id: descriptor.allocation_id });
    store.assertOwner(owner);
    importManagedUsage(store, taskId, descriptor);
    if (observation.protected || !observation.termination_evidence?.verified) return { stopped: false, neverStarted: false };
    neverStarted &&= observation.termination_evidence.kind === "never-started";
    store.put("agentcfg-attempt-termination-v1", attempt.attempt_id, { lease_id: attempt.lease_id ?? descriptor.allocation_id,
      termination_confirmed: true, resources_reclaimed: true, evidence_digest: observation.termination_evidence.evidence_digest });
    if (!["completed", "failed", "canceled", "timeout"].includes(attempt.state)) store.put("agentcfg-attempts-v1", attempt.attempt_id,
      { ...attempt, lease_id: attempt.lease_id ?? descriptor.allocation_id, state: "failed" });
  }
  return { stopped: true, neverStarted };
}
export function taskState(status: string): string {
  const values: Record<string, string> = { QUEUED: "queued", RUNNING: "running", WAITING_QUOTA: "waiting", PAUSED: "paused",
    BLOCKED: "blocked", COMPLETED: "completed", FAILED: "failed", CANCELLED: "canceled", PARTIAL: "blocked" };
  if (!values[status]) throw new ContractError("UNKNOWN_TASK_STATE");
  return values[status];
}
