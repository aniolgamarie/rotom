import { test, assert, evidence } from "./recorded-test.ts";
import { Scheduler, validatePlan, type PlanStep } from "../src/orchestration/scheduler.ts";
import { Store } from "../src/store/database.ts";
import { Artifacts } from "../src/store/artifacts.ts";
import { isolatedDirectory } from "./helpers.ts";
const step = (id: string, dependencies: string[] = []): PlanStep => ({ id, dependencies, allowedSkippedDependencies: [], role: "reader", kind: "read", optional: false, resources: [] });
const spec = (id: string) => ({ id, workScope: "scope", version: 1, objective: "Dependency contract", workflow: "inspect" as const,
  required: ["check"], optional: [], allowPartial: false, policyDigest: "policy", snapshot: "tree", maxSteps: 8, maxSemanticAttempts: 3 });

test("[U SCH-004 TK02] every malformed dependency is rejected with a valid acyclic control", () => {
  for (const id of ["SCH-004", "TK02"]) evidence(id, () => {
    assert.doesNotThrow(() => validatePlan([step("a"), step("b", ["a"]), step("c", ["a", "b"])], 8));
    for (const [plan, code] of [
      [[step("a", ["missing"])], "INVALID_DEPENDENCY"], [[step("a", ["a"])], "INVALID_DEPENDENCY"],
      [[step("a", ["b"]), step("b", ["a"])], "DEPENDENCY_CYCLE"], [[step("a"), step("b", ["a", "a"])], "INVALID_DEPENDENCY"],
      [[step("a"), step("a")], "DUPLICATE_STEP"],
    ] as Array<[PlanStep[], string]>) assert.throws(() => validatePlan(plan, 8), { code });
  });
});

test("[S SCH-004 TK02] invalid submitted plans leave no persistent pseudo-ready work", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const queue = new Scheduler(store, store.claimOwner("scope", "owner"));
  for (const id of ["SCH-004", "TK02"]) evidence(id, () => {
    for (const plan of [[step("a", ["missing"])], [step("a", ["b"]), step("b", ["a"])]]) {
      assert.throws(() => queue.submit(spec("invalid"), plan, 0, 0));
      assert.equal(store.list("jobs").length, 0); assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0); assert.equal(queue.next(1), null);
    }
  });
  queue.submit(spec("valid"), [step("a"), step("b", ["a"])], 0, 0); assert.equal(queue.next(1)!.stepId, "a");
});

test("[S SCH-003 TK01] running failed and unknown prerequisites block only their descendants", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const queue = new Scheduler(store, store.claimOwner("scope", "owner"));
  for (const state of ["pending", "running", "failed", "unknown"] as const) {
    const job = `job-${state}`; queue.submit(spec(job), [step("upstream"), step("dependent", ["upstream"]), step("independent")], 0, 0);
    if (state !== "pending") queue.dispatch(job, "upstream", "tree");
    if (state === "failed" || state === "unknown") queue.finish(job, "upstream", { terminated: state === "failed", passed: false, artifactId: null }, 1);
    for (const id of ["SCH-003", "TK01"]) evidence(id, () => {
      assert.equal(queue.job(job).steps.find(s => s.id === "upstream")!.status, state);
      assert.throws(() => queue.dispatch(job, "dependent", "tree"), { code: "STEP_NOT_READY" });
      assert.equal(queue.job(job).steps.find(s => s.id === "dependent")!.status, "pending");
      assert.equal(queue.job(job).steps.find(s => s.id === "dependent")!.intentId, null);
    });
    const independent = queue.dispatch(job, "independent", "tree"); assert.equal(independent.status, "prepared");
  }
});

test("[S SCH-005] successful or explicitly skippable dependencies enable a single dispatch", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const queue = new Scheduler(store, store.claimOwner("scope", "owner")), artifacts = new Artifacts(store);
  queue.submit(spec("success"), [step("a"), step("b", ["a"])], 0, 0); queue.dispatch("success", "a", "tree");
  const proof = artifacts.pin("success", "tree", "authenticated execution result", "runtime");
  queue.finish("success", "a", { terminated: true, passed: true, artifactId: proof.id }, 1);
  assert.equal(queue.next(2)!.stepId, "b"); queue.dispatch("success", "b", "tree");
  assert.throws(() => queue.dispatch("success", "b", "tree"), { code: "STEP_NOT_READY" });
  for (const allowed of [false, true]) {
    const job = `optional-${allowed}`, upstream = { ...step("a"), optional: true }, downstream = { ...step("b", ["a"]), allowedSkippedDependencies: allowed ? ["a"] : [] };
    queue.submit(spec(job), [upstream, downstream], 0, 0); queue.skipOptional(job, "a", "no optional work needed", 1);
    if (allowed) { assert.doesNotThrow(() => queue.dispatch(job, "b", "tree")); assert.throws(() => queue.dispatch(job, "b", "tree")); }
    else assert.throws(() => queue.dispatch(job, "b", "tree"), { code: "STEP_NOT_READY" });
  }
});
