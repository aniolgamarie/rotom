import { test, assert, evidence } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { FakeClock, barrier, isolatedDirectory } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";

for (const kind of ["canary", "continuation"] as const) for (const result of ["success", "quota", "unknown"] as const)
test(`[S REC-012 T38] ${kind} ${result} arriving after request timeout records facts without restoring automatic control`, async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = kind === "canary";
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const completion = barrier<{ nativeId: string; terminated: boolean; failure: null | { status: number; message: string; stream: "error" } }>();
  const trace: string[] = []; let requestSignal: AbortSignal | undefined;
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), abort() { trace.push("abort"); },
    continue: async (_intent, signal) => { requestSignal = signal; trace.push("continue"); return await completion.promise; },
    canary: async (signal, guard) => { guard(); requestSignal = signal; trace.push("canary"); return await completion.promise; } };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0); t.after(() => { controller.dispose(); store.close(); });
  const quota = { status: 429, message: "temporary limit", stream: "error" as const };
  controller.settled(quota); clock.advance(100); await flush(); const intent = controller.state().intentId!;
  assert.ok(intent); assert.equal(config.recovery.maxWaitMs, null); clock.advance(500); await flush();
  assert.equal(controller.state().reason, "request_timeout_termination_unknown"); assert.equal(requestSignal!.aborted, true);
  assert.equal(store.intent(intent)!.status, "unknown"); assert.ok(store.claims().length > 0);
  completion.resolve({ nativeId: "late-native", terminated: result !== "unknown", failure: result === "quota" ? quota : null }); await flush();
  if (kind === "continuation") { snapshot.leafId = "late-terminal"; snapshot.terminationKnown = result !== "unknown"; controller.settled(result === "quota" ? quota : null); }
  clock.advance(10000); await controller.tick(); await flush();
  for (const id of ["REC-012", "T38"]) evidence(id, () => {
    assert.equal(controller.state().status, "BLOCKED"); assert.equal(trace.filter(item => item === kind || (kind === "continuation" && item === "continue")).length, 1);
    assert.equal(store.intent(intent)!.nativeId, "late-native"); assert.equal(store.intent(intent)!.status, result === "unknown" ? "unknown" : "settled");
    assert.equal(controller.state().canaryReady ?? false, false);
  });
  if (result === "unknown") {
    assert.ok(store.claims().length > 0); assert.throws(() => controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
  } else {
    assert.equal(store.claims().length, 0); assert.equal(controller.state().intentId, null);
    controller.resume(); assert.equal(controller.state().status, "WAITING_QUOTA");
    await controller.tick(); await flush(); assert.equal(trace.filter(item => item === kind || (kind === "continuation" && item === "continue")).length, 2);
  }
});


test("[S REC-012] synchronous abort settlement observes revoked timeout authority and preserves the original quota incident", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured();
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  let controller: RecoveryController, calls = 0, activeInAbort: boolean | undefined;
  controller = new RecoveryController(store, config, { snapshot: () => ({ ...snapshot }), continue: async () => { calls++; return { nativeId: "native" }; },
    abort() {
      activeInAbort = store.owner(controller.state().scopeId)!.active;
      snapshot.leafId = "abort-terminal";
      controller.settled({ message: "Request aborted", code: "RECOVERY_REQUEST_TIMEOUT", controlRevoked: true, stream: "error" });
    } }, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  controller.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(100); await flush();
  const incident = controller.state().incidentId, intent = controller.state().intentId!;
  clock.advance(500); await flush();
  assert.equal(activeInAbort, false); assert.equal(controller.state().status, "BLOCKED"); assert.equal(controller.state().reason, "request_timeout_termination_unknown");
  assert.equal(controller.state().intentId, null); assert.equal(store.intent(intent)!.status, "settled"); assert.equal(store.claims().length, 0);
  assert.equal(controller.state().incidentId, incident); assert.equal(controller.state().history.length, 1); assert.equal(controller.state().attempts, 1);
  clock.advance(10000); await controller.tick(); assert.equal(calls, 1);
});
