import { test, assert, matrixCase } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { FakeClock, isolatedDirectory, barrier } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";
for (const change of ["input", "pause", "stop", "dispose", "model", "provider", "session", "leaf", "profile", "certification", "mutator", "queue", "blocker", "quota-cooldown", "transport-cooldown", "deadline"] as const)
  for (const order of ["control-first", "credentials-first"] as const) test(`[S REC-019] native request ${change} / ${order} rechecks ownership after credential resolution`, async t => {
    const store = new Store(isolatedDirectory(t)), config = configured(), clock = new FakeClock(); config.recovery.maxWaitMs = 150;
    const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", model: "fixture-model", provider: "fixture-provider", idle: true,
      pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [], runtimeFingerprint: "runtime" };
    const controller = new RecoveryController(store, config, { snapshot: () => ({ ...snapshot }), continue: async () => ({ nativeId: "native" }), abort() {} }, clock, () => 0);
    t.after(() => { controller.dispose(); store.close(); });
    controller.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(100); await flush();
    const record = controller.state(); assert.equal(record.status, "RUNNING"); assert.ok(record.intentId);
    snapshot.idle = false; // A real provider request runs inside the active native turn.
    const guard = controller.requestGuard(record.intentId!, record.ownerEpoch), credentials = barrier(); let sent = 0;
    const pending = credentials.promise.then(() => { guard(); sent++; });
    const revoke = () => {
      if (change === "input") controller.pause("user_input"); else if (change === "pause") controller.pause(); else if (change === "stop") controller.stop(); else if (change === "dispose") controller.dispose();
      else if (change === "model") snapshot.model = "changed"; else if (change === "provider") snapshot.provider = "changed";
      else if (change === "session") snapshot.sessionId = "changed"; else if (change === "leaf") snapshot.leafId = "changed";
      else if (change === "profile") snapshot.runtimeFingerprint = "changed"; else if (change === "certification") snapshot.certified = false;
      else if (change === "mutator") snapshot.terminationKnown = false; else if (change === "queue") snapshot.pendingMessages = true; else if (change === "blocker") snapshot.blockedReasons = ["external-work"];
      else if (change === "deadline") clock.advance(51);
      else {
        const network = change === "transport-cooldown", key = network ? config.routes.primary.transportDomain : config.routes.primary.quotaGroup;
        store.put(network ? "transport-incidents" : "incidents", key, { id: "shared", status: "OPEN", failures: 1, notBefore: clock.now() + 1000,
          domain: { kind: network ? "transport" : "quota", id: key } });
      }
    };
    if (order === "control-first") {
      const denied = assert.rejects(pending); revoke(); credentials.resolve(); await denied; assert.equal(sent, 0);
    } else {
      credentials.resolve(); await pending; assert.equal(sent, 1); revoke(); assert.throws(guard); assert.equal(sent, 1);
    }
    assert.equal(controller.state().attempts, 1);
    const event = change === "input" ? "input" : change === "stop" ? "stop" : ["model", "provider", "profile"].includes(change) ? "binding-change" : null;
    if (event) matrixCase("await-orders", `R01.${event}.${order === "control-first" ? "revoke-first" : "await-first"}`, () => {
      assert.equal(sent, order === "control-first" ? 0 : 1); assert.throws(guard); assert.equal(controller.state().attempts, 1);
    });
  });

test("[S REC-019] an owned compaction permits only its context-transform blocker and still obeys revocation", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock();
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [], runtimeFingerprint: "runtime" };
  const controller = new RecoveryController(store, configured(), { snapshot: () => ({ ...snapshot }), continue: async () => ({ nativeId: "native" }), abort() {} }, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(100); await flush();
  const state = controller.state(), ordinary = controller.requestGuard(state.intentId!, state.ownerEpoch), compact = controller.requestGuard(state.intentId!, state.ownerEpoch, true);
  assert.doesNotThrow(ordinary); snapshot.certified = false; snapshot.blockedReasons = ["context_transformation_in_progress"];
  assert.throws(ordinary); assert.doesNotThrow(compact);
  const baseline = structuredClone(snapshot);
  for (const change of [{ blockedReasons: [] }, { blockedReasons: ["context_transformation_in_progress", "external-work"] }, { terminationKnown: false },
    { pendingMessages: true }, { sessionId: "different" }, { model: "different" }, { runtimeFingerprint: "changed" }]) {
    Object.assign(snapshot, structuredClone(baseline), change); assert.throws(compact);
  }
  Object.assign(snapshot, baseline); controller.pause(); assert.throws(compact); assert.equal(controller.state().status, "PAUSED");
});
