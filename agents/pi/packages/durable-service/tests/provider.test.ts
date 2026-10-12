import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableModelDispatch } from "../src/provider.ts";
import { createModelAttemptStore } from "../src/model-attempts.ts";
import { createDurableCallIdentityBridge } from "../src/call-identity.ts";
import { databaseFixture } from "./model-attempt-database.ts";
import { factory, rawStream, deferred, PublicEventStream } from "./provider-events.ts";

const secret = "SYNTHETIC_PRIVATE auth SQL request exception";
const tick = () => new Promise(resolve => setImmediate(resolve));
const terminalMessage = extra => ({ role: "assistant", content: [{ type: "text", text: "business content" }], api: "fixture-api", provider: "fictional", model: "model",
  usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 3, cost: { input: 0.1, output: 0.2, cacheRead: 0, cacheWrite: 0, total: 0.3 } }, stopReason: "stop", timestamp: 1, ...extra });
function fixedError(expected = "dispatch-unknown") { return error => { assert.equal(error.message, expected); assert.equal(error.code, expected); assert.equal(error.cause, undefined); assert(!String(error.stack).includes(secret)); return true; }; }
async function collect(stream) { const events = []; for await (const event of stream) events.push(event); return { events, result: await stream.result() }; }
async function fixture(t, hooks = {}) {
  const db = databaseFixture(); t.after(() => db.cleanup());
  const store = await createModelAttemptStore({ database: db.database, deploymentIdentity: "a".repeat(64), mode: "create" })();
  const bridge = createDurableCallIdentityBridge(), calls = [], state = { authorizations: 0, collectors: 0, attemptId: "attempt-4", takes: 0 };
  const model = { provider: "fictional", id: "model", api: "fixture-api", name: "private descriptor", headers: { authorization: secret }, maxTokens: 100 };
  const actual = terminalMessage();
  class Models {
    streamSimple(givenModel, context, options) {
      calls.push("streamSimple"); assert.equal(this, original);
      assert.equal(options.signal instanceof AbortSignal, true);
      if (hooks.stream) return hooks.stream(givenModel, context, options);
      return rawStream([{ type: "start", partial: actual }, { type: "text_delta", contentIndex: 0, delta: "business", partial: actual }, { type: "done", reason: "stop", message: actual }], actual);
    }
    async completeSimple(givenModel, context, options) {
      calls.push("completeSimple"); assert.equal(this, original);
      if (hooks.complete) return hooks.complete(givenModel, context, options);
      // 原receiver里的原streamSimple不是wrapper，不会再次gate/take。
      const inner = this.streamSimple(givenModel, context, options); for await (const _ of inner) {} return inner.result();
    }
    stream() { assert.fail("unsupported original stream"); }
    complete() { assert.fail("unsupported original complete"); }
    fetchDeferred() { assert.fail("unsupported fetch"); }
    cancelDeferred() { assert.fail("unsupported cancel"); }
  }
  const original = new Models();
  const observedBridge = { take(signal, operation) { state.takes++; return bridge.take(signal, operation); }, check(...args) { return bridge.check(...args); } };
  const observedStore = {
    async prepare(input) { if (hooks.beforePrepare) await hooks.beforePrepare(input); return store.prepare(input); },
    async commitSending(id) { if (hooks.commit) return hooks.commit(id, store, db); return store.commitSending(id); },
    async recordResult(id, result) { if (hooks.record) await hooks.record(id, result); return store.recordResult(id, result); },
    async settle(id, settlement) { if (hooks.settle) await hooks.settle(id, settlement); return store.settle(id, settlement); },
  };
  const cfg = { models: original, ai: factory, bridge: observedBridge, store: observedStore, model,
    limits: { timeoutMs: 1000, maxEvents: 20 },
    async authorize(snapshot, signal) {
      state.authorizations++; assert(Object.isFrozen(snapshot)); assert(Object.isFrozen(snapshot.context)); assert(!Object.hasOwn(snapshot.options, "signal")); assert(signal instanceof AbortSignal);
      if (hooks.authorize) return hooks.authorize(snapshot, signal, state.authorizations);
      return { attemptId: state.attemptId, taskId: "task-" + snapshot.identity.nativeTaskId, phase: snapshot.identity.call_kind,
        nativeTaskId: snapshot.identity.nativeTaskId, nativeConversationId: snapshot.identity.nativeConversationId,
        registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "model" },
        budget: { scopeId: "scope-" + snapshot.identity.nativeTaskId, maxCalls: 5, maxCostUnits: 100, reservationUnits: 20 } };
    },
    async resultFacts(snapshot, message, signal) {
      state.collectors++; assert(Object.isFrozen(snapshot)); assert(signal instanceof AbortSignal);
      if (hooks.facts) return hooks.facts(snapshot, message, signal);
      return { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } },
        settlement: { usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 5 } };
    },
  };
  function scope(kind = "generation", taskId = 4) {
    const controller = new AbortController(), signal = controller.signal;
    const api = { taskId, conversationId: 9 }, context = { get abortSignal() { return signal; } };
    if (kind === "generation") bridge.generationHooks.beforeRequest(undefined, api, context);
    else bridge.compactionHooks.beforeCompact(undefined, api, context);
    return { controller, signal, api, context, options: { signal, maxTokens: 50, maxRetries: 0, transport: "sse" }, prompt: { messages: [{ role: "user", content: "private request" }] } };
  }
  return { db, store, bridge, original, model, actual, cfg, calls, state, scope, create: () => createDurableModelDispatch(cfg) };
}

