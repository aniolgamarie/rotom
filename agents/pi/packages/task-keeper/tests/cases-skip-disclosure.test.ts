import { test, assert } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { presentReceipt } from "../src/contracts/task.ts";

test("[S EVD-011] optional skips remain visible in the receipt and context without demoting required checks", t => {
  const f = completedState(t, true), job = f.service.get(f.jobId);
  job.checks = job.checks.filter(check => check.checkId !== "extra"); f.store.put("managed-jobs", f.jobId, job);
  f.queue.retryFrom(f.jobId, "extra"); f.queue.skipOptional(f.jobId, "extra", "fixture_optional_skip", 1234); f.finalize();
  const receipt = f.service.get(f.jobId).receipt!, expected = [{ stepId: "extra", reason: "fixture_optional_skip", at: 1234 }];
  assert.equal(receipt.status, "PARTIAL"); assert.deepEqual(receipt.optionalGaps, ["extra"]);
  assert.deepEqual(receipt.skippedSteps, expected); assert.deepEqual(f.service.describe(f.jobId).skippedSteps, expected);
  assert.deepEqual(f.service.contextEvidence()[0].skippedSteps, expected); assert.ok(presentReceipt(receipt).includes("extra:fixture_optional_skip"));
  assert.deepEqual(f.queue.job(f.jobId).spec.required, ["build", "focused-tests", "independent-review"]);
  assert.equal(f.queue.job(f.jobId).dispatched, 5);
});
