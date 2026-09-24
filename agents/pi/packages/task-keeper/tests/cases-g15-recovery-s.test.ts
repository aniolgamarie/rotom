import type { TestContext } from "node:test";
import { readFileSync } from "node:fs";
import { setImmediate as flush } from "node:timers/promises";
import { test, assert, evidence } from "./recorded-test.ts";
import { configured } from "./fixtures/config.ts";
import type { Config, Rule } from "../src/config.ts";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { terminalError } from "../src/reliability/classifier.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";

const samples = JSON.parse(readFileSync(new URL("./fixtures/qwen-service-errors.json", import.meta.url), "utf8")) as {
  cases: Array<{ id: string; status: number; body: unknown; rules: Rule[]; expected: string }>;
};
function fixture(t: TestContext, config: Config) {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock();
  const route = config.routes.primary;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "original-task-after-write", provider: route.provider, model: route.model,
    idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const calls: Array<{ sessionId: string; leafId: string }> = [];
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => {
    calls.push({ sessionId: snapshot.sessionId, leafId: snapshot.leafId }); return { nativeId: `continued-${calls.length}` };
  } };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  return { store, clock, snapshot, calls, controller, adapter };
}

test("[S REC-001 TK09] a long-task checkpoint survives quota recovery without replaying the completed tool transition", async t => {
  const f = fixture(t, configured());
  // Explicit state simulation: completed tool effects and retained native context are inputs,
  // not a claim that this fake adapter proves real filesystem or service behavior.
  const context = ["original user task " + "long-context ".repeat(8192), "tool-call:write", "tool-result:written"];
  const workspace = new Map([["candidate", "changed once"]]);
  let writeTransitions = 1;
  const checkpoint = structuredClone({ context, workspace: [...workspace], writeTransitions });
  const actions: Array<{ type: string; id: string; leaf: string }> = [];
  f.adapter.continue = async intent => {
    actions.push({ type: "continue", id: intent.id, leaf: intent.leafId });
    context.push("assistant:original task completed");
    return { nativeId: "continued-original" };
  };
  f.controller.settled({ status: 429, message: "after completed write", headers: { "retry-after": "1" }, stream: "error" });
  const waiting = f.controller.state();
  f.clock.advance(999); await flush();
  for (const id of ["REC-001", "TK09"]) evidence(id, () => {
    assert.equal(actions.length, 0); assert.equal(waiting.status, "WAITING_QUOTA");
    assert.deepEqual({ context, workspace: [...workspace], writeTransitions }, checkpoint);
    assert.equal(waiting.sessionId, "session"); assert.equal(waiting.leafId, "original-task-after-write");
  });
  f.clock.advance(1); await flush();
  const running = f.controller.state(); f.snapshot.leafId = "completed-original"; f.controller.settled(null);
  f.clock.advance(100000); await f.controller.tick();
  for (const id of ["REC-001", "TK09"]) evidence(id, () => {
    assert.deepEqual(actions, [{ type: "continue", id: running.intentId, leaf: "original-task-after-write" }]);
    assert.deepEqual(context.slice(0, -1), checkpoint.context); assert.equal(context.length, 4);
    assert.deepEqual([...workspace], checkpoint.workspace); assert.equal(writeTransitions, 1);
    assert.equal(f.controller.state().status, "DONE"); assert.equal(f.controller.state().attempts, 1);
    assert.equal(f.controller.state().incidentId, waiting.incidentId); assert.equal(f.controller.state().history.length, 1);
    assert.equal(f.store.intent(running.intentId!)!.nativeId, "continued-original");
    assert.equal(f.store.intent(running.intentId!)!.status, "settled"); assert.equal(f.store.claims().length, 0);
  });
});