test("sync public outer stream, three identical checks, real SQLite send/result ordering and private fixed lookup copy", async t => {
  const f = await fixture(t), scope = f.scope(), wrapper = f.create();
  assert(Object.isFrozen(wrapper)); assert(Object.isFrozen(wrapper.models));
  const copy = wrapper.models.getModel("fictional", "model"); assert.equal(JSON.stringify(copy), JSON.stringify(f.model)); assert.notEqual(copy, f.model);
  assert.equal(wrapper.models.getModel("other", "model"), undefined); assert.equal(wrapper.models.refresh, undefined);
  const before = JSON.stringify([f.model, scope.prompt, scope.options]);
  const stream = wrapper.models.streamSimple(f.model, scope.prompt, scope.options); assert(stream instanceof PublicEventStream); assert.equal(stream.then, undefined); assert.deepEqual(f.calls, []);
  const observed = await collect(stream); assert.deepEqual(observed.events.map(value => value.type), ["start", "text_delta", "done"]);
  assert.equal(observed.result, f.actual); assert.equal(f.state.authorizations, 3); assert.equal(f.state.takes, 1); assert.deepEqual(f.calls, ["streamSimple"]);
  const row = await f.store.observe("attempt-4"); assert.equal(row.state, "settled"); assert.equal(row.settlement.estimatedCostUnits, 5);
  assert.equal(JSON.stringify([f.model, scope.prompt, scope.options]), before); assert.equal(Object.isFrozen(f.model), false); assert.equal(Object.isFrozen(f.actual), false);
});
test("completeSimple binds original receiver and internally original stream does not double-gate", async t => {
  const f = await fixture(t), scope = f.scope("compaction"), wrapper = f.create();
  const value = wrapper.models.completeSimple(f.model, scope.prompt, scope.options); assert(value instanceof Promise);
  assert.equal(await value, f.actual); assert.deepEqual(f.calls, ["completeSimple", "streamSimple"]); assert.equal(f.state.takes, 1); assert.equal(f.state.authorizations, 3);
  assert.equal((await f.store.observe("attempt-4")).input.phase, "compaction");
});
for (const operation of ["stream", "streamDeferred", "complete", "fetchDeferred", "cancelDeferred"]) test(`${operation} is explicit unsupported without original Models, ledger or bridge entry`, async t => {
  const f = await fixture(t), wrapper = f.create();
  if (operation.startsWith("stream")) assert.equal((await collect(wrapper.models[operation]())).result.errorMessage, "unsupported");
  else await assert.rejects(wrapper.models[operation](), fixedError("unsupported"));
  assert.deepEqual(f.calls, []); assert.equal(f.state.takes, 0); assert.equal(f.state.authorizations, 0);
});
test("result terminal is withheld while trusted facts/record/settlement persist, despite public terminal push immediate result", async t => {
  const recorded = deferred(), settled = deferred(); const f = await fixture(t, { record: () => recorded.promise, settle: () => settled.promise });
  const scope = f.scope(), stream = f.create().models.streamSimple(f.model, scope.prompt, scope.options);
  let published = false; stream.result().then(() => { published = true; }); const collecting = collect(stream);
  await tick(); assert.equal(published, false); assert.equal((await f.store.observe("attempt-4")).state, "sending");
  recorded.resolve(); await tick(); assert.equal(published, false); assert.equal((await f.store.observe("attempt-4")).state, "result-recorded");
  settled.resolve(); const observed = await collecting; assert.equal(observed.result, f.actual); assert.equal((await f.store.observe("attempt-4")).state, "settled");
});
test("SDK errorMessage is filtered only at explicit positions; business text/tool args and originals retained", async t => {
  const original = terminalMessage({ errorMessage: secret, stopReason: "error", content: [{ type: "text", text: secret }, { type: "toolCall", id: "t", name: "tool", arguments: { text: secret } }] });
  const f = await fixture(t, { stream: () => rawStream([{ type: "start", partial: original }, { type: "error", reason: "error", error: original }], original) });
  const scope = f.scope(), output = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(output.result.errorMessage, "dispatch-unknown"); assert.equal(output.events[0].partial.errorMessage, "dispatch-unknown");
  assert.equal(output.result.content, original.content); assert.equal(output.result.content[0].text, secret); assert.equal(original.errorMessage, secret); assert.equal(Object.isFrozen(original), false);
});
test("null settlement preserves full reservation; SDK synthetic zero usage never becomes billing fact", async t => {
  const actual = terminalMessage({ usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { total: 0 } } });
  const f = await fixture(t, { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual), facts: () => ({ result: { resultRef: "e".repeat(64), outcome: "failed", observedRoute: { provider: "fictional", model: "model" } }, settlement: null }) });
  const scope = f.scope(); assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result, actual);
  const snapshot = await f.store.snapshot("task-4"); assert.equal(snapshot.reservedCostUnits, "20"); assert.equal(snapshot.settledCostUnits, "0"); assert.equal(snapshot.attempts[0].state, "result-recorded");
});
test("same request with fresh hook repeats committed fact and never sends again; compaction without new hook fails", async t => {
  const f = await fixture(t), wrapper = f.create(), first = f.scope("compaction");
  await wrapper.models.completeSimple(f.model, first.prompt, first.options);
  await assert.rejects(wrapper.models.completeSimple(f.model, first.prompt, first.options), fixedError());
  f.bridge.compactionHooks.beforeCompact(undefined, first.api, first.context);
  await assert.rejects(wrapper.models.completeSimple(f.model, first.prompt, first.options), fixedError());
  assert.deepEqual(f.calls, ["completeSimple", "streamSimple"]); assert.equal((await f.store.observe("attempt-4")).state, "settled");
});
for (const round of [2, 3]) test(`authorization metadata drift on check${round} preserves reservation, zero Models entry`, async t => {
  const f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { const value = await original(...args); if (f.state.authorizations === round) value.policyIdentity = "f".repeat(64); return value; };
  const scope = f.scope(), observed = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(observed.result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []);
  assert.equal((await f.store.observe("attempt-4")).state, round === 2 ? "prepared" : "sending"); assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
for (const round of [1, 2, 3]) test(`current authorization rejects round${round} without entry or inferred release`, async t => {
  const f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { if (f.state.authorizations + 1 === round) { f.state.authorizations++; throw new Error(secret); } return original(...args); };
  const scope = f.scope(), observed = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(observed.result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []);
  if (round > 1) assert.equal((await f.store.observe("attempt-4")).state, round === 2 ? "prepared" : "sending");
});
for (const field of ["nativeTaskId", "nativeConversationId", "phase", "route", "budget", "unknown"]) test(`authorize closed identity ${field} cannot register/send forged binding`, async t => {
  const f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { const value = await original(...args);
    if (field === "nativeTaskId") value.nativeTaskId = 5;
    if (field === "nativeConversationId") value.nativeConversationId = 10;
    if (field === "phase") value.phase = "compaction";
    if (field === "route") value.route.model = "different";
    if (field === "budget") value.budget.reservationUnits = true;
    if (field === "unknown") value.approved = true;
    return value;
  };
  const scope = f.scope(); assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []);
});
for (const lifecycle of ["timeout", "close", "abort", "bridge-close", "fatal-hook", "new-hook"]) test(`pending first-authorize ${lifecycle} never reaches original entry`, async t => {
  const gate = deferred(), f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { const value = await original(...args); if (f.state.authorizations === 1) await gate.promise; return value; };
  if (lifecycle === "timeout") f.cfg.limits.timeoutMs = 10;
  const scope = f.scope(), wrapper = f.create(), collecting = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick();
  if (lifecycle === "timeout") await new Promise(resolve => setTimeout(resolve, 20));
  if (lifecycle === "close") wrapper.close();
  if (lifecycle === "abort") scope.controller.abort(secret);
  if (lifecycle === "bridge-close") f.bridge.close();
  if (lifecycle === "fatal-hook") { try { f.bridge.generationHooks.beforeRequest(undefined, {}, {}); } catch {} }
  if (lifecycle === "new-hook") f.bridge.generationHooks.beforeRequest(undefined, scope.api, scope.context);
  gate.resolve(); const output = await collecting; assert.equal(output.result.errorMessage, "dispatch-unknown"); await tick(); assert.deepEqual(f.calls, []);
});
for (const lifecycle of ["bridge-close", "fatal-hook", "new-hook"]) test(`pending second-authorize ${lifecycle} preserves prepared reservation but denies send`, async t => {
  const gate = deferred(), f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { const value = await original(...args); if (f.state.authorizations === 2) await gate.promise; return value; };
  const scope = f.scope(), wrapper = f.create(), collecting = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "prepared");
  if (lifecycle === "bridge-close") f.bridge.close();
  if (lifecycle === "fatal-hook") { try { f.bridge.generationHooks.beforeRequest(undefined, {}, {}); } catch {} }
  if (lifecycle === "new-hook") f.bridge.generationHooks.beforeRequest(undefined, scope.api, scope.context);
  gate.resolve(); assert.equal((await collecting).result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []); assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
for (const lifecycle of ["close", "abort", "bridge-close", "new-hook"]) test(`pending committed ack ${lifecycle} leaves sending unknown with zero entry`, async t => {
  const gate = deferred(), f = await fixture(t, { commit: async (id, store) => { const value = await store.commitSending(id); await gate.promise; return value; } });
  const scope = f.scope(), wrapper = f.create(), collecting = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "sending");
  if (lifecycle === "close") wrapper.close(); if (lifecycle === "abort") scope.controller.abort(); if (lifecycle === "bridge-close") f.bridge.close();
  if (lifecycle === "new-hook") f.bridge.generationHooks.beforeRequest(undefined, scope.api, scope.context);
  gate.resolve(); assert.equal((await collecting).result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []); assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
test("real SQL commit lost acknowledgement retires facade and never dispatches", async t => {
  const f = await fixture(t, { commit: async (id, store, db) => { db.faults.lostAck = new Error(secret); try { return await store.commitSending(id); } finally { delete db.faults.lostAck; } } });
  const scope = f.scope(), wrapper = f.create(); assert.equal((await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown");
  assert.deepEqual(f.calls, []); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
  const recovered = await createModelAttemptStore({ database: f.db.database, deploymentIdentity: "a".repeat(64), mode: "active" })(); assert.equal((await recovered.observe("attempt-4")).state, "sending");
});
for (const fault of ["model", "request", "methods", "authorize", "store"]) test(`live ${fault} drift retires wrapper and other pending outputs`, async t => {
  const gate = deferred(), f = await fixture(t), original = f.cfg.authorize;
  f.cfg.authorize = async (...args) => { const value = await original(...args); await gate.promise; return value; };
  const first = f.scope(), second = f.scope("generation", 5), wrapper = f.create();
  const one = collect(wrapper.models.streamSimple(f.model, first.prompt, first.options)), two = collect(wrapper.models.streamSimple(f.model, second.prompt, second.options)); await tick();
  if (fault === "model") f.model.headers.authorization = "changed";
  if (fault === "request") first.prompt.messages[0].content = "changed";
  if (fault === "methods") f.original.streamSimple = () => assert.fail("replacement");
  if (fault === "authorize") f.cfg.authorize = () => assert.fail("replacement");
  if (fault === "store") f.cfg.store.prepare = () => assert.fail("replacement");
  gate.resolve(); assert.equal((await one).result.errorMessage, "dispatch-unknown"); assert.equal((await two).result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []);
});
for (const protocol of ["no-terminal", "double-terminal", "after-terminal", "result-mismatch", "deferred", "throw", "result-reject"]) test(`stream ${protocol} stays sending unknown and does not invent result/zero settlement`, async t => {
  const actual = terminalMessage(); let events = [{ type: "done", reason: "stop", message: actual }], returned = actual, options = {};
  if (protocol === "no-terminal") events = [{ type: "start", partial: actual }];
  if (protocol === "double-terminal") events.push(events[0]);
  if (protocol === "after-terminal") events.push({ type: "start", partial: actual });
  if (protocol === "result-mismatch") returned = terminalMessage();
  if (protocol === "deferred") { actual.stopReason = "deferred"; actual.deferred = { id: "background" }; }
  if (protocol === "throw") options.throwAfter = new Error(secret);
  if (protocol === "result-reject") options.resultReject = new Error(secret);
  const f = await fixture(t, { stream: () => rawStream(events, returned, options) }); const scope = f.scope();
  assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown");
  assert.equal(f.state.collectors, 0); assert.equal((await f.store.observe("attempt-4")).state, "sending"); assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
for (const mode of ["close", "timeout"]) test(`late real terminal after ${mode} records old facts but never reopens output`, async t => {
  const gate = deferred(), actual = terminalMessage(); const f = await fixture(t, { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual, { gate }) });
  if (mode === "timeout") f.cfg.limits.timeoutMs = 15;
  const scope = f.scope(), wrapper = f.create(), stream = wrapper.models.streamSimple(f.model, scope.prompt, scope.options); await tick();
  assert.deepEqual(f.calls, ["streamSimple"]); if (mode === "close") wrapper.close(); else await new Promise(resolve => setTimeout(resolve, 25));
  const output = await collect(stream); assert.equal(output.result.errorMessage, "dispatch-unknown"); gate.resolve(); await tick(); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "settled"); assert.equal(await stream.result(), output.result); assert.equal(f.db.counters.dbCloses, 0); assert.equal(scope.signal.aborted, false);
});
test("late complete actual message may settle after close without invoking wrapper stream a second time", async t => {
  const gate = deferred(), actual = terminalMessage(), f = await fixture(t, { complete: () => gate.promise });
  const scope = f.scope("compaction"), wrapper = f.create(), answer = wrapper.models.completeSimple(f.model, scope.prompt, scope.options); await tick(); wrapper.close();
  await assert.rejects(answer, fixedError()); gate.resolve(actual); await tick(); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "settled"); assert.deepEqual(f.calls, ["completeSimple"]);
});
for (const field of ["apiKey", "headers", "fetch", "onPayload", "onResponse", "transformHeaders", "samplingParams", "deferred", "unknown"]) test(`unqualified option ${field} blocks before authorize/ledger/entry`, async t => {
  const f = await fixture(t), scope = f.scope(); scope.options[field] = field === "deferred" ? false : secret;
  assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown"); assert.equal(f.state.authorizations, 0); assert.deepEqual(f.calls, []);
});
for (const [field, value] of [["maxTokens", 0], ["maxRetries", undefined], ["maxRetries", 1], ["transport", "auto"], ["reasoning", "off"], ["temperature", Infinity], ["timeoutMs", 0], ["maxRetryDelayMs", -1], ["sessionId", "bad\n"], ["cacheRetention", "all"]]) test(`option native shape ${field}/${String(value)} rejects`, async t => {
  const f = await fixture(t), scope = f.scope(); scope.options[field] = value;
  assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown"); assert.deepEqual(f.calls, []);
});
for (const shape of ["cycle", "getter", "proxy", "function", "date", "oversize", "signal-fake", "signal-proxy"]) test(`pure request ${shape} cannot reach gate or original models`, async t => {
  const f = await fixture(t), scope = f.scope(); let reads = 0;
  if (shape === "cycle") scope.prompt.self = scope.prompt;
  if (shape === "getter") Object.defineProperty(scope.prompt, "messages", { enumerable: true, get() { reads++; throw new Error(secret); } });
  if (shape === "proxy") scope.prompt = new Proxy(scope.prompt, {});
  if (shape === "function") scope.prompt.function = () => {};
  if (shape === "date") scope.prompt.timestamp = new Date();
  if (shape === "oversize") scope.prompt.messages[0].content = "x".repeat(8 * 1024 * 1024);
  if (shape === "signal-fake") scope.options.signal = { aborted: false };
  if (shape === "signal-proxy") scope.options.signal = new Proxy(scope.signal, {});
  assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown"); assert.equal(reads, 0); assert.equal(f.state.authorizations, 0); assert.deepEqual(f.calls, []);
});
for (const [field, value] of [["timeoutMs", 0], ["timeoutMs", 120001], ["maxEvents", 0], ["maxEvents", 65537], ["maxEvents", true]]) test(`invalid finite limits ${field}/${value} rejects construction`, async t => {
  const f = await fixture(t); f.cfg.limits[field] = value; assert.throws(f.create, fixedError("input-invalid"));
});
test("maxEvents bounds published queue and preserves sending unknown without collector", async t => {
  const actual = terminalMessage(); const f = await fixture(t, { stream: () => rawStream([{ type: "start", partial: actual }, { type: "text_delta", delta: "x", partial: actual }, { type: "done", reason: "stop", message: actual }], actual) });
  f.cfg.limits.maxEvents = 1; const scope = f.scope(), output = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.deepEqual(output.events.map(event => event.type), ["start", "error"]); assert.equal(f.state.collectors, 0); assert.equal((await f.store.observe("attempt-4")).state, "sending");
});
test("raw rejection code accessor is never executed and background late rejection is handled", async t => {
  let reads = 0; const hostile = new Error(secret); Object.defineProperty(hostile, "code", { get() { reads++; throw new Error(secret); } });
  const gate = deferred(), f = await fixture(t, { authorize: () => gate.promise }); f.cfg.limits.timeoutMs = 10;
  const scope = f.scope(), stream = f.create().models.streamSimple(f.model, scope.prompt, scope.options); assert.equal((await collect(stream)).result.errorMessage, "dispatch-unknown");
  gate.reject(hostile); await tick(); assert.equal(reads, 0); assert.deepEqual(f.calls, []);
});

for (const position of ["resultFacts", "recordResult", "settle"]) test(`failed ${position} never publishes success before durable completion`, async t => {
  const hooks = position === "resultFacts" ? { facts: () => { throw new Error(secret); } } : position === "recordResult" ? { record: () => { throw new Error(secret); } } : { settle: () => { throw new Error(secret); } };
  const f = await fixture(t, hooks), scope = f.scope(), output = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(output.events.at(-1).type, "error"); assert.equal(output.result.errorMessage, "dispatch-unknown");
  assert.equal((await f.store.observe("attempt-4")).state, position === "settle" ? "result-recorded" : "sending");
  assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
for (const fault of ["collector", "store"]) test(`late ${fault} method drift blocks mutation even after local close`, async t => {
  const gate = deferred(), actual = terminalMessage(); const f = await fixture(t, { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual, { gate }) });
  const scope = f.scope(), wrapper = f.create(), stream = wrapper.models.streamSimple(f.model, scope.prompt, scope.options); await tick(); wrapper.close();
  assert.equal((await collect(stream)).result.errorMessage, "dispatch-unknown");
  if (fault === "collector") f.cfg.resultFacts = () => assert.fail("replacement collector must not run");
  else f.cfg.store.recordResult = () => assert.fail("replacement store must not run");
  gate.resolve(); await tick(); await tick(); assert.equal((await f.store.observe("attempt-4")).state, "sending");
});
test("unrelated authorization/model drift after close does not erase valid late old facts", async t => {
  const gate = deferred(), actual = terminalMessage(); const f = await fixture(t, { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual, { gate }) });
  const scope = f.scope(), wrapper = f.create(), stream = wrapper.models.streamSimple(f.model, scope.prompt, scope.options); await tick(); wrapper.close();
  assert.equal((await collect(stream)).result.errorMessage, "dispatch-unknown");
  Object.defineProperty(f.cfg, "authorize", { enumerable: true, get() { assert.fail("late fact must not inspect current authorize"); } });
  f.model.headers.authorization = "new descriptor"; gate.resolve(); await tick(); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "settled");
});
test("private lookup returns detached data and allowed public options preserve explicit values without inventing reasoning off", async t => {
  let observed; const f = await fixture(t, { stream: (model, context, options) => { observed = { model, context, options }; return rawStream([{ type: "done", reason: "stop", message: f.actual }], f.actual); } });
  const scope = f.scope(), wrapper = f.create(), copy = wrapper.models.getModel("fictional", "model"); copy.headers.authorization = "detached";
  assert.equal(f.model.headers.authorization, secret);
  Object.assign(scope.options, { temperature: 0.5, cacheRetention: "none", sessionId: "原生session", timeoutMs: 100, maxRetryDelayMs: 0 });
  await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(Object.hasOwn(observed.options, "reasoning"), false); assert.equal(observed.options.signal, scope.signal); assert.equal(observed.options.maxRetryDelayMs, 0);
  assert.notEqual(observed.context, scope.prompt); assert.equal(Object.isFrozen(scope.prompt), false);
});
test("inner result rejection while iteration waits is already handled and returns fixed unknown", async t => {
  const gate = deferred(), actual = terminalMessage(); const f = await fixture(t, { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual, { gate, resultReject: new Error(secret) }) });
  const scope = f.scope(), stream = f.create().models.streamSimple(f.model, scope.prompt, scope.options);
  assert.equal((await collect(stream)).result.errorMessage, "dispatch-unknown"); gate.resolve(); await tick();
  assert.equal((await f.store.observe("attempt-4")).state, "sending"); assert.equal(f.state.collectors, 0);
});
for (const fault of ["terminal-reason", "message-stop", "iterator-bool", "iterator-getter"]) test(`malformed public stream ${fault} remains unknown with no collector`, async t => {
  let reads = 0; const actual = terminalMessage();
  const f = await fixture(t, { stream: () => {
    if (fault === "iterator-bool" || fault === "iterator-getter") {
      const first = fault === "iterator-bool" ? { done: 1, value: undefined } : { get done() { reads++; throw new Error(secret); }, value: undefined };
      return { [Symbol.asyncIterator]() { return { async next() { return first; } }; }, async result() { return actual; } };
    }
    if (fault === "message-stop") actual.stopReason = "impossible";
    return rawStream([{ type: "done", reason: fault === "terminal-reason" ? "impossible" : "stop", message: actual }], actual);
  } });
  const scope = f.scope(); assert.equal((await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options))).result.errorMessage, "dispatch-unknown");
  assert.equal(f.state.collectors, 0); assert.equal(reads, 0);
});


