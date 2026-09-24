import { test, assert } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { Store } from "../src/store/database.ts";

test("[S] diagnostic replanning changes the fixed graph once and atomically retains its root limits", t => {
  const f = completedState(t), plan = f.queue.job(f.jobId); plan.spec.maxSemanticReplans = 1; f.store.put("jobs", f.jobId, plan);
  const original = f.queue.job(f.jobId), managed = f.service.get(f.jobId);
  assert.throws(() => f.queue.retryFrom(f.jobId, "implement", true, () => {
    f.store.put("managed-jobs", f.jobId, { ...managed, semanticAttempts: 2 }); throw new Error("replan commit rejected");
  }), /replan commit rejected/);
  assert.deepEqual(f.queue.job(f.jobId), original); assert.equal(f.service.get(f.jobId).semanticAttempts, 1); assert.deepEqual(f.store.list("plan-revisions"), []);
  f.queue.retryFrom(f.jobId, "implement", true, () => f.store.put("managed-jobs", f.jobId, { ...managed, semanticAttempts: 2 }));
  const revised = f.queue.job(f.jobId), diagnosis = revised.steps.find(step => step.id === "replan:diagnose:1")!;
  assert.equal(revised.semanticReplans, 1); assert.equal(diagnosis.kind, "read"); assert.equal(diagnosis.role, "scout"); assert.equal(diagnosis.optional, false);
  assert.deepEqual(revised.steps.find(step => step.id === "implement")!.dependencies, [diagnosis.id]); assert.deepEqual(revised.spec, original.spec);
  assert.equal(revised.dispatched, original.dispatched); assert.equal(f.service.get(f.jobId).semanticAttempts, 2);
  assert.throws(() => f.queue.retryFrom(f.jobId, "implement", true), { code: "REPLAN_LIMIT_OR_TEMPLATE_DENIED" });
  assert.deepEqual(f.queue.job(f.jobId), revised); f.queue.retryFrom(f.jobId, "implement"); assert.equal(f.queue.job(f.jobId).semanticReplans, 1);
  const reopened = new Store(f.store.root); t.after(() => reopened.close());
  assert.equal(reopened.get<{semanticReplans:number}>("jobs", f.jobId)!.semanticReplans, 1);
  const denied = f.queue.job(f.jobId); denied.spec.maxSemanticReplans = 0; denied.semanticReplans = 0; f.store.put("jobs", f.jobId, denied);
  assert.throws(() => f.queue.retryFrom(f.jobId, "implement", true), {code:"REPLAN_LIMIT_OR_TEMPLATE_DENIED"});
  denied.spec.maxSemanticReplans = 2; denied.steps.find(step => step.id === diagnosis.id)!.status = "unknown"; f.store.put("jobs", f.jobId, denied);
  assert.throws(() => f.queue.retryFrom(f.jobId, "implement", true), {code:"EXECUTION_NOT_RECONCILED"});
});


test("[S] changed candidate resume reruns the existing diagnostic without allocating another replan", async t => {
  const f = completedState(t), plan = f.queue.job(f.jobId); plan.spec.maxSemanticReplans = 1; f.store.put("jobs", f.jobId, plan);
  f.queue.retryFrom(f.jobId, "implement", true); f.service.pause(f.jobId);
  const interrupted = f.queue.job(f.jobId); interrupted.steps.find(step => step.id === "replan:diagnose:1")!.status = "failed";
  f.store.put("jobs", f.jobId, interrupted);
  const internal = f.service as unknown as {capture(): Promise<unknown>};
  internal.capture = async () => ({ snapshot: { id: "changed-tree", files: [] }, patch: "changed candidate" });
  await f.service.resume(f.jobId);
  const resumed = f.queue.job(f.jobId);
  assert.equal(resumed.semanticReplans, 1); assert.equal(resumed.steps.filter(step => step.id.startsWith("replan:diagnose:")).length, 1);
  assert.equal(resumed.steps.find(step => step.id === "replan:diagnose:1")!.status, "pending");
  assert.deepEqual(resumed.steps.find(step => step.id === "implement")!.dependencies, ["replan:diagnose:1"]);
  assert.equal(resumed.spec.snapshot, "changed-tree"); assert.equal(f.service.get(f.jobId).semanticAttempts, 1);
  assert.equal(f.queue.next(Date.now())!.stepId, "replan:diagnose:1");
});
