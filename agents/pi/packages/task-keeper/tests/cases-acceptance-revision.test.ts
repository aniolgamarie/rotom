import { test, assert, evidence } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { verificationInputs } from "../src/verification/inputs.ts";

test("[S WFL-005 CFG-007 T46] approving changed checks retires the previous receipt while preserving its historical artifact", async t => {
  const f = completedState(t), job = f.service.get(f.jobId);
  const inputs = verificationInputs(f.config.verificationBindings, job.cwd!);
  job.status = "BLOCKED"; job.reason = "acceptance_inputs_changed"; job.modelBindings = {};
  job.checkInputChange = { digest: inputs.digest, artifact: "recorded-change" }; job.checkInputsDigest = "old-inputs";
  f.queue.pause(f.jobId); f.store.put("managed-jobs", f.jobId, job); f.finalize();
  const previous = f.service.get(f.jobId), saved = f.artifacts.read(previous.outputs.receipt, f.jobId, "tree").content;
  (f.service as unknown as { capture(): Promise<unknown> }).capture = async () => ({ snapshot: { id: "tree" }, patch: "" });
  await f.service.approveChecks(f.jobId, inputs.digest);
  for (const id of ["WFL-005", "CFG-007", "T46"]) evidence(id, () => {
    const current = f.service.get(f.jobId); assert.equal(f.queue.job(f.jobId).spec.version, 2); assert.equal(current.receipt, null);
    assert.equal(current.reason, "acceptance_revision_authorized"); assert.equal(current.status, "BLOCKED"); assert.deepEqual(current.checks, []);
    assert.equal(current.semanticAttempts, previous.semanticAttempts); assert.equal(f.queue.job(f.jobId).dispatched, 5);
    assert.deepEqual(f.artifacts.read(previous.outputs.receipt, f.jobId, "tree").content, saved);
    assert.ok(f.queue.job(f.jobId).steps.filter(step => ["verify", "review"].includes(step.kind)).every(step => step.status === "pending"));
  });
});

test("[S] a receipt from another TaskSpec revision cannot be presented as current", async t => {
  const f = completedState(t); f.finalize(); const job = f.service.get(f.jobId), original = structuredClone(job.receipt);
  job.modelBindings = {}; job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
  f.store.put("managed-jobs", f.jobId, job); const plan = f.queue.job(f.jobId); plan.spec.version++; f.store.put("jobs", f.jobId, plan);
  (f.service as unknown as { capture(): Promise<unknown> }).capture = async () => ({ snapshot: { id: "tree" }, patch: "" });
  const presented = await f.service.inspect(f.jobId);
  assert.equal(presented.receiptCurrent, false); assert.equal(presented.status, "BLOCKED"); assert.equal(presented.reason, "task_spec_revision_changed");
  const context = f.service.contextEvidence()[0]; assert.equal(context.status, "BLOCKED"); assert.equal(context.recordedStatus, "COMPLETED");
  assert.equal(context.receipt!.status, "BLOCKED"); assert.equal(context.receipt!.currentCandidate, false);
  assert.deepEqual(f.service.get(f.jobId).receipt, original);
});

test("[S] changing only evidence presentation capacity preserves acceptance while execution policy changes invalidate it", async t => {
  const f = completedState(t), job = f.service.get(f.jobId);
  job.modelBindings = {}; job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
  f.store.put("managed-jobs", f.jobId, job); f.finalize();
  (f.service as unknown as { capture(): Promise<unknown> }).capture = async () => ({ snapshot: { id: "tree" }, patch: "" });
  assert.equal((await f.service.inspect(f.jobId)).receiptCurrent, true);
  const original = structuredClone(f.service.get(f.jobId).receipt);
  f.config.evidence.packetByteBudget++;
  assert.equal((await f.service.inspect(f.jobId)).receiptCurrent, true); assert.deepEqual(f.service.get(f.jobId).receipt, original);
  f.config.budget.backupAttemptsPerIncident++;
  assert.equal((await f.service.inspect(f.jobId)).receiptCurrent, false); assert.deepEqual(f.service.get(f.jobId).receipt, original);
});