for (const kind of ["generation", "compaction"]) for (const observedRoute of [null, { provider: "other-remote", model: "model" }]) test(`${kind} unknown/drift remote retains result reference and reservation but terminal is fixed unknown`, async t => {
  const f = await fixture(t, { facts: () => ({ result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute }, settlement: null }) });
  const scope = f.scope(kind), wrapper = f.create();
  if (kind === "generation") {
    const output = await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
    assert.equal(output.events.at(-1).type, "error"); assert.equal(output.result.errorMessage, "dispatch-unknown");
  } else await assert.rejects(wrapper.models.completeSimple(f.model, scope.prompt, scope.options), fixedError());
  const attempt = await f.store.observe("attempt-4"); assert.equal(attempt.state, "result-recorded"); assert.equal(attempt.result.resultRef, "e".repeat(64));
  assert.equal(attempt.settlement, null); assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});

for (const [type, reason, stopReason] of [["done", "stop", "error"], ["error", "error", "stop"]]) test(`review02 legal contradictory ${type} terminal is rejected before collector or durable result`, async t => {
  const actual = terminalMessage({ stopReason });
  const event = { type, reason, [type === "done" ? "message" : "error"]: actual };
  const f = await fixture(t, { stream: () => rawStream([event], actual) }); const scope = f.scope();
  const output = await collect(f.create().models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(output.result.errorMessage, "dispatch-unknown"); assert.equal(output.events.at(-1).type, "error");
  assert.equal(f.state.collectors, 0); assert.equal((await f.store.observe("attempt-4")).state, "sending");
  assert.equal((await f.store.snapshot("task-4")).reservedCostUnits, "20");
});
test("review02 inherited prototype getters never supplement captured fields", { concurrency: false }, async t => {
  for (const field of ["partial", "type", "reason", "message", "error", "role", "stopReason", "done"]) await t.test(field, { concurrency: false }, async t => {
    const actual = terminalMessage(); let item = null, events = [{ type: "done", reason: "stop", message: actual }];
    if (field === "partial") events.unshift({ type: "text_delta", contentIndex: 0, delta: "x" });
    if (field === "type") delete events[0].type;
    if (field === "reason") delete events[0].reason;
    if (field === "message") delete events[0].message;
    if (field === "error") events = [{ type: "error", reason: "error" }];
    if (field === "role") delete actual.role;
    if (field === "stopReason") delete actual.stopReason;
    if (field === "done") item = { value: events[0] };
    let reads = 0;
    const f = await fixture(t, { stream: () => {
      const descriptor = Object.create(null); descriptor.configurable = true;
      descriptor.get = () => { reads++; return field === "partial" || field === "message" || field === "error" ? actual : field === "role" ? "assistant" : field === "stopReason" || field === "reason" ? "stop" : field === "done" ? false : "done"; };
      Object.defineProperty(Object.prototype, field, descriptor);
      if (item) {
        let returned = false;
        return { [Symbol.asyncIterator]() { return { async next() { if (!returned) { returned = true; return item; } return { done: true }; } }; }, async result() { return actual; } };
      }
      return rawStream(events, actual);
    } });
    const scope = f.scope(), wrapper = f.create(), previous = Object.getOwnPropertyDescriptor(Object.prototype, field);
    let output;
    try { output = await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); }
    finally { if (previous) Object.defineProperty(Object.prototype, field, previous); else delete Object.prototype[field]; }
    assert.equal(reads, 0, `inherited ${field} getter must never run`);
    if (field === "partial") assert.equal(output.result, actual);
    else { assert.equal(output.result.errorMessage, "dispatch-unknown"); assert.equal(f.state.collectors, 0); assert.equal((await f.store.observe("attempt-4")).state, "sending"); }
  });
});
test("review02 inherited toJSON is never called while capturing/size-checking plain data or arrays", { concurrency: false }, async t => {
  const f = await fixture(t), scope = f.scope(), wrapper = f.create(), original = f.cfg.authorize;
  let reads = 0;
  f.cfg.authorize = original;
  const previous = Object.getOwnPropertyDescriptor(Object.prototype, "toJSON");
  const descriptor = Object.create(null); descriptor.configurable = true; descriptor.get = () => { reads++; return () => "unsafe inherited serialization"; };
  let output;
  try { Object.defineProperty(Object.prototype, "toJSON", descriptor); output = await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); }
  finally { if (previous) Object.defineProperty(Object.prototype, "toJSON", previous); else delete Object.prototype.toJSON; }
  assert.equal(reads, 0); assert.equal(output.result, f.actual); assert.equal(f.state.authorizations, 3);
});

