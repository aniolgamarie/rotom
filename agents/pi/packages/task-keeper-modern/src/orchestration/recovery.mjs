import { ContractError } from "../contracts/primitives.mjs";
import { importManagedUsage } from "../usage/managed.mjs";
export async function reconcileManagedStep(store, owner, supervisor, taskId, stepId) {
    store.assertOwner(owner);
    const attempts = store.list("agentcfg-attempts-v1").map((row)=>row.value).filter((row)=>row.task_id === taskId && row.step_id === stepId);
    if (!attempts.length) return null;
    let neverStarted = true;
    for (const attempt of attempts){
        const descriptor = store.get("agentcfg-descriptors-v1", attempt.attempt_id);
        if (!descriptor) throw new ContractError("ATTEMPT_IDENTITY_CONFLICT");
        const observation = await supervisor.call("reconcile", {
            lease_id: descriptor.allocation_id
        });
        store.assertOwner(owner);
        importManagedUsage(store, taskId, descriptor);
        if (observation.protected || !observation.termination_evidence?.verified) return {
            stopped: false,
            neverStarted: false
        };
        neverStarted &&= observation.termination_evidence.kind === "never-started";
        store.put("agentcfg-attempt-termination-v1", attempt.attempt_id, {
            lease_id: attempt.lease_id ?? descriptor.allocation_id,
            termination_confirmed: true,
            resources_reclaimed: true,
            evidence_digest: observation.termination_evidence.evidence_digest
        });
        if (![
            "completed",
            "failed",
            "canceled",
            "timeout"
        ].includes(attempt.state)) store.put("agentcfg-attempts-v1", attempt.attempt_id, {
            ...attempt,
            lease_id: attempt.lease_id ?? descriptor.allocation_id,
            state: "failed"
        });
    }
    return {
        stopped: true,
        neverStarted
    };
}
export function taskState(status) {
    const values = {
        QUEUED: "queued",
        RUNNING: "running",
        WAITING_QUOTA: "waiting",
        PAUSED: "paused",
        BLOCKED: "blocked",
        COMPLETED: "completed",
        FAILED: "failed",
        CANCELLED: "canceled",
        PARTIAL: "blocked"
    };
    if (!values[status]) throw new ContractError("UNKNOWN_TASK_STATE");
    return values[status];
}
