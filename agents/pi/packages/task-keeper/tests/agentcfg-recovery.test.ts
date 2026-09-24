import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { TaskSchedules } from "../src/orchestration/scheduler.ts";
import { reconcileManagedStep, taskState } from "../src/orchestration/recovery.ts";

const setup = () => {
  const store = new Store(mkdtempSync(join(tmpdir(), "tk-recovery-"))), owner = store.claimOwner("scope", "owner");
  return { store, owner, schedules: new TaskSchedules(store, owner) };
};
test("one-shot admission is atomic with workspace intent and never repeated after acknowledgment loss", () => {
  const f = setup();
  try {
    f.schedules.create("task", 100, 1000);
    assert.throws(() => f.store.transaction(() => { f.schedules.admit("task", 110); throw Error("fault before commit"); }));
    assert.equal(f.schedules.read("task").state, "scheduled");
    f.store.transaction(() => f.schedules.admit("task", 110));
    assert.equal(new TaskSchedules(f.store, f.owner).recover("task", 120).state, "admitted");
    assert.throws(() => f.schedules.admit("task", 120), /SCHEDULE_START_NOT_ELIGIBLE/);
    assert.throws(() => f.schedules.resume("task", 130, 120), /SCHEDULE_RESUME_INVALID/);
    f.schedules.executed("task", "workspace-intent");
    assert.equal(f.schedules.read("task").dispatch_id, "workspace-intent");
  } finally { f.store.close(); }
});
test("missed schedules pause; explicit resume retains task and budget; canceled and expired cannot start", () => {
  const f = setup();
  try {
    const original = f.schedules.create("task", 100, 1000);
    assert.equal(f.schedules.recover("task", 200).state, "paused-missed");
    f.schedules.resume("task", 300, 200);
    const admitted = f.schedules.admit("task", 300);
    assert.equal(admitted.task_id, original.task_id); assert.equal(admitted.budget_scope_id, original.budget_scope_id);
    f.schedules.create("canceled", 400, 1000); f.schedules.pause("canceled", true);
    assert.throws(() => f.schedules.admit("canceled", 500), /SCHEDULE_START_NOT_ELIGIBLE/);
    f.schedules.create("expired", 400, 500);
    assert.equal(f.schedules.recover("expired", 600).state, "expired");
    assert.throws(() => f.schedules.admit("expired", 600), /SCHEDULE_START_NOT_ELIGIBLE/);
  } finally { f.store.close(); }
});
test("step recovery requires verified physical reclamation and cannot turn unknown into stopped", async () => {
  const f = setup();
  try {
    f.store.put("agentcfg-attempts-v1", "attempt", { attempt_id: "attempt", task_id: "task", step_id: "step", state: "start_unknown", lease_id: null });
    f.store.put("agentcfg-descriptors-v1", "attempt", { allocation_id: "allocation" });
    let observation = { protected: true, termination_evidence: null };
    const supervisor = { async call(method, args) { assert.equal(method, "reconcile"); assert.equal(args.lease_id, "allocation"); return observation; } };
    assert.equal((await reconcileManagedStep(f.store, f.owner, supervisor, "task", "step")).stopped, false);
    assert.equal(f.store.has("agentcfg-attempt-termination-v1", "attempt"), false);
    observation = { protected: false, termination_evidence: { verified: true, kind: "never-started", evidence_digest: "a".repeat(64) } };
    assert.deepEqual(await reconcileManagedStep(f.store, f.owner, supervisor, "task", "step"), { stopped: true, neverStarted: true });
    assert.equal(f.store.get("agentcfg-attempts-v1", "attempt").lease_id, "allocation");
    assert.equal(taskState("BLOCKED"), "blocked"); assert.throws(() => taskState("UNKNOWN"), /UNKNOWN_TASK_STATE/);
  } finally { f.store.close(); }
});