for (const cut of ["resultFacts", "recordResult", "settle"]) test(`review03 producer changes legal stopReason during ${cut} wait: no stale terminal success, old facts retained`, async t => {
  const gate = deferred(), actual = terminalMessage();
  const facts = { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } },
    settlement: { usage: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 5 } };
  let entered = false;
  const hooks = { stream: () => rawStream([{ type: "done", reason: "stop", message: actual }], actual) };
  if (cut === "resultFacts") hooks.facts = async () => { entered = true; await gate.promise; return facts; };
  if (cut === "recordResult") hooks.record = async () => { entered = true; await gate.promise; };
  if (cut === "settle") hooks.settle = async () => { entered = true; await gate.promise; };
  const f = await fixture(t, hooks), scope = f.scope(), stream = f.create().models.streamSimple(f.model, scope.prompt, scope.options), receiving = collect(stream);
  await tick(); assert.equal(entered, true); actual.stopReason = "error"; gate.resolve();
  const output = await receiving;
  assert.equal(output.events.at(-1).type, "error"); assert.equal(output.result.errorMessage, "dispatch-unknown");
  assert.equal(actual.stopReason, "error"); assert.equal(Object.isFrozen(actual), false);
  const attempt = await f.store.observe("attempt-4"); assert.equal(attempt.state, "settled"); assert.equal(attempt.result.resultRef, "e".repeat(64));
  assert.equal(attempt.settlement.estimatedCostUnits, 5); assert.equal((await f.store.snapshot("task-4")).chargedCostUnits, "5");
});
for (const mutation of ["role", "stopReason", "deferred"]) test(`review03 complete original message changes ${mutation} during persist await: reject publication without undoing facts`, async t => {
  const gate = deferred(), actual = terminalMessage(); let entered = false;
  const f = await fixture(t, { complete: () => actual, settle: async () => { entered = true; await gate.promise; } });
  const scope = f.scope("compaction"), answer = f.create().models.completeSimple(f.model, scope.prompt, scope.options);
  await tick(); assert.equal(entered, true);
  if (mutation === "role") actual.role = "user";
  if (mutation === "stopReason") actual.stopReason = "not-public";
  if (mutation === "deferred") actual.deferred = { id: "unexpected" };
  gate.resolve(); await assert.rejects(answer, fixedError());
  const attempt = await f.store.observe("attempt-4"); assert.equal(attempt.state, "settled"); assert.equal(attempt.settlement.estimatedCostUnits, 5);
  assert.equal(Object.isFrozen(actual), false);
});

