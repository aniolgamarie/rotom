import { test, assert } from "./recorded-test.ts";
import { unlinkSync } from "node:fs";
import { join } from "node:path";
import { completedState } from "./fixtures/service-state.ts";
import { barrier } from "./helpers.ts";
import { verificationInputs } from "../src/verification/inputs.ts";

for (const change of ["unchanged", "spec-revision", "artifact-loss", "receipt-replaced"] as const)
test(`[S EVD-012] receipt inspection rechecks ${change} after awaiting candidate capture`, async t => {
  const f = completedState(t), job = f.service.get(f.jobId); job.modelBindings = {};
  job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
  f.store.put("managed-jobs", f.jobId, job); f.finalize();
  const previousProjection = f.service.describe(f.jobId);
  const before = structuredClone(f.service.get(f.jobId).receipt), captured = barrier<{ snapshot: { id: string }; patch: string }>(), started = barrier();
  (f.service as unknown as { capture(): Promise<unknown> }).capture = async () => { started.resolve(); return await captured.promise; };
  const pending = f.service.inspect(f.jobId); await started.promise;
  if (change === "spec-revision") { const plan = f.queue.job(f.jobId); plan.spec.version++; f.store.put("jobs", f.jobId, plan); }
  else if (change === "artifact-loss") { const artifact = f.service.get(f.jobId).checks.find(check => check.checkId === "focused-tests")!.artifactId!; unlinkSync(join(f.store.root, "artifacts", artifact)); }
  else if (change === "receipt-replaced") {
    const current = f.service.get(f.jobId); current.status = "BLOCKED"; current.reason = "required_recheck";
    current.receipt = { ...current.receipt!, status: "BLOCKED", reasons: ["required_recheck"] }; f.store.put("managed-jobs", f.jobId, current);
  }
  captured.resolve({ snapshot: { id: "tree" }, patch: "" }); const result = await pending;
  if (change === "unchanged") { assert.equal(result.receiptCurrent, true); assert.equal(result.status, "COMPLETED"); assert.deepEqual(result.receipt, previousProjection.receipt); }
  else {
    assert.equal(result.status, "BLOCKED"); assert.equal(result.receipt!.status, "BLOCKED");
    if (change !== "receipt-replaced") assert.equal(result.receiptCurrent, false);
  }
  if (change !== "receipt-replaced") assert.deepEqual(f.service.get(f.jobId).receipt, before);
  assert.equal(f.queue.job(f.jobId).dispatched, 5); assert.equal(f.service.get(f.jobId).semanticAttempts, 1);
});
