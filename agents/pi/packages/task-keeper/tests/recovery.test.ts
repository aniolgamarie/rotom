import type { TestContext } from "node:test";
import { test, assert, evidence } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { Store } from "../src/store/database.ts";
import { FakeClock, isolatedDirectory, barrier } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";
import type { FailureSignal } from "../src/reliability/classifier.ts";

const limited: FailureSignal = { status: 429, message: "frequency", stream: "error" };
function setup(t: TestContext, sessionId = "session-1", root?: string) {
  const store = new Store(root ?? isolatedDirectory(t)), clock = new FakeClock();
  const snapshot: InteractiveSnapshot = { sessionId, leafId: "leaf-1", provider: "fixture-provider", model: "fixture-model",
    idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const actions: string[] = [];
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }),
    continue: async (intent) => { actions.push(intent.id); return { nativeId: `native-${actions.length}` }; },
    abort: () => { actions.push("abort"); } };
  const controller = new RecoveryController(store, configured(), adapter, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  return { store, clock, snapshot, actions, adapter, controller };
}

test("[S REC-006 T18] native retry success and non-settled events do not send an outer continuation", async (t) => {
  const f = setup(t); f.snapshot.idle = false;
  f.controller.settled(limited); f.clock.advance(1000); await flush(); assert.equal(f.actions.length, 0);
  f.snapshot.idle = true; f.controller.settled(null); f.clock.advance(1000); await flush();
  for (const id of ["REC-006", "T18"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "DONE"); assert.equal(f.actions.length, 0);
    assert.equal(f.controller.state().attempts, 0); assert.equal(f.controller.state().intentId, null);
    assert.equal(f.clock.pending, 0);
  });
});

test("[S CFG-012] pausing and reattaching a completed recovery cannot reopen it", (t) => {
  for (const id of ["CFG-012"]) evidence(id, () => {
    const f = setup(t); f.controller.settled(null); assert.equal(f.controller.state().status, "DONE");
    f.controller.pause(); assert.equal(f.controller.state().status, "DONE"); assert.throws(() => f.controller.resume());
    f.controller.dispose();
    const next = new RecoveryController(f.store, configured(), f.adapter, f.clock);
    assert.equal(next.state().status, "DONE"); assert.throws(() => next.resume()); next.dispose();
  });
});

test("[S REC-007 T19] settled continuation releases its intent before queued user work takes control", async (t) => {
  const f = setup(t); f.controller.settled(limited); f.clock.advance(100); await flush();
  assert.equal(f.actions.length, 1); assert.ok(f.controller.state().intentId);
  f.snapshot.leafId = "settled-with-queue"; f.snapshot.pendingMessages = true; f.controller.settled(null);
  assert.equal(f.controller.state().intentId, null); assert.equal(f.store.claims().length, 0);
  for (const id of ["REC-007", "T19"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "PAUSED"); assert.equal(f.controller.state().reason, "pending_messages");
    assert.equal(f.controller.state().intentId, null); assert.equal(f.store.claims().length, 0); assert.equal(f.actions.length, 1);
  });
  f.snapshot.pendingMessages = false; f.controller.beginUserTurn();
  assert.equal(f.controller.state().status, "IDLE"); f.clock.advance(1000); await flush(); assert.equal(f.actions.length, 1);
});

test("[S CFG-007] a genuine new user turn can bind a changed policy without deleting history", (t) => {
  for (const id of ["CFG-007"]) evidence(id, () => {
    const f = setup(t); f.controller.settled(limited); f.controller.dispose();
    const config = configured(); config.recovery.requestTimeoutMs++;
    const next = new RecoveryController(f.store, config, f.adapter, f.clock);
    assert.throws(() => next.resume());
    next.beginUserTurn(); next.settled(null);
    assert.equal(next.state().status, "DONE"); assert.equal(next.state().history.length, 1);
    assert.equal(f.store.list("policy-authorizations").length, 1); next.dispose();
  });
});

