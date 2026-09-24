// Task Keeper 再核对本次执行关联；模型声称通过不能替代程序检查与独立审查。
import { assertReceipt } from "@agentcfg/pi-runtime/managed-results";
import { canonical, digest, reject } from "@agentcfg/pi-runtime/managed-types";

export function assertExecutionEvidence(receipt: any, descriptor: any, attempt: any, proof: any) {
  assertReceipt(receipt);
  if (["task_id", "step_id", "attempt_id"].some(key => receipt[key] !== descriptor[key])
      || receipt.manager_run_id !== attempt.manager_run_id || receipt.request_digest !== digest(descriptor)
      || receipt.runtime_digest !== descriptor.runtime_digest || receipt.policy_digest !== descriptor.policy_digest
      || proof.lease_id !== attempt.lease_id) reject("EVIDENCE_IDENTITY", 4);
  const model = { provider_id: descriptor.provider_id, model_id: descriptor.model_id };
  if (canonical(receipt.requested_model) !== canonical(model) || receipt.observed_model !== null && canonical(receipt.observed_model) !== canonical(model)) reject("MODEL_MISMATCH", 5);
  if (!receipt.termination_confirmed || !receipt.external_work_empty || !receipt.sequence_complete
      || !proof.termination_confirmed || !proof.external_work_empty) reject("TERMINATION_UNKNOWN", 4);
  if (receipt.candidate_digest !== proof.candidate_digest || descriptor.write_roots.length
      && (proof.mutation_chain_verified !== true || proof.initial_candidate_digest !== descriptor.snapshot_digest)
      || !descriptor.write_roots.length && receipt.candidate_digest !== descriptor.snapshot_digest) reject("SNAPSHOT_STALE", 4);
  if (receipt.final_artifact_digest !== proof.artifact_digest || receipt.terminal_status === "completed" && proof.artifact_nonempty !== true) reject("EVIDENCE_MISSING", 5);
  return receipt;
}
