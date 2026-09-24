import { test, assert } from "./recorded-test.ts";
import { StatusPublisher, recoveryStatusText, jobStatusText } from "../src/evidence/status.ts";
import { FakeClock } from "./helpers.ts";

test("[U CFG-014] status distinguishes an earliest retry from admission and an unresolved execution", () => {
  const record = { status: "WAITING_QUOTA", reason: "frequency_limit", notBefore: 2000, attempts: 3, intentId: null, deadlineAt: 3000 };
  assert.ok(recoveryStatusText(record, 1001).includes("wait >=1s")); assert.ok(recoveryStatusText(record, 2000).includes("awaiting admission"));
  assert.ok(recoveryStatusText(record, 1001).includes("deadline 2s"));
  assert.ok(recoveryStatusText({ ...record, status: "BLOCKED", reason: "termination_unknown", intentId: "unknown" }, 1001).includes("execution unreconciled"));
  const waiting = jobStatusText({ id: "job", status: "WAITING_QUOTA", reason: "quota", snapshot: "tree", routeNotBefore: 100000, stageDeadline: 2000 }, 1000);
  assert.ok(waiting.includes("route >=99s")); assert.ok(waiting.includes("stage 1s"));
  assert.ok(jobStatusText({ id: "job", status: "COMPLETED", reason: "", snapshot: "tree-identity" }, 1).includes("@identity"));
});

test("[S CFG-014] repeated updates are coalesced, countdowns refresh, critical changes arrive immediately and disposal clears timers", () => {
  const clock = new FakeClock(), output: Array<{at:number;value:string|undefined}> = [];
  const publisher = new StatusPublisher((_key, value) => output.push({ at: clock.monotonic(), value }), clock);
  const waiting = { status: "WAITING_QUOTA", reason: "frequency_limit", notBefore: clock.now() + 5000, attempts: 1, intentId: null };
  publisher.publish("recovery", "waiting", now => recoveryStatusText(waiting, now), true);
  for (let i = 0; i < 100; i++) { clock.advance(5); publisher.publish("recovery", "waiting", now => recoveryStatusText(waiting, now), true); }
  assert.equal(output.length, 1); clock.advance(500); assert.equal(output.length, 2); assert.ok(output[1].value!.includes("wait >=4s"));
  clock.advance(10); publisher.publish("recovery", "blocked", () => "BLOCKED · termination_unknown");
  assert.equal(output.length, 3); assert.equal(output[2].at, 1010); assert.equal(clock.pending, 0);
  clock.advance(10000); assert.equal(output.length, 3); publisher.dispose(); assert.equal(output.at(-1)!.value, undefined);
  publisher.publish("recovery", "late", () => "RUNNING", true); clock.advance(10000); assert.equal(output.length, 4); assert.equal(clock.pending, 0);
});

test("[S CFG-014] an unavailable optional UI is retried without interrupting the state publisher", () => {
  const clock = new FakeClock(); let offline = true, attempts = 0;
  const publisher = new StatusPublisher(() => { attempts++; if (offline) throw new Error("no UI"); }, clock);
  assert.doesNotThrow(() => publisher.publish("recovery", "waiting", () => "WAITING"));
  for (let i = 0; i < 100; i++) publisher.publish("recovery", "waiting", () => "WAITING");
  assert.equal(attempts, 1); offline = false; clock.advance(1000); assert.equal(attempts, 2); assert.equal(clock.pending, 0);
  publisher.dispose();
});

test("[S CFG-014] fractional production-style monotonic time always schedules integer delays", () => {
  const clock = new FakeClock(), original = clock.schedule.bind(clock), delays: number[] = [];
  clock.monotonic = () => clock.mono += 0.125;
  clock.schedule = (delay, callback) => { assert.ok(Number.isSafeInteger(delay)); delays.push(delay); return original(delay, callback); };
  const publisher = new StatusPublisher(() => {}, clock);
  assert.doesNotThrow(() => publisher.publish("wait", "one", () => "WAITING", true));
  assert.deepEqual(delays, [1000]); assert.equal(clock.pending, 1); publisher.dispose(); assert.equal(clock.pending, 0);
});