test("[S REC-011 T51] configured overall wait deadline bounds an otherwise forever quota wait", async (t) => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured();
  config.recovery.maxWaitMs = 50;
  let sends = 0;
  const adapter: InteractiveAdapter = { snapshot: () => ({ sessionId: "deadline", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] }), continue: async () => { sends++; return { nativeId: "unexpected" }; }, abort() {} };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  controller.settled(limited); clock.advance(49); await flush(); assert.equal(sends, 0);
  clock.advance(1); await flush(); assert.equal(controller.state().reason, "recovery_deadline_exhausted"); assert.equal(sends, 0);
  const deadline = controller.state().deadlineAt; controller.pause(); controller.resume(); clock.advance(1); await flush();
  for (const id of ["REC-011", "T51"]) evidence(id, () => {
    assert.equal(controller.state().deadlineAt, deadline); assert.equal(deadline, 1000050);
    assert.equal(sends, 0); assert.equal(controller.state().reason, "recovery_deadline_exhausted"); assert.equal(controller.state().attempts, 0);
  });
});

test("[S REC-008 REC-010 T21] no request before exact notBefore and duplicate settled cannot refresh cooldown", async (t) => {
  const f = setup(t); f.controller.settled({ ...limited, headers: { "Retry-After": "1" } });
  const at = f.controller.state().notBefore;
  f.controller.settled(limited); assert.equal(f.controller.state().notBefore, at);
  f.clock.advance(999); await flush(); const before = f.actions.length;
  f.clock.advance(1); await flush();
  for (const id of ["REC-008", "REC-010", "T21"]) evidence(id, () => {
    assert.equal(before, 0); assert.equal(f.actions.length, 1); assert.equal(f.controller.state().status, "RUNNING");
    assert.equal(f.controller.state().notBefore, at); assert.equal(at, 1001000);
  });
  f.snapshot.leafId = "leaf-2"; f.controller.settled(null);
  f.clock.advance(10000); await flush(); assert.equal(f.actions.length, 1); assert.equal(f.clock.pending, 0);
});

test("[S REC-017 REC-018 T23] repeated long-request failures preserve incident, then full success settles", async (t) => {
  const f = setup(t); f.controller.settled(limited); const incident = f.controller.state().incidentId;
  f.clock.advance(100); await flush(); assert.equal(f.actions.length, 1);
  f.snapshot.leafId = "leaf-2";
  f.controller.settled({ status: 200, code: "ResourcePressure", message: "long input still limited", stream: "error" });
  for (const id of ["REC-017", "REC-018", "T23"]) evidence(id, () => {
    assert.equal(f.controller.state().incidentId, incident); assert.equal(f.controller.state().status, "WAITING_QUOTA");
    assert.equal(f.controller.state().history.at(-1)!.category, "resource_pressure"); assert.equal(f.actions.length, 1);
  });
  f.clock.advance(100); await flush(); assert.equal(f.actions.length, 2);
  f.snapshot.leafId = "leaf-3"; f.controller.settled(null);
  for (const id of ["REC-017", "REC-018", "T23"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "DONE"); assert.equal(f.controller.state().history.length, 2);
    assert.equal(f.store.claims().length, 0); assert.equal(f.actions.length, 2);
  });
});

test("[S T38] user pause and lifecycle disposal invalidate expired callbacks", async (t) => {
  for (const id of ["T38"]) await evidence(id, async () => {
    const f = setup(t); f.controller.settled(limited); f.controller.pause("user_input");
    f.clock.advance(1000); await flush(); assert.equal(f.actions.length, 0); assert.equal(f.controller.state().status, "PAUSED");
    f.controller.resume(); await f.controller.tick(); assert.equal(f.actions.length, 1);
    f.controller.stop(); f.snapshot.leafId = "leaf-2"; f.controller.settled(null);
    f.clock.advance(10000); await flush(); assert.equal(f.actions.filter((a) => a !== "abort").length, 1);
    assert.equal(f.controller.state().status, "PAUSED");
  });
});

test("[S REC-021 CFG-013 T40] missing acknowledgement stays unknown and resume cannot repeat the send", async (t) => {
  const f = setup(t);
  f.adapter.continue = async (intent) => { f.actions.push(intent.id); throw new Error("ack transport lost"); };
  f.controller.settled(limited); f.clock.advance(100); await flush();
  assert.equal(f.controller.state().status, "BLOCKED"); assert.equal(f.store.claims().length, 1);
  assert.throws(() => f.controller.resume());
  f.clock.advance(10000); await flush();
  for (const id of ["REC-021", "CFG-013", "T40"]) evidence(id, () => {
    assert.equal(f.actions.filter(action => action !== "abort").length, 1); assert.equal(f.controller.state().status, "BLOCKED");
    assert.equal(f.store.intent(f.controller.state().intentId!)!.status, "unknown"); assert.equal(f.store.claims().length, 1);
    assert.throws(() => f.controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
  });
});

test("[S REC-019] a valid terminal fact arriving before ack does not regress the completed state", async (t) => {
  const f = setup(t), ack = barrier<{ nativeId: string }>();
  f.adapter.continue = (intent) => { f.actions.push(intent.id); return ack.promise; };
  f.controller.settled(limited); f.clock.advance(100); await flush();
  f.snapshot.leafId = "leaf-2"; f.controller.settled(null);
  ack.resolve({ nativeId: "native-1" }); await flush();
  for (const id of ["REC-019"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "DONE");
    assert.equal(f.store.intent(f.actions[0])!.nativeId, "native-1");
    assert.equal(f.store.intent(f.actions[0])!.status, "settled");
  });
});

