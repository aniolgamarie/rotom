import { test, assert, evidence } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";

test("[S CFG-013 WFL-007 T72] resume preserves an exhausted job or workScope step limit before attempting new work", async t => {
  for (const limit of ["job", "scope", "available"] as const) {
    const f = completedState(t, false, false, ["direct"], config => { config.limits.dispatchedStepsPerWorkScope = limit === "scope" ? 10 : 16; });
    f.queue.retryFrom(f.jobId, "focused-tests"); const plan = f.queue.job(f.jobId), job = f.service.get(f.jobId);
    plan.dispatched = limit === "job" ? 16 : 15; job.status = "BLOCKED"; job.reason = "step_budget_exhausted";
    f.queue.pause(f.jobId); plan.paused = true; f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job);
    let captures = 0; (f.service as unknown as {capture():Promise<unknown>}).capture = async () => { captures++; return { snapshot: { id: "tree", files: [] }, patch: "" }; };
    if (limit === "available") {
      await f.service.resume(f.jobId); assert.equal(f.service.get(f.jobId).status, "RUNNING"); assert.equal(captures, 1);
    } else {
      await assert.rejects(f.service.resume(f.jobId), { code: limit === "job" ? "STEP_BUDGET_EXHAUSTED" : "WORK_SCOPE_STEP_LIMIT" });
      for (const id of ["CFG-013", "WFL-007", "T72"]) evidence(id, () => {
        assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.equal(f.service.get(f.jobId).reason, "step_budget_exhausted");
        assert.equal(f.queue.job(f.jobId).paused, true); assert.equal(f.queue.job(f.jobId).dispatched, plan.dispatched);
        assert.equal(f.service.get(f.jobId).controlEpoch, job.controlEpoch); assert.equal(captures, 0);
        assert.equal(f.store.list("managed-jobs").length, 1);
      });
    }
  }
});
