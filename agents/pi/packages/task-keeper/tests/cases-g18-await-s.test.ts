import { test, assert, matrixCase } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { FakeClock, barrier, isolatedDirectory } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";

for (const event of ["input", "pause", "stop", "shutdown"] as const) for (const order of ["revoke-first", "await-first"] as const)
test(`[S REC-019] canary completion ${event} / ${order} cannot append a stale continuation`, async t => matrixCase("await-orders", `R03.${event}.${order}`, async () => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = true;
  const trace: string[] = [], completion = barrier<{ nativeId: string; terminated: boolean; failure: null }>();
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), abort() { trace.push("abort"); },
    continue: async () => { trace.push("continue"); return { nativeId: "unexpected" }; },
    canary: async (_signal, guard) => { guard(); trace.push("canary-sent"); const result = await completion.promise; trace.push("canary-returned"); return result; } };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0); t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "limit", stream: "error" }); clock.advance(100); await flush();
  const intent = controller.state().intentId!; assert.ok(intent); assert.deepEqual(trace, ["canary-sent"]);
  const revoke = () => { trace.push("revoke"); if (event === "stop") controller.stop(); else if (event === "shutdown") controller.dispose(); else controller.pause(event === "input" ? "user_input" : "user_pause"); };
  if (order === "revoke-first") { revoke(); completion.resolve({ nativeId: "native-canary", terminated: true, failure: null }); await flush(); }
  else { completion.resolve({ nativeId: "native-canary", terminated: true, failure: null }); await flush(); assert.equal(controller.state().reason, "canary_passed_real_request_pending"); revoke(); }
  clock.advance(10000); await controller.tick(); await flush();
  assert.equal(trace.includes("continue"), false); assert.equal(trace.filter(action => action === "canary-sent").length, 1);
  assert.equal(controller.state().status, "PAUSED"); assert.equal(controller.state().attempts, 0); assert.equal(controller.state().canaryAttempts, 1);
  assert.equal(trace.indexOf("revoke") < trace.indexOf("canary-returned"), order === "revoke-first");
  if (event === "shutdown" && order === "revoke-first") {
    assert.equal(store.intent(intent)!.status, "sent"); assert.ok(store.claims().length > 0); assert.equal(controller.state().intentId, intent);
  } else {
    assert.equal(store.intent(intent)!.status, "settled"); assert.equal(store.claims().length, 0); assert.equal(controller.state().intentId, null);
  }
}));

for (const event of ["input", "stop", "fork", "switch"] as const) for (const order of ["revoke-first", "await-first"] as const)
test(`[S REC-019] continuation acknowledgement ${event} / ${order} records facts without renewing authority`, async t => matrixCase("await-orders", `R07.${event}.${order}`, async () => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), trace: string[] = [], ack = barrier<{ nativeId: string }>();
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const controller = new RecoveryController(store, configured(), { snapshot: () => ({ ...snapshot }), abort() { trace.push("abort"); },
    continue: async () => { trace.push("continuation-sent"); const result = await ack.promise; trace.push("ack-returned"); return result; } }, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "limit", stream: "error" }); clock.advance(100); await flush();
  const intent = controller.state().intentId!, epoch = controller.state().ownerEpoch; assert.ok(intent);
  const revoke = () => {
    trace.push("revoke");
    if (event === "stop") controller.stop();
    else { controller.pause(event === "input" ? "user_input" : `session_${event}`); if (event !== "input") snapshot.sessionId = `new-${event}`; }
  };
  if (order === "revoke-first") { revoke(); ack.resolve({ nativeId: "native-continuation" }); await flush(); }
  else { ack.resolve({ nativeId: "native-continuation" }); await flush(); assert.equal(store.intent(intent)!.status, "acked"); revoke(); }
  clock.advance(10000); await controller.tick(); await flush();
  assert.equal(trace.filter(action => action === "continuation-sent").length, 1); assert.equal(controller.state().attempts, 1);
  assert.equal(controller.state().status, "PAUSED"); assert.equal(controller.state().ownerEpoch, epoch);
  assert.equal(store.intent(intent)!.nativeId, "native-continuation"); assert.equal(store.intent(intent)!.status, "acked");
  assert.ok(store.claims().length > 0); assert.equal(controller.state().intentId, intent);
  assert.throws(() => controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
  assert.equal(trace.indexOf("revoke") < trace.indexOf("ack-returned"), order === "revoke-first");
}));