test("[S REC-004 RTB-007 T26 T33] permanent failures and uncertified/protected paths do not silently retry", async (t) => {
  const f = setup(t); f.controller.settled({ status: 401, message: "denied", stream: "error" });
  assert.throws(() => f.controller.resume()); f.clock.advance(10000); await flush(); assert.equal(f.actions.length, 0);
  const g = setup(t, "session-2"); g.snapshot.certified = false; g.controller.settled(limited);
  assert.equal(g.controller.state().reason, "adapter_not_certified"); assert.equal(g.clock.pending, 0);
  for (const id of ["REC-004", "RTB-007", "T26", "T33"]) evidence(id, () => {
    assert.equal(f.actions.length, 0);
    assert.equal(g.controller.state().reason, "adapter_not_certified");
  });
});

test("[S REC-022 TK13] independent quota waiters do not share cancellation authority", async (t) => {
  for (const id of ["REC-022", "TK13"]) await evidence(id, async () => {
    const root = isolatedDirectory(t), a = setup(t, "session-a", root), b = setup(t, "session-b", root);
    a.controller.settled(limited); b.controller.settled(limited); a.controller.pause();
    b.clock.advance(100); await flush(); assert.equal(b.actions.length, 1); assert.equal(a.actions.length, 0);
  });
});

test("[S VAL-016] every independent pre-dispatch condition denies while an unchanged valid state dispatches once", async (t) => {
  for (const id of ["VAL-016"]) await evidence(id, async () => {
    const variants = [
      { leafId: "different-leaf" }, { model: "changed-model" }, { provider: "changed-provider" },
      { idle: false }, { pendingMessages: true }, { terminationKnown: false }, { blockedReasons: ["external-work"] }, { certified: false },
    ];
    for (let i = 0; i < variants.length; i++) {
      const f = setup(t, `session-${i}`); f.controller.settled(limited); Object.assign(f.snapshot, variants[i]);
      f.clock.advance(100); await flush(); assert.equal(f.actions.length, 0, JSON.stringify(variants[i]));
      assert.equal(f.controller.state().status, "BLOCKED");
      assert.equal(f.controller.state().attempts, 0); assert.equal(f.controller.state().intentId, null);
      assert.equal(f.store.claims().length, 0);
      assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
    }
    const legal = setup(t, "legal-control"); legal.controller.settled(limited);
    legal.clock.advance(99); await flush(); assert.equal(legal.actions.length, 0);
    legal.clock.advance(1); await flush();
    assert.equal(legal.actions.length, 1); assert.equal(legal.controller.state().status, "RUNNING");
    assert.equal(legal.controller.state().attempts, 1); assert.equal(legal.store.claims().length, 1);
    await legal.controller.tick(); assert.equal(legal.actions.length, 1);
  });
});

test("[S REC-013 T24] ten waiters get one shared permit and advance one at a time", async t => {
  const root = isolatedDirectory(t), waiters = Array.from({length: 10}, (_, i) => setup(t, `session-${i}`, root));
  for (const waiter of waiters) waiter.controller.settled(limited);
  for (const waiter of waiters) waiter.clock.advance(10000); await flush();
  for (const id of ["REC-013", "T24"]) evidence(id, () => {
    assert.equal(waiters.reduce((sum, waiter) => sum + waiter.actions.length, 0), 1);
    assert.equal(waiters[0].store.claims().length, 1); assert.equal(waiters[0].controller.state().status, "RUNNING");
    assert.ok(waiters.slice(1).every(waiter => waiter.actions.length === 0));
  });
  waiters[0].snapshot.leafId = "finished"; waiters[0].controller.settled(null);
  for (const waiter of waiters.slice(1)) waiter.clock.advance(100); await flush();
  for (const id of ["REC-013", "T24"]) evidence(id, () => {
    assert.equal(waiters.reduce((sum, waiter) => sum + waiter.actions.length, 0), 2);
    assert.equal(waiters[1].actions.length, 1); assert.equal(waiters[1].store.claims().length, 1);
    assert.ok(waiters.slice(2).every(waiter => waiter.actions.length === 0));
  });
});

