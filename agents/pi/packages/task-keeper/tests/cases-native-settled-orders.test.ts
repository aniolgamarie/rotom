import { test, assert, matrixCase } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { FakeClock, barrier, isolatedDirectory } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";

for (const event of ["input", "stop", "switch"] as const) for (const order of ["revoke-first", "await-first"] as const)
test(`[S REC-019] native context settlement ${event} / ${order} cannot revive an old continuation`, async t => matrixCase("await-orders", `R08.${event}.${order}`, async () => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), trace: string[] = [];
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "initial", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const controller = new RecoveryController(store, configured(), { snapshot: () => ({ ...snapshot }), abort() { trace.push("abort"); },
    continue: async () => { trace.push("continue"); return { nativeId: "native" }; } }, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  const quota = { status: 429, message: "quota", stream: "error" as const };
  controller.settled(quota); clock.advance(100); await flush(); const intent = controller.state().intentId!;
  assert.ok(intent); assert.equal(store.intent(intent)!.status, "acked");
  snapshot.idle = false; snapshot.certified = false; snapshot.blockedReasons = ["context_transformation_in_progress"];
  controller.settled(null); assert.equal(controller.state().intentId, intent); assert.ok(store.claims().length > 0);
  const tail = barrier();
  const pending = tail.promise.then(() => {
    trace.push("settled"); snapshot.idle = true; snapshot.certified = true; snapshot.blockedReasons = []; snapshot.leafId = "native-tail-terminal";
    controller.settled(quota);
  });
  const revoke = () => { trace.push("revoke"); if (event === "stop") controller.stop(); else controller.pause(event === "input" ? "user_input" : "session_switch");
    if (event === "switch") snapshot.sessionId = "new-session"; };
  if (order === "revoke-first") { revoke(); tail.resolve(); await pending; }
  else { tail.resolve(); await pending; assert.equal(controller.state().status, "WAITING_QUOTA"); assert.equal(store.intent(intent)!.status, "settled"); revoke(); }
  clock.advance(10000); await controller.tick(); await flush();
  assert.equal(trace.filter(action => action === "continue").length, 1); assert.equal(controller.state().attempts, 1);
  assert.equal(controller.state().sessionId, "session"); assert.ok(controller.state().history.length > 0);
  assert.equal(trace.indexOf("revoke") < trace.indexOf("settled"), order === "revoke-first");
  if (event === "switch" && order === "revoke-first") {
    assert.equal(controller.state().status, "BLOCKED"); assert.equal(controller.state().reason, "session_identity_changed_requires_reconciliation");
    assert.equal(store.intent(intent)!.status, "unknown"); assert.ok(store.claims().length > 0);
  } else {
    assert.equal(controller.state().status, "PAUSED"); assert.equal(store.intent(intent)!.status, "settled"); assert.equal(store.claims().length, 0);
  }
}));
