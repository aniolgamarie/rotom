import { test, assert } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import type { Intent } from "../src/store/database.ts";
import { verificationInputs } from "../src/verification/inputs.ts";

for (const budgetState of ["sent", "unknown"] as const)
test(`[S RTB-012] a trusted local verification step runs with model budget ${budgetState} without spending or clearing it`, async t => {
  const f = completedState(t, false, false, ["direct"], config => {
    config.budget.protectedAttemptsPerWorkScope = 1;
    // Budget independence is under test; allow cold namespace/Node startup under the full suite.
    config.verificationBindings["focused-tests"].timeoutMs = 5000;
    config.verificationBindings["focused-tests"].args = ["-e", 'console.log(JSON.stringify({tests:1,passed:1,failed:0,skipped:0}))'];
  });
  const job = f.service.get(f.jobId), plan = f.queue.job(f.jobId), step = plan.steps.find(item => item.id === "focused-tests")!;
  step.status = "pending"; step.intentId = null; step.finishedAt = null; job.checks = job.checks.filter(check => check.checkId !== "focused-tests");
  job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
  f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job);
  f.store.prepare(f.owner, "prior-model", "model", {}); f.store.reserveRequest(f.owner, "prior-model", "prior-request", [{ id: `work-${job.workScope}`, ceiling: 1 }]);
  f.store.markSent(f.owner, "prior-model"); f.store.settleRequest("prior-request", budgetState); f.store.settle("prior-model", "terminated");
  const originalBudget = f.store.bucket(`work-${job.workScope}`); let modelCalls = 0;
  t.mock.method(SubagentsAdapter.prototype, "execute", async () => { modelCalls++; throw new Error("Local verification must not request a model"); });
  const internal = f.service as unknown as { capture(): Promise<unknown>; runStep(jobId: string, stepId: string, intent: Intent, epoch: number, signal: AbortSignal): Promise<void> };
  internal.capture = async () => ({ snapshot: { id: "tree", files: [] }, patch: "" });
  const intent = f.queue.dispatch(f.jobId, "focused-tests", "tree"); await internal.runStep(f.jobId, "focused-tests", intent, job.controlEpoch, new AbortController().signal);
  const current = f.service.get(f.jobId), verified = current.verification["focused-tests"];
  assert.equal(verified.status, "passed"); assert.equal(verified.terminationConfirmed, true); assert.equal(verified.counts!.tests, 1); assert.equal(verified.counts!.passed, 1);
  assert.equal(f.queue.job(f.jobId).steps.find(item => item.id === "focused-tests")!.status, "passed"); assert.equal(modelCalls, 0);
  assert.deepEqual(f.store.bucket(`work-${job.workScope}`), originalBudget); assert.equal(f.store.request("prior-request")!.state, budgetState);
  assert.equal(current.semanticAttempts, 1); assert.equal(f.store.intent(intent.id)!.status, "settled");
});
