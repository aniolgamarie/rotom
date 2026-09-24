import { test, assert, evidence } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import type { QueuedJob } from "../src/orchestration/scheduler.ts";

test("[S RTB-015 T80] critique revision and same-model repair share persistent semantic step and request accounting", t => {
  const f = completedState(t, false, true, ["direct", "critique"]), budget = `work-${f.owner.scopeId}`;
  f.store.prepare(f.owner, "history", "model", {});
  f.store.reserveRequest(f.owner, "history", "spent", [{ id: budget, ceiling: 12 }]); f.store.settleRequest("spent", "sent");
  f.store.reserveRequest(f.owner, "history", "uncertain", [{ id: budget, ceiling: 12 }]); f.store.settleRequest("uncertain", "unknown");
  const originalBudget = f.store.bucket(budget);
  let job = f.service.get(f.jobId); job.reason = "critic_revision_pending"; job.critiquesUsed = 1; f.store.put("managed-jobs", f.jobId, job);
  f.finalize(); job = f.service.get(f.jobId); assert.equal(job.semanticAttempts, 2); assert.equal(job.reason, "bounded_semantic_repair");
  const attempt = f.queue.dispatch(f.jobId, "implement", "tree"); f.store.markSent(f.owner, attempt.id);
  f.queue.finish(f.jobId, "implement", { terminated: true, passed: false, artifactId: null }, 2);
  job = f.service.get(f.jobId); job.reason = "repair_pending"; f.store.put("managed-jobs", f.jobId, job); f.finalize();
  job = f.service.get(f.jobId);
  for (const id of ["RTB-015", "T80"]) evidence(id, () => {
    assert.equal(job.semanticAttempts, 3); assert.equal(job.upgradesUsed ?? 0, 0); assert.equal(job.critiquesUsed, 1); assert.equal(job.routes?.implement ?? "primary", "primary");
    assert.deepEqual(f.store.bucket(budget), originalBudget); assert.equal(f.queue.job(f.jobId).dispatched, 6); assert.equal(f.store.list("managed-jobs").length, 1);
  });
  job.reason = "critic_revision_pending"; f.store.put("managed-jobs", f.jobId, job); f.finalize();
  for (const id of ["RTB-015", "T80"]) evidence(id, () => {
    assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.equal(f.service.get(f.jobId).reason, "work_scope_semantic_limit");
    assert.equal(f.service.get(f.jobId).semanticAttempts, 3); assert.deepEqual(f.store.bucket(budget), originalBudget);
  });
});

test("[S WFL-007 T72] unfinished work at the step ceiling cannot create a replacement job or discard its checks", t => {
  const f = completedState(t), before = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
  plan.dispatched = 16; plan.steps.find(step => step.id === "focused-tests")!.status = "pending"; f.store.put("jobs", f.jobId, plan); f.finalize();
  for (const id of ["WFL-007", "T72"]) evidence(id, () => {
    const job = f.service.get(f.jobId); assert.equal(job.status, "BLOCKED"); assert.equal(job.reason, "step_budget_exhausted");
    assert.equal(job.cwd, before.cwd); assert.equal(job.snapshot, before.snapshot); assert.equal(job.semanticAttempts, before.semanticAttempts);
    assert.equal(f.store.get<QueuedJob>("jobs", f.jobId)!.dispatched, 16);
    assert.throws(() => f.service.submit("fix", "restart under a new job"), { code: "WORK_SCOPE_STEP_LIMIT" });
    assert.equal(f.store.list("managed-jobs").length, 1); assert.deepEqual(f.queue.job(f.jobId).spec.required, ["build", "focused-tests", "independent-review"]);
  });
  const allowed = completedState(t), near = allowed.queue.job(allowed.jobId); near.dispatched = 15;
  near.steps.find(step => step.id === "focused-tests")!.status = "pending"; allowed.store.put("jobs", allowed.jobId, near); allowed.finalize();
  assert.equal(allowed.service.get(allowed.jobId).status, "RUNNING"); allowed.queue.dispatch(allowed.jobId, "focused-tests", "tree");
  assert.equal(allowed.queue.job(allowed.jobId).dispatched, 16);
});
