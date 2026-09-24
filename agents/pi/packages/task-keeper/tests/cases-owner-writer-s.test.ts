import { test, assert, evidence } from "./recorded-test.ts";
import { writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { Scheduler, type PlanStep } from "../src/orchestration/scheduler.ts";
import { workspaceResource } from "../src/workspace/worktree.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S EXE-010 T41] owner replacement cannot release an unconfirmed writer or undo its observed effects", t => {
  const root = isolatedDirectory(t), store = new Store(join(root, "state")), path = join(root, "candidate.txt"); t.after(() => store.close());
  const old = store.claimOwner("scope", "old"), resources = [{ id: workspaceResource(root), capacity: 1, units: 1 }];
  store.prepare(old, "original", "write", { workspace: root }, resources); store.markSent(old, "original"); store.acknowledge("original", "native-writer");
  // Declared external writer effects: authorization revocation does not physically stop an existing process.
  writeFileSync(path, "first effect\n"); store.settle("original", "unknown"); store.revokeOwner(old); const current = store.claimOwner("scope", "current");
  writeFileSync(path, "late original effect\n");
  const dispatch = () => { store.prepare(current, "replacement", "write", { workspace: root }, resources); writeFileSync(path, "replacement effect\n"); };
  for (const id of ["EXE-010", "T41"]) evidence(id, () => {
    assert.throws(dispatch, { code: "RESOURCE_DENIED" }); assert.equal(store.intent("replacement"), null);
    assert.equal(store.intent("original")!.nativeId, "native-writer"); assert.equal(store.intent("original")!.status, "unknown");
    assert.equal(store.claims().length, 1); assert.equal(store.claims()[0].intent_id, "original"); assert.equal(readFileSync(path, "utf8"), "late original effect\n");
    assert.throws(() => store.markSent(old, "original"), { code: "CONTROL_REVOKED" });
  });
  store.settle("original", "terminated"); dispatch();
  for (const id of ["EXE-010", "T41"]) evidence(id, () => {
    assert.equal(store.intent("original")!.status, "settled"); assert.equal(store.intent("replacement")!.status, "prepared");
    assert.equal(store.claims().length, 1); assert.equal(store.claims()[0].intent_id, "replacement"); assert.equal(readFileSync(path, "utf8"), "replacement effect\n");
  });
});

test("[S EXE-011] cancellation with unknown termination preserves the claim and cannot reopen the cancelled job after reconciliation", t => {
  const store = new Store(isolatedDirectory(t)), owner = store.claimOwner("scope", "owner"), queue = new Scheduler(store, owner); t.after(() => store.close());
  const spec = (id: string) => ({ id, workScope: "scope", version: 1, objective: "bounded write", workflow: "fix" as const, required: ["tests"], optional: [],
    allowPartial: false, policyDigest: "policy", snapshot: "tree", maxSteps: 8, maxSemanticAttempts: 3 });
  const step: PlanStep = { id: "write", kind: "write", role: "worker", optional: false, dependencies: [], allowedSkippedDependencies: [], resources: [{ id: "source", capacity: 1, units: 1 }] };
  queue.submit(spec("a"), [step], 0, 0); queue.submit(spec("b"), [step], 0, 0); const intent = queue.dispatch("a", "write", "tree"); store.markSent(owner, intent.id);
  queue.cancel("a"); queue.finish("a", "write", { terminated: false, passed: false, artifactId: null }, 1);
  assert.equal(queue.job("a").cancelled, true); assert.equal(queue.job("a").steps[0].status, "unknown"); assert.equal(store.claims().length, 1);
  assert.throws(() => queue.resume("a"), { code: "CANCELLED_JOB" }); assert.throws(() => queue.dispatch("b", "write", "tree"), { code: "RESOURCE_DENIED" });
  queue.reconcileStopped("a", "write", false);
  assert.equal(queue.job("a").cancelled, true); assert.equal(queue.job("a").steps[0].status, "failed"); assert.equal(store.claims().length, 0);
  assert.throws(() => queue.resume("a"), { code: "CANCELLED_JOB" }); assert.equal(queue.next(2)!.jobId, "b");
  assert.equal(queue.dispatch("b", "write", "tree").status, "prepared"); assert.equal(queue.job("a").dispatched, 1);
});
