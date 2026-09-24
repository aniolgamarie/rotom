import assert from "node:assert/strict";
import { test } from "node:test";
import { assertExecutionEvidence } from "../src/contracts/evidence.ts";
import { descriptor } from "../../../runtime/tests/fixtures.ts";
import { digest } from "@agentcfg/pi-runtime/managed-types";

test("Task Keeper accepts only its current attempt/candidate and physically verified result", () => {
  const value = descriptor(), attempt = { manager_run_id: "run", lease_id: "lease" };
  const receipt = { receipt_id: "receipt", task_id: value.task_id, step_id: value.step_id, attempt_id: value.attempt_id,
    manager_run_id: "run", candidate_digest: value.snapshot_digest, request_digest: digest(value), runtime_digest: value.runtime_digest,
    policy_digest: value.policy_digest, final_artifact_digest: "a".repeat(64), check_results: [],
    requested_model: { provider_id: value.provider_id, model_id: value.model_id }, observed_model: null,
    terminal_status: "completed", termination_confirmed: true, external_work_empty: true, sequence_complete: true };
  const proof = { lease_id: "lease", artifact_digest: receipt.final_artifact_digest, artifact_nonempty: true,
    candidate_digest: value.snapshot_digest, termination_confirmed: true, external_work_empty: true };
  assert.equal(assertExecutionEvidence(receipt, value, attempt, proof), receipt);
  for (const change of [{ termination_confirmed: false }, { artifact_nonempty: false }, { candidate_digest: "b".repeat(64) }]) {
    assert.throws(() => assertExecutionEvidence(receipt, value, attempt, { ...proof, ...change }));
  }
  assert.throws(() => assertExecutionEvidence({ ...receipt, attempt_id: "old-attempt" }, value, attempt, proof), /EVIDENCE_IDENTITY/);
  assert.throws(() => assertExecutionEvidence({ ...receipt, observed_model: { provider_id: "other", model_id: value.model_id } }, value, attempt, proof), /MODEL_MISMATCH/);
  assert.deepEqual(receipt.check_results, []); // 执行验证不凭空生成项目检查通过事实。
});
