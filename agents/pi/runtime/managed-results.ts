// receipt 是不可变关联记录；模型声称“完成”不能代替监督者的终止/文件证明。
import { canonical, closed, reject, sha, text } from "./managed-types.ts";

function model(value) {
  closed(value, ["provider_id", "model_id"]);
  if (!text(value.provider_id) || !text(value.model_id)) reject();
}
export function assertReceipt(value) {
  closed(value, ["receipt_id", "task_id", "step_id", "attempt_id", "manager_run_id", "candidate_digest", "request_digest",
    "runtime_digest", "policy_digest", "final_artifact_digest", "check_results", "requested_model", "observed_model",
    "terminal_status", "termination_confirmed", "external_work_empty", "sequence_complete"]);
  if (["receipt_id", "task_id", "step_id", "attempt_id", "manager_run_id"].some(key => !text(value[key]))
      || ["candidate_digest", "request_digest", "runtime_digest", "policy_digest"].some(key => !sha(value[key]))
      || !(value.final_artifact_digest === null || sha(value.final_artifact_digest))
      || !["completed", "failed", "canceled", "timeout"].includes(value.terminal_status)
      || ["termination_confirmed", "external_work_empty", "sequence_complete"].some(key => typeof value[key] !== "boolean")
      || !Array.isArray(value.check_results)) reject();
  model(value.requested_model);
  if (value.observed_model !== null) model(value.observed_model);
  const checks = new Set();
  for (const check of value.check_results) {
    closed(check, ["check_id", "candidate_digest", "status", "artifact_digest"]);
    if (!text(check.check_id) || checks.has(check.check_id) || check.candidate_digest !== value.candidate_digest
        || !["passed", "failed", "not-run"].includes(check.status) || !(check.artifact_digest === null || sha(check.artifact_digest))) reject();
    checks.add(check.check_id);
  }
  return value;
}

export function assertReceiptAssociation(receipt, run, proof) {
  assertReceipt(receipt);
  const descriptor = run.descriptor;
  if (["task_id", "step_id", "attempt_id"].some(key => receipt[key] !== descriptor[key]) || receipt.manager_run_id !== run.manager_run_id
      || receipt.request_digest !== run.descriptor_digest || receipt.runtime_digest !== descriptor.runtime_digest
      || receipt.policy_digest !== descriptor.policy_digest) reject("EVIDENCE_IDENTITY", 4);
  if (descriptor.write_roots.length) {
    if (proof.mutation_chain_verified !== true || proof.initial_candidate_digest !== descriptor.snapshot_digest
        || receipt.candidate_digest !== proof.candidate_digest) reject("SNAPSHOT_STALE", 4);
  } else if (receipt.candidate_digest !== descriptor.snapshot_digest || proof.candidate_digest !== descriptor.snapshot_digest) reject("SNAPSHOT_STALE", 4);
  const requested = { provider_id: descriptor.provider_id, model_id: descriptor.model_id };
  if (canonical(receipt.requested_model) !== canonical(requested)
      || receipt.observed_model !== null && canonical(receipt.observed_model) !== canonical(requested)) reject("MODEL_MISMATCH", 5);
  if (!receipt.termination_confirmed || !receipt.external_work_empty || !receipt.sequence_complete || !run.sequence_complete
      || proof.termination_confirmed !== true || proof.external_work_empty !== true || proof.lease_id !== run.lease_id) reject("TERMINATION_UNKNOWN", 4);
  if (!Object.values(run.last_events ?? {}).some(event => event.termination_confirmed && event.result_digest === receipt.final_artifact_digest
      && event.active_tool_ids.length === 0 && event.external_work_ids.length === 0)) reject("EVIDENCE_MISSING", 5);
  if (receipt.final_artifact_digest !== proof.artifact_digest
      || receipt.terminal_status === "completed" && (!sha(receipt.final_artifact_digest) || proof.artifact_nonempty !== true)) reject("EVIDENCE_MISSING", 5);
}