test("[S REC-014] removing every waiter stops probing and explicit resume restarts one waiter", async t => {
  const root = isolatedDirectory(t), a = setup(t, "session-a", root), b = setup(t, "session-b", root);
  a.controller.settled(limited); b.controller.settled(limited); a.controller.pause(); b.controller.pause();
  a.clock.advance(10000); b.clock.advance(10000); await a.controller.tick(); await b.controller.tick(); await flush();
  assert.equal(a.actions.length + b.actions.length, 0); assert.equal(a.clock.pending + b.clock.pending, 0); assert.equal(a.store.claims().length, 0);
  a.controller.resume(); await a.controller.tick(); await flush();
  for (const id of ["REC-014"]) evidence(id, () => {
    assert.equal(a.actions.length, 1); assert.equal(b.actions.length, 0); assert.equal(b.controller.state().status, "PAUSED");
  });
});

test("[S REC-009 T25 TK12] wall rollback extends waiting and never bursts missed timers", async (t) => {
  for (const id of ["T25", "TK12"]) await evidence(id, async () => {
    const f = setup(t); f.controller.settled(limited);
    f.clock.wall -= 1000; f.clock.advance(100); await flush(); assert.equal(f.actions.length, 0);
    f.clock.advance(2000); await flush(); assert.equal(f.actions.length, 1);
  });
});

test("[S REC-012 T51] finite request timeout aborts, keeps unknown reservation and rejects resume", async (t) => {
  const f = setup(t), ack = barrier<{ nativeId: string }>();
  f.adapter.continue = (intent) => { f.actions.push(intent.id); return ack.promise; };
  f.controller.settled(limited); f.clock.advance(100); await flush();
  f.clock.advance(500); await flush();
  assert.equal(f.controller.state().status, "BLOCKED"); assert.ok(f.actions.includes("abort"));
  assert.equal(f.store.claims().length, 1); assert.throws(() => f.controller.resume());
  ack.resolve({ nativeId: "late-ack" }); await flush();
  for (const id of ["REC-012", "T51"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "BLOCKED"); assert.equal(f.actions.filter(action => action !== "abort").length, 1);
    assert.equal(f.controller.state().reason, "request_timeout_termination_unknown"); assert.equal(f.store.claims().length, 1);
    assert.equal(f.store.intent(f.controller.state().intentId!)!.nativeId, "late-ack");
    assert.throws(() => f.controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
  });
});

test("[S REC-005] network failures exhaust their separate finite policy", async (t) => {
  const f = setup(t);
  const outage: FailureSignal = { status: 503, message: "overloaded", stream: "error" };
  f.controller.settled(outage); f.clock.advance(100); await flush();
  f.snapshot.leafId = "leaf-2"; f.controller.settled(outage); f.clock.advance(100); await flush();
  f.snapshot.leafId = "leaf-3"; f.controller.settled(outage);
  assert.equal(f.controller.state().reason, "network_attempts_exhausted");
  assert.throws(() => f.controller.resume()); f.clock.advance(10000); await flush();
  assert.equal(f.actions.length, 2);
  for (const id of ["REC-005"]) evidence(id, () => {
    assert.equal(f.controller.state().reason, "network_attempts_exhausted");
    assert.equal(f.actions.length, 2);
  });
});

test("[S REC-009] restored wait retains history and deadline instead of silently restarting", async (t) => {
  const f = setup(t); f.controller.settled(limited);
  const before = f.controller.state(); f.controller.dispose();
  const restored = new RecoveryController(f.store, configured(), f.adapter, f.clock, () => 0);
  try {
    assert.equal(restored.state().status, "PAUSED");
    assert.equal(restored.state().notBefore, before.notBefore); assert.deepEqual(restored.state().history, before.history);
    for (const id of ["REC-009"]) evidence(id, () => {
      assert.equal(restored.state().status, "PAUSED");
      assert.equal(restored.state().notBefore, before.notBefore);
      assert.deepEqual(restored.state().history, before.history);
    });
    f.clock.advance(99); await flush(); assert.equal(f.actions.length, 0);
    restored.resume(); f.clock.advance(1); await flush(); assert.equal(f.actions.length, 1);
  } finally { restored.dispose(); }
});

