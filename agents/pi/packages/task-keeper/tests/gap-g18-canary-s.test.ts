import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, FakeClock, barrier } from "./helpers.ts";
const mutations: Record<string, Partial<InteractiveSnapshot>> = {
  model: { model: "new-model" }, provider: { provider: "new-provider" }, leaf: { leafId: "new-leaf" }, session: { sessionId: "new-session" },
  certification: { certified: false }, queue: { pendingMessages: true }, activity: { idle: false }, mutator: { terminationKnown: false },
  profile: { runtimeFingerprint: "new-runtime" }, blockers: { blockedReasons: ["unknown"] },
};
for (const variant of ["valid", "pause", "stop", "shared-cooldown", "deadline", "request-timeout", ...Object.keys(mutations)]) test(`[S REC-019] canary rechecks ${variant} after awaited credentials and before any send`, async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = true; if (variant === "deadline") config.recovery.maxWaitMs = 150;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true, pendingMessages: false, terminationKnown: true,
    certified: true, blockedReasons: [], runtimeFingerprint: "runtime" };
  const gate = barrier(); let sends = 0, continuations = 0;
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => { continuations++; return { nativeId: "continue" }; },
    canary: async (_signal, guard) => { await gate.promise; guard(); sends++; return { nativeId: "canary", terminated: true, failure: null }; } };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "temporary limit", stream: "error" }); clock.advance(100); await flush();
  assert.equal(sends, 0);
  if (variant === "pause") controller.pause(); else if (variant === "stop") controller.stop();
  else if (variant === "shared-cooldown") { const incident = store.get<Record<string, unknown>>("incidents", "pool")!; store.put("incidents", "pool", { ...incident, notBefore: clock.now() + 1000 }); }
  else if (variant === "deadline") clock.advance(60);
  else if (variant === "request-timeout") clock.advance(501);
  else if (variant !== "valid") Object.assign(snapshot, mutations[variant]);
  gate.resolve(); await flush();
  assert.equal(sends, variant === "valid" ? 1 : 0); assert.equal(continuations, 0);
  if (variant === "valid") { assert.equal(controller.state().canaryReady, true); assert.equal(controller.state().status, "WAITING_QUOTA"); }
  else assert.ok(["BLOCKED", "PAUSED"].includes(controller.state().status));
});

test("[S REC-019] a host terminal event cannot settle a still-active canary or authorize its stale callback", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = true;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const gate = barrier(); let sent = 0;
  const adapter: InteractiveAdapter = { snapshot: () => snapshot, abort() {}, continue: async () => ({ nativeId: "unused" }), canary: async (_signal, guard) => {
    await gate.promise; guard(); sent++; return { nativeId: "canary", terminated: true, failure: null };
  } };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0); t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(100); await flush();
  const intent = controller.state().intentId!; assert.equal(store.intent(intent)?.kind, "canary");
  controller.pause("new-user-input"); controller.settled(null); controller.beginUserTurn();
  assert.equal(controller.state().intentId, intent); assert.equal(store.claims().length, 1);
  gate.resolve(); await flush(); assert.equal(sent, 0); assert.notEqual(controller.state().status, "DONE");
});
