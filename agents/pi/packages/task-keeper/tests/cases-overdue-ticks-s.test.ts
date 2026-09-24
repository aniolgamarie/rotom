import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import type { Clock } from "../src/contracts/primitives.ts";
import { barrier, isolatedDirectory } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";

// Deliberately retain callbacks already queued before cancellation; the controller must reject stale work itself.
function pausedHostClock() {
  let wall = 1000000, mono = 0;
  const callbacks: Array<() => void> = [];
  const clock: Clock = { now: () => wall, monotonic: () => mono, schedule: (_delay, callback) => { callbacks.push(callback); return () => {}; } };
  return { clock, callbacks, move: (wallDelta: number, monoDelta = wallDelta) => { wall += wallDelta; mono += monoDelta; } };
}

test("[S REC-009 T25 TK12] many already queued recovery ticks after host suspension cannot burst requests or bypass a new cooldown", async t => {
  const store = new Store(isolatedDirectory(t)), timer = pausedHostClock(), ack = barrier(); let sends = 0;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const controller = new RecoveryController(store, configured(), { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => {
    const ordinal = ++sends; await ack.promise; return { nativeId: `native-${ordinal}` };
  } }, timer.clock, () => 0); t.after(() => { controller.dispose(); store.close(); });
  const quota = { status: 429, message: "quota", stream: "error" as const }; controller.settled(quota);
  for (let n = 0; n < 6; n++) await controller.tick(); const queued = timer.callbacks.slice(); assert.ok(queued.length >= 6); assert.equal(sends, 0);
  timer.move(10000); for (const callback of queued) callback(); await flush();
  const firstIntent = controller.state().intentId!;
  for (const id of ["REC-009", "T25", "TK12"]) evidence(id, () => {
    assert.equal(sends, 1); assert.equal(controller.state().attempts, 1); assert.equal(controller.state().status, "RUNNING");
    assert.equal(store.intent(firstIntent)!.status, "sent"); assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 1);
  });
  ack.resolve(); await flush(); snapshot.leafId = "limited-again"; controller.settled(quota);
  const floor = controller.state().notBefore; assert.ok(floor > timer.clock.now());
  for (const callback of queued) callback(); await flush(); assert.equal(sends, 1);
  timer.move(floor - timer.clock.now() - 1); for (const callback of queued) callback(); await flush(); assert.equal(sends, 1);
  timer.move(1); for (const callback of queued) callback(); await flush();
  for (const id of ["REC-009", "T25", "TK12"]) evidence(id, () => {
    assert.equal(sends, 2); assert.equal(controller.state().attempts, 2); assert.equal(store.intent(firstIntent)!.status, "settled");
    assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 2); assert.equal(controller.state().notBefore, floor);
  });
  controller.settled(null); for (const callback of queued) callback(); await flush(); assert.equal(sends, 2); assert.equal(controller.state().status, "DONE");
  acceptance("AC07","suspend-ticks",{level:"S",observer:"retained-timer-callbacks-and-durable-intents",predicate:"queued ticks cannot replay a sent continuation",artifact:observerArtifact("suspend-ticks",{state:controller.state(),sends,firstIntent})},()=>{assert.equal(sends,2);assert.equal(controller.state().attempts,2);assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n,2);});
});

test("[S TK12] repeated callbacks apply a wall-clock rollback once and preserve the extended durable wait", async t => {
  const store = new Store(isolatedDirectory(t)), timer = pausedHostClock(); let sends = 0;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const controller = new RecoveryController(store, configured(), { snapshot: () => snapshot, abort() {}, continue: async () => { sends++; return { nativeId: "native" }; } }, timer.clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); }); controller.settled({ status: 429, message: "quota", stream: "error" }); const before = controller.state();
  timer.move(-200, 100); for (let n = 0; n < 8; n++) await controller.tick();
  assert.equal(controller.state().notBefore, before.notBefore + 300); assert.equal(sends, 0); assert.equal(controller.state().attempts, 0);
  assert.equal(store.get<{ notBefore: number }>("recovery", before.scopeId)!.notBefore, before.notBefore + 300);
  assert.equal(controller.state().incidentId, before.incidentId); assert.deepEqual(controller.state().history, before.history);
  timer.move(before.notBefore + 300 - timer.clock.now()); await controller.tick(); await flush(); assert.equal(sends, 1);
  acceptance("AC07","wall-rollback",{level:"S",observer:"independent-wall-monotonic-clock-and-SQLite",predicate:"rollback extends the wait exactly once",artifact:observerArtifact("wall-rollback",{before,after:controller.state(),sends})},()=>{assert.equal(sends,1);assert.equal(controller.state().notBefore,before.notBefore+300);assert.equal(controller.state().incidentId,before.incidentId);});
});
