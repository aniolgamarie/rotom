import assert from "node:assert/strict";
import { test } from "node:test";
import { OneShotScheduler } from "../../../runtime/one-shot-schedule.ts";
import { fixture } from "../../../runtime/tests/fixtures.ts";

function setup() {
  const { store } = fixture();
  const context = { now: Date.parse("2026-09-16T00:00:00Z"), user: true, calls: [], fail: false };
  const options = { store, now: () => context.now, authorizeUser: () => context.user,
    dispatcher: { async dispatch(record) {
      assert.equal(Object.values(store.snapshot().schedules)[0].state, "admitted");
      assert.ok(Object.values(store.snapshot().schedules)[0].admitted_at);
      context.calls.push(record);
      if (context.fail) throw Error("synthetic lost acknowledgment");
      return { dispatch_id: "dispatch" };
    } } };
  const request = { task_id: "original-task", budget_scope_id: "original-budget", due_at: "2026-09-16T00:01:00Z",
    deadline: "2026-09-16T01:00:00Z", idempotency_key: "once" };
  return { context, options, request, scheduler: new OneShotScheduler(options) };
}

test("admission persists before dispatch; repeated ticks cannot trigger twice", async () => {
  const f = setup();
  await f.scheduler.schedule(f.request);
  f.context.now += 60000;
  await Promise.all([f.scheduler.tick(), f.scheduler.tick()]);
  assert.equal(f.context.calls.length, 1);
  assert.equal(f.context.calls[0].budget_scope_id, "original-budget");
});

test("restart misses pause and user resume retains original task budget", async () => {
  const f = setup();
  const scheduled = await f.scheduler.schedule(f.request);
  f.scheduler.close();
  f.context.now += 120000;
  await f.scheduler.tick();
  assert.equal(f.context.calls.length, 0);
  const resumed = new OneShotScheduler(f.options);
  await resumed.tick();
  assert.equal(Object.values(f.options.store.snapshot().schedules)[0].state, "paused-missed");
  await resumed.update(scheduled.schedule_id, "resume", "2026-09-16T00:03:00Z");
  f.context.now += 60000;
  await resumed.tick();
  assert.equal(f.context.calls[0].task_id, "original-task");
  assert.equal(f.context.calls[0].budget_scope_id, "original-budget");
});

test("unknown dispatch is never retried and model control cannot schedule", async () => {
  const f = setup();
  f.context.user = false;
  await assert.rejects(f.scheduler.schedule(f.request), /USER_CONTROL_REQUIRED/);
  f.context.user = true;
  await f.scheduler.schedule(f.request);
  f.context.fail = true;
  f.context.now += 60000;
  const first = await f.scheduler.tick();
  assert.equal(first[0].dispatch_status, "start_unknown");
  await f.scheduler.tick();
  assert.equal(f.context.calls.length, 1);
});