test("[S REC-002 TK10] service bindings and renamed models use the same recovery transitions", async t => {
  for (const sampleId of ["service-a-resource", "service-b-resource"]) for (const model of ["qwen-symbolic", "renamed-symbolic"]) {
    const sample = samples.cases.find(item => item.id === sampleId)!;
    const config = configured(); config.routes.primary.provider = `${sampleId}-provider`; config.routes.primary.model = model;
    config.routes.primary.accountBinding = `provider:${config.routes.primary.provider}`; config.quotaGroups.pool.rules = sample.rules;
    const f = fixture(t, config);
    f.controller.settled(terminalError(`${sample.status} ${JSON.stringify(sample.body)}`, { status: sample.status, headers: { "retry-after": "1" } }));
    const before = f.controller.state(); f.clock.advance(999); await flush();
    for (const id of ["REC-002", "TK10"]) evidence(id, () => {
      assert.equal(before.status, "WAITING_QUOTA"); assert.equal(before.reason, "resource_pressure"); assert.equal(before.notBefore, 1001000);
      assert.equal(before.history[0].evidence!.categorySource, "binding-rule"); assert.equal(f.calls.length, 0);
    });
    f.clock.advance(1); await flush();
    for (const id of ["REC-002", "TK10"]) evidence(id, () => {
      assert.deepEqual(f.calls, [{ sessionId: "session", leafId: "original-task-after-write" }]);
      assert.equal(f.controller.state().status, "RUNNING"); assert.equal(f.controller.state().incidentId, before.incidentId);
    });
    f.snapshot.leafId = "continued-complete"; f.controller.settled(null);
    for (const id of ["REC-002", "TK10"]) evidence(id, () => {
      assert.equal(f.controller.state().status, "DONE"); assert.equal(f.controller.state().history.length, 1);
      assert.equal(f.store.claims().length, 0); assert.equal(f.clock.pending, 0);
    });
  }
});

test("[S REC-003 T20] observed usage-pressure binding waits and recovers without inventing a monthly reset", async t => {
  const observed = JSON.parse(readFileSync(new URL("./fixtures/qwen-observed-error.json", import.meta.url), "utf8"));
  const config = configured(); config.quotaGroups.pool.rules = observed.rules;
  const missing = fixture(t, config); missing.controller.settled(terminalError(observed.terminalError, null));
  assert.equal(missing.controller.state().reason, "http_response_observation_missing"); assert.equal(missing.calls.length, 0);
  // State-layer input models a matching HTTP observation; the historical sample itself has none.
  const f = fixture(t, config); f.controller.settled(terminalError(observed.terminalError, { status: 429, headers: {} }));
  const first = f.controller.state(); f.clock.advance(100); await flush();
  for (const id of ["REC-003", "T20"]) evidence(id, () => {
    assert.equal(first.status, "WAITING_QUOTA"); assert.equal(first.reason, "resource_pressure"); assert.equal(first.notBefore, 1000100);
    assert.equal(first.history[0].retryAt, null); assert.equal(first.history[0].evidence!.resetAt, null); assert.equal(first.history[0].evidence!.ruleIndex, 0);
    assert.equal(f.calls.length, 1); assert.equal(f.controller.state().status, "RUNNING");
  });
  f.snapshot.leafId = "completed"; f.controller.settled(null);
  for (const id of ["REC-003", "T20"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "DONE"); assert.equal(f.controller.state().history[0].code, "throttling"); assert.equal(f.store.claims().length, 0);
  });
});