test("[S REC-020 T37] another session's idle snapshot cannot settle the old execution", async t => {
  const f = setup(t); f.controller.settled(limited); f.clock.advance(100); await flush();
  const intent = f.controller.state().intentId!; assert.ok(intent); f.snapshot.sessionId = "replacement-session";
  f.controller.settled(null);
  for (const id of ["REC-020", "T37"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "BLOCKED"); assert.equal(f.controller.state().intentId, intent);
    assert.equal(f.store.intent(intent)!.status, "unknown"); assert.equal(f.store.claims().length, 1);
    assert.throws(() => f.controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
  });
  f.clock.advance(10000); await flush(); assert.equal(f.actions.filter(action => action !== "abort").length, 1);
});

test("[S REC-019] a late canary fact cannot overwrite a replacement recovery owner's state", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = true;
  const completed = barrier<{nativeId:string;terminated:boolean;failure:null}>(); let firstNotifications = 0, continuations = 0;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), abort() {}, canary: () => completed.promise,
    continue: async () => { continuations++; return { nativeId: "unexpected" }; } };
  const first = new RecoveryController(store, config, adapter, clock, () => 0, () => { firstNotifications++; });
  let second: RecoveryController | undefined;
  t.after(() => { first.dispose(); second?.dispose(); store.close(); });
  first.settled(limited); clock.advance(100); await flush(); const intent = first.state().intentId!; assert.ok(intent);
  const old = store.owner(first.scopeId)!; store.revokeOwner(old);
  second = new RecoveryController(store, config, adapter, clock, () => 0);
  const before = second.state(), notifications = firstNotifications;
  completed.resolve({ nativeId: "late-canary", terminated: true, failure: null }); await flush();
  for (const id of ["REC-019"]) evidence(id, () => {
    assert.deepEqual(store.get("recovery", first.scopeId), before); assert.deepEqual(second.state(), before);
    assert.equal(firstNotifications, notifications); assert.equal(store.intent(intent)!.status, "settled"); assert.equal(store.intent(intent)!.nativeId, "late-canary");
    assert.equal(store.list("late-recovery-records").length, 1); assert.equal(continuations, 0);
  });
});

test("[S REC-019] a controller's own revocation persists pause before any successor takes over", async t => {
  const f = setup(t); f.controller.settled(limited); f.controller.pause("user_pause");
  assert.equal(f.store.owner(f.controller.scopeId)!.active, false);
  assert.equal(f.store.get<{status:string}>("recovery", f.controller.scopeId)!.status, "PAUSED");
  assert.deepEqual(f.store.get("recovery", f.controller.scopeId), f.controller.state()); assert.equal(f.store.list("late-recovery-records").length, 0);
  f.controller.resume(); f.clock.advance(100); await flush();
  for (const id of ["REC-019"]) evidence(id, () => {
    assert.equal(f.actions.length, 1); assert.equal(f.store.get<{status:string}>("recovery", f.controller.scopeId)!.status, "RUNNING");
  });
});


test("[S T33] a missing actual HTTP observer prevents recovery admission without consuming an attempt", async t => {
  const missing = setup(t, "missing-gate"); missing.snapshot.certified = false; missing.snapshot.blockedReasons = ["http_observer_not_active"];
  missing.controller.settled(limited); missing.clock.advance(100000); await missing.controller.tick(); await flush();
  assert.equal(missing.controller.state().status, "BLOCKED"); assert.equal(missing.controller.state().reason, "adapter_not_certified");
  assert.equal(missing.controller.state().attempts, 0); assert.equal(missing.controller.state().intentId, null); assert.equal(missing.actions.length, 0);
  assert.equal(missing.store.claims().length, 0); assert.equal(missing.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
  assert.throws(() => missing.controller.resume());
  const certified = setup(t, "with-gate"); certified.controller.settled(limited); certified.clock.advance(100); await flush();
  assert.equal(certified.controller.state().status, "RUNNING"); assert.equal(certified.controller.state().attempts, 1); assert.equal(certified.actions.length, 1);
  for (const id of ["T33"]) evidence(id, () => {
    assert.equal(missing.controller.state().status, "BLOCKED"); assert.equal(missing.actions.length, 0);
    assert.equal(certified.controller.state().status, "RUNNING"); assert.equal(certified.controller.state().attempts, 1);
  });
});