test("original commitSending body receives once despite own call fake ACK; no SQL fixture", async () => {
  const bridge = createDurableCallIdentityBridge(), controller = new AbortController(), signal = controller.signal;
  bridge.generationHooks.beforeRequest(undefined, { taskId: 4, conversationId: 9 }, { abortSignal: signal });
  const actual = terminalMessage(), model = { provider: "fictional", id: "model", api: "fixture-api", maxTokens: 100 };
  const counts = { getter: 0, spy: 0, commits: 0, sends: 0 }; let durableSending = false;
  const store = { async prepare(value) { assert.equal(this, store); assert.equal(value.attemptId, "attempt-4"); },
    async commitSending(id) { counts.commits++; assert.equal(this, store); assert.equal(id, "attempt-4"); durableSending = true; return { attempt: null, committedNow: true }; },
    async recordResult(id, result) { assert.equal(this, store); if (!durableSending) throw Error("synthetic prepared cannot record"); }, async settle() { assert.equal(this, store); } };
  Object.defineProperty(store.commitSending, "call", { get() { counts.getter++; return async (receiver, id) => { counts.spy++; assert.equal(receiver, store); assert.equal(id, "attempt-4"); return { attempt: null, committedNow: true }; }; } });
  const models = { streamSimple(givenModel, context, options) { counts.sends++; assert.equal(this, models); assert.equal(JSON.stringify(givenModel), JSON.stringify(model)); assert.equal(options.signal, signal); return rawStream([{ type: "done", reason: "stop", message: actual }], actual); },
    completeSimple() { assert.fail("unexpected complete"); }, getModel() { return model; } };
  const cfg = { models, ai: factory, bridge, store, model, limits: { timeoutMs: 1000, maxEvents: 10 },
    async authorize() { return { attemptId: "attempt-4", taskId: "task-4", phase: "generation", nativeTaskId: 4, nativeConversationId: 9, registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "model" }, budget: { scopeId: "scope-4", maxCalls: 1, maxCostUnits: 20, reservationUnits: 10 } }; },
    async resultFacts() { return { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } }, settlement: null }; } };
  const wrapper = createDurableModelDispatch(cfg);
  const observed = await collect(wrapper.models.streamSimple(model, { messages: [{ role: "user", content: "synthetic" }] }, { signal, maxTokens: 50, maxRetries: 0, transport: "sse" }));
  assert.deepEqual(counts, { getter: 0, spy: 0, commits: 1, sends: 1 });
  assert.equal(durableSending, true); assert.equal(observed.result, actual);
});