test("[S REC-004 T26] auth billing policy context and unknown failures cannot enter quota forever or switch routes", async t => {
  const variants = [
    { status: 401, body: { error: { code: "auth" } }, category: "auth_billing_policy" },
    { status: 402, body: { error: { code: "billing" } }, category: "auth_billing_policy" },
    { status: 403, body: { error: { code: "policy" } }, category: "auth_billing_policy" },
    { status: 429, body: { error: { code: "PolicyDenied" } }, category: "auth_billing_policy" },
    { status: 400, body: { error: { code: "ContextExceeded" } }, category: "context_contract" },
    { status: 200, body: { error: { code: "UnknownFailure" } }, category: "other" },
  ];
  for (const variant of variants) {
    const config = configured(); config.quotaGroups.pool.rules = [
      { code: "PolicyDenied", category: "auth_billing_policy" }, { code: "ContextExceeded", category: "context_contract" },
    ];
    const f = fixture(t, config);
    f.controller.settled(terminalError(`${variant.status} ${JSON.stringify(variant.body)}`, { status: variant.status, headers: {} }));
    f.clock.advance(1000000); await f.controller.tick();
    for (const id of ["REC-004", "T26"]) evidence(id, () => {
      const state = f.controller.state(); assert.equal(state.status, "BLOCKED"); assert.equal(state.reason, variant.category);
      assert.equal(state.routeId, "primary"); assert.equal(state.intentId, null); assert.equal(state.attempts, 0);
      assert.equal(f.calls.length, 0); assert.equal(f.clock.pending, 0); assert.equal(f.store.list("incidents").length, 0);
      assert.throws(() => f.controller.resume(), { code: "NO_RECOVERABLE_INCIDENT" });
    });
  }
});

test("[S REC-015 REC-016 T22] successful canary permits only a candidate and a long-request failure keeps the original incident", async t => {
  const config = configured(); config.recovery.lightCanaryEnabled = true;
  const f = fixture(t, config); let probes = 0;
  f.adapter.canary = async (...args) => {
    assert.equal(args.length, 2); assert.ok(args[0] instanceof AbortSignal); assert.equal(typeof args[1], "function");
    args[1](); probes++; return { nativeId: `canary-${probes}`, terminated: true, failure: null };
  };
  f.controller.settled({ status: 429, message: "long-context request limited", stream: "error" });
  const original = f.controller.state().incidentId;
  f.clock.advance(100); await flush();
  evidence("REC-016", () => {
    assert.equal(probes, 1); assert.equal(f.controller.state().canaryAttempts, 1); assert.equal(f.controller.state().attempts, 0);
    assert.equal(f.controller.state().reason, "canary_passed_real_request_pending"); assert.equal(f.calls.length, 0);
  });
  f.clock.advance(1); await flush(); assert.equal(f.calls.length, 1);
  f.snapshot.leafId = "long-request-still-limited";
  f.controller.settled({ status: 429, message: "same long-context request remains limited", headers: { "retry-after": "2" }, stream: "error" });
  const afterFailure = f.controller.state();
  for (const id of ["REC-015", "T22"]) evidence(id, () => {
    assert.equal(afterFailure.status, "WAITING_QUOTA"); assert.equal(afterFailure.incidentId, original); assert.equal(afterFailure.canaryReady, false);
    assert.equal(afterFailure.attempts, 1); assert.equal(afterFailure.canaryAttempts, 1); assert.equal(afterFailure.history.length, 2);
    assert.equal(afterFailure.notBefore, 1002101); assert.equal(f.store.list("incidents").length, 1);
    assert.equal(f.store.get<{status:string;failures:number}>("incidents", "pool")!.status, "OPEN");
    assert.equal(f.store.get<{status:string;failures:number}>("incidents", "pool")!.failures, 2);
  });
  f.clock.advance(1999); await flush(); assert.equal(probes, 1); assert.equal(f.calls.length, 1);
  f.clock.advance(1); await flush(); assert.equal(probes, 2); assert.equal(f.calls.length, 1);
  f.clock.advance(1); await flush(); assert.equal(f.calls.length, 2);
  f.snapshot.leafId = "long-request-complete"; f.controller.settled(null);
  for (const id of ["REC-015", "REC-016", "T22"]) evidence(id, () => {
    assert.equal(f.controller.state().status, "DONE"); assert.equal(f.controller.state().incidentId, original);
    assert.equal(f.controller.state().attempts, 2); assert.equal(f.controller.state().canaryAttempts, 2); assert.equal(f.clock.pending, 0);
  });
});
