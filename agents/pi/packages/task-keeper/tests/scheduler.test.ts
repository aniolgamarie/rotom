import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { Scheduler, validatePlan, type PlanStep } from "../src/orchestration/scheduler.ts";
import { Store } from "../src/store/database.ts";
import { Artifacts } from "../src/store/artifacts.ts";
import type { TaskSpec } from "../src/contracts/task.ts";
import { isolatedDirectory } from "./helpers.ts";

const spec = (id: string): TaskSpec => ({ id, workScope: "parent", version: 1, objective: "bounded task", workflow: "inspect", required: ["scope-check"], optional: [], allowPartial: false,
  policyDigest: "policy", snapshot: "tree", maxSteps: 16, maxSemanticAttempts: 3 });
const step = (id: string, dependencies: string[] = []): PlanStep => ({ id, dependencies, allowedSkippedDependencies: [], role: "reader", kind: "read", optional: false, resources: [{ id: "slot", capacity: 1, units: 1 }] });

test("[S SCH-003 SCH-004 SCH-005 TK01 TK02] dependency validation and required failure only block dependent work", (t) => {
  for (const id of ["SCH-003", "SCH-005", "TK01"]) evidence(id, () => {
    assert.throws(() => validatePlan([step("a", ["b"]), step("b", ["a"])], 16));
    assert.throws(() => validatePlan([step("a", ["missing"])], 16));
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const queue = new Scheduler(store, store.claimOwner("parent", "owner"));
    queue.submit(spec("job"), [step("a"), step("b", ["a"]), step("c")], 0, 0);
    assert.equal(queue.next(0)!.stepId, "a");
    queue.dispatch("job", "a", "tree"); queue.finish("job", "a", { terminated: true, passed: false, artifactId: null }, 1);
    assert.equal(queue.next(1)!.stepId, "c");
    assert.throws(() => queue.dispatch("job", "b", "tree"));
    if(id === "SCH-003")acceptance("AC28","dependency-fail",{level:"S",observer:"durable-scheduler-plan-after-required-predecessor-failure",predicate:"dependent blocked independent ready",artifact:observerArtifact("dependency-fail",queue.job("job"))},()=>{assert.equal(queue.next(1)!.stepId,"c");assert.throws(()=>queue.dispatch("job","b","tree"));assert.equal(queue.job("job").steps.find(s=>s.id==="b")!.status,"pending");});

  });
});

test("[S SCH-006 TK03] ready aging beats newly arriving priority without preempting active steps", (t) => {
  for (const id of ["TK03"]) evidence(id, () => {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const queue = new Scheduler(store, store.claimOwner("parent", "owner"), 10);
    queue.submit(spec("old"), [step("a")], 0, 0); queue.next(0);
    queue.submit(spec("new"), [step("a")], 100, 1001);
    assert.equal(queue.next(1010)!.jobId, "old");
    queue.dispatch("old", "a", "tree"); assert.equal(queue.next(1020), null);
  });
});

test("[S SCH-007 TK04 TK05] final admission rechecks snapshot/control and atomically rolls back loser", (t) => {
  for (const id of ["TK04"]) evidence(id, () => {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const queue = new Scheduler(store, store.claimOwner("parent", "owner"));
    queue.submit(spec("a"), [step("a")], 0, 0); queue.submit(spec("b"), [step("a")], 0, 0);
    assert.throws(() => queue.dispatch("a", "a", "stale-tree"));
    queue.dispatch("a", "a", "tree"); assert.throws(() => queue.dispatch("b", "a", "tree"));
    assert.equal(queue.job("b").dispatched, 0); assert.equal(queue.job("b").steps[0].status, "pending");
    queue.pause("b"); queue.finish("a", "a", { terminated: true, passed: false, artifactId: null }, 1);
    assert.throws(() => queue.dispatch("b", "a", "tree"));
    queue.resume("b"); queue.dispatch("b", "a", "tree");
  });
});

test("[S SCH-002] model cannot choose a new budget scope and claims do not satisfy step dependencies", (t) => {
  for (const id of ["SCH-002"]) evidence(id, () => {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const queue = new Scheduler(store, store.claimOwner("parent", "owner"));
    assert.throws(() => queue.submit({ ...spec("bad"), workScope: "fresh-budget" }, [step("a")], 0, 0));
    queue.submit(spec("job"), [step("a"), step("b", ["a"])], 0, 0); queue.dispatch("job", "a", "tree");
    const artifacts = new Artifacts(store);
    const claim = artifacts.pin("job", "tree", "I passed", "claim");
    assert.throws(() => queue.finish("job", "a", { terminated: true, passed: true, artifactId: claim.id }, 1));
    const runtime = artifacts.pin("job", "tree", "observed execution", "runtime");
    queue.finish("job", "a", { terminated: true, passed: true, artifactId: runtime.id }, 1);
    assert.equal(queue.next(1)!.stepId, "b");
    acceptance("AC28","dependency-ready",{level:"S",observer:"durable-scheduler-real-runtime-artifact",predicate:"passed predecessor unlocks dependent",artifact:observerArtifact("dependency-ready",queue.job("job"))},()=>{assert.equal(queue.next(1)!.stepId,"b");assert.equal(queue.job("job").steps[0].status,"passed");});

    queue.cancel("job"); assert.throws(() => queue.resume("job")); assert.equal(queue.next(2), null);
  });
});

test("[S SCH-006 TK03] aging survives bounded slot contention instead of restarting after every high-priority run", (t) => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const queue = new Scheduler(store, store.claimOwner("parent", "owner"), 10), artifacts = new Artifacts(store);
  queue.submit(spec("old"), [step("work")], 0, 0);
  let selected = false;
  for (let round = 0; round < 5; round++) {
    const now = round * 10, id = `high-${round}`;
    queue.submit(spec(id), [step("work")], 2, now);
    const next = queue.next(now)!;
    if (next.jobId === "old") { selected = true; break; }
    queue.dispatch(next.jobId, next.stepId, "tree");
    assert.equal(queue.next(now + 1), null);
    const artifact = artifacts.pin(next.jobId, "tree", "completed bounded work", "runtime");
    queue.finish(next.jobId, next.stepId, { passed: true, terminated: true, artifactId: artifact.id }, now + 9);
  }
  acceptance("AC28","aging",{level:"S",observer:"same-owner-scheduler-with-completed-competing-work",predicate:"ready age survives bounded contention",artifact:observerArtifact("aging",{selected,old:queue.job("old"),first:queue.job("high-0")})},()=>{assert.equal(selected,true);assert.equal(queue.next(50)!.jobId,"old");assert.equal(queue.job("old").steps[0].readyAt,0);assert.equal(queue.job("high-0").steps[0].status,"passed");});
  for (const id of ["SCH-006", "TK03"]) evidence(id, () => {
    assert.equal(selected, true); assert.equal(queue.next(50)!.jobId, "old");
    assert.equal(queue.job("old").steps[0].readyAt, 0); assert.equal(queue.job("old").dispatched, 0);
    assert.equal(queue.job("high-0").steps[0].status, "passed");
  });
});

test("[S] only an explicitly optional predecessor may be skipped for an opted-in dependent", (t) => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const queue = new Scheduler(store, store.claimOwner("parent", "owner"));
  const upstream = { ...step("optional"), optional: true };
  const downstream = { ...step("consumer", ["optional"]), allowedSkippedDependencies: ["optional"] };
  queue.submit(spec("job"), [upstream, downstream], 0, 0);
  assert.throws(() => queue.skipOptional("job", "consumer", "skip required", 1));
  queue.skipOptional("job", "optional", "not needed for this task", 1);
  assert.equal(queue.next(1)!.stepId, "consumer");
  assert.throws(() => validatePlan([{ ...upstream, optional: false }, downstream], 16));
});
