import assert from "node:assert/strict";
import { test } from "node:test";
import { createPiDelegateStreamFn } from "../official-delegate-stream.ts";

const clone = value => structuredClone(value);
function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
function fixture(overrides = {}) {
  const model = { provider: "fixture", id: "model", api: "openai-completions", baseUrl: "https://fixture.invalid/v1",
    headers: { "x-private": "synthetic-secret" }, compat: { supportsUsageInStreaming: true } };
  const context = { messages: [{ role: "user", content: "original", timestamp: 1 }] };
  const calls = [], events = [], originals = [];
  let current = clone(model), error;
  const original = freeze({ result() { throw new Error("must not consume"); }, [Symbol.asyncIterator]() { throw new Error("must not iterate"); } });
  const ai = freeze({ createAssistantMessageEventStream() {
    calls.push("factory");
    const rows = [];
    return { push(event) { events.push(event); rows.push(event); }, end(message) { this.message = message; },
      async result() { return this.message; }, async *[Symbol.asyncIterator]() { yield* rows; } };
  } });
  const runtime = freeze({ getModel(provider, id) { calls.push("model"); assert.equal(provider, "fixture"); assert.equal(id, "model"); return current; },
    getError() { calls.push("error"); return error; }, streamSimple(...args) { calls.push("submit"); originals.push(args); return overrides.submit ? overrides.submit(...args) : original; } });
  let checkCount = 0, gateCount = 0;
  const runtimeHandle = freeze({ modelRuntime: runtime, async check() { calls.push("check"); await overrides.check?.(++checkCount, f); } });
  const input = { ai, runtimeHandle, binding: { provider: "fixture", model: "model" }, maxTokens: 71, reasoning: "low", sessionId: "session",
    async beforeDispatch(snapshot, signal) { calls.push("gate"); return overrides.gate ? overrides.gate(snapshot, ++gateCount, f, signal) : true; } };
  const f = { model, context, calls, events, originals, original, ai, runtime, runtimeHandle, input,
    setModel(value) { current = value; }, getModel() { return current; }, setError(value) { error = value; } };
  f.streamFn = createPiDelegateStreamFn(input);
  return f;
}
async function denied(f, options, code = "pi-delegate-dispatch-denied", reason = "error") {
  const stream = await f.streamFn(f.model, f.context, options);
  const message = await stream.result();
  assert.equal(message.errorMessage, code); assert.equal(message.stopReason, reason);
  assert.equal(message.provider, "fixture"); assert.equal(message.model, "model");
  assert.equal(f.events.at(-1).error, message); assert.equal(f.events.at(-1).reason, reason);
  const rows = []; for await (const row of stream) rows.push(row);
  assert.deepEqual(rows, [{ type: "error", reason, error: message }]);
  assert.equal(JSON.stringify(message).includes("synthetic-secret"), false);
  if (code === "pi-delegate-dispatch-denied") assert.equal(f.originals.length, 0);
  return message;
}

test("factory is inert and rejects invalid trusted inputs with a fixed code", () => {
  const f = fixture(); assert.deepEqual(f.calls, []);
  for (const patch of [{ binding: { provider: "", model: "model" } }, { binding: { provider: "fixture", model: "model", extra: true } },
    { binding: { provider: "fixture\n", model: "model" } }, { ai: {} }, { runtimeHandle: {} }, { beforeDispatch: null },
    { maxTokens: 0 }, { reasoning: "off" }, { sessionId: "" }]) {
    assert.throws(() => createPiDelegateStreamFn({ ...f.input, ...patch }), /^Error: pi-delegate-stream-input$/);
  }
  assert.deepEqual(f.calls, []);
});

test("each invocation checks twice and gates once, preserving original stream and SDK objects", async () => {
  const f = fixture();
  for (let index = 0; index < 2; index++) assert.equal(await f.streamFn(f.model, f.context), f.original);
  assert.equal(f.calls.filter(item => item === "check").length, 4);
  assert.equal(f.calls.filter(item => item === "gate").length, 2);
  assert.equal(f.calls.filter(item => item === "submit").length, 2);
  assert.equal(f.calls.includes("factory"), false);
  assert.equal(Object.isFrozen(f.runtime), true); assert.equal(Object.isFrozen(f.ai), true);
});

test("false, undefined, nonboolean and throwing authorization fail closed without leaking secrets", async () => {
  for (const gate of [() => false, () => undefined, () => 1, () => { throw new Error("synthetic-secret"); }]) {
    const f = fixture({ gate }); await denied(f);
    assert.equal(f.calls.filter(item => item === "check").length, 1);
  }
});

test("runtime throw and rejection encode unknown submission rather than denial", async () => {
  for (const submit of [() => { throw new Error("synthetic-secret"); }, async () => { throw new Error("synthetic-secret"); }]) {
    const f = fixture({ submit }); await denied(f, undefined, "pi-delegate-runtime-submit-unknown");
    assert.equal(f.originals.length, 1);
  }
});

test("cancellation before dispatch, during either check, and during a pending gate never submits", async () => {
  for (const phase of ["before", "check1", "check2", "gate"]) {
    const controller = new AbortController();
    const f = fixture({ check: async count => { if (phase === "check" + count) controller.abort("synthetic-secret"); },
      gate: async () => { if (phase === "gate") { await Promise.resolve(); controller.abort("synthetic-secret"); } return true; } });
    if (phase === "before") controller.abort("synthetic-secret");
    await denied(f, { signal: controller.signal }, "pi-delegate-dispatch-denied", "aborted");
  }
  let release, entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  const controller = new AbortController();
  const f = fixture({ gate: () => { entered(); return new Promise(resolve => { release = resolve; }); } });
  const pending = denied(f, { signal: controller.signal }, "pi-delegate-dispatch-denied", "aborted");
  await waiting; controller.abort(); release(true); await pending;
});

test("runtime configuration errors, check failures and drift after each await block submission", async () => {
  for (const phase of ["initial", "check1", "gate", "check2"]) {
    const mutate = f => { f.getModel().baseUrl = "https://other.invalid"; };
    const f = fixture({ check: async (count, value) => { if (phase === "check" + count) mutate(value); },
      gate: async (_snapshot, _count, value) => { if (phase === "gate") mutate(value); return true; } });
    if (phase === "initial") f.setError("synthetic-secret");
    await denied(f);
  }
  for (const count of [1, 2]) {
    const f = fixture({ check: async number => { if (number === count) throw new Error("synthetic-secret"); } }); await denied(f);
  }
});

test("provider, model, API, route, headers and schema changes cannot change the pinned dispatch", async () => {
  for (const mutate of [model => { model.provider = "other"; }, model => { model.id = "other"; }, model => { model.api = "openai-responses"; },
    model => { model.baseUrl += "/other"; }, model => { model.headers.extra = "synthetic-secret"; }, model => { model.compat.extra = true; }]) {
    const f = fixture(); await f.streamFn(f.model, f.context); f.originals.length = 0;
    mutate(f.model); await denied(f);
    const g = fixture(); await g.streamFn(g.model, g.context); g.originals.length = 0;
    mutate(g.getModel()); await denied(g);
  }
});

test("gate and caller mutations are isolated from pinned model, transcript and trusted options", async () => {
  const f = fixture({ gate: async (snapshot, _count, value) => {
    snapshot.binding.provider = "other"; snapshot.model.baseUrl = "https://gate.invalid"; snapshot.model.headers.extra = "secret";
    snapshot.context.messages[0].content = "gate"; snapshot.options.maxTokens = 999;
    value.model.baseUrl = "https://caller.invalid"; value.context.messages[0].content = "caller";
    await Promise.resolve(); return true;
  } });
  const model = clone(f.model), context = clone(f.context);
  assert.equal(await f.streamFn(f.model, f.context), f.original);
  const [actualModel, actualContext, options] = f.originals[0];
  assert.deepEqual(actualModel, model); assert.deepEqual(actualContext, context);
  assert.equal(options.maxTokens, 71);
  actualModel.headers.extra = "runtime"; actualContext.messages[0].content = "runtime";
  assert.equal(f.getModel().headers.extra, undefined);
});

test("only signal crosses incoming options and factory configuration cannot be overridden", async () => {
  const f = fixture(), controller = new AbortController();
  const incoming = { signal: controller.signal, apiKey: "synthetic-secret", env: {}, fetch() {}, headers: {}, onPayload() {}, onResponse() {}, transformContext() {},
    maxTokens: 999, reasoning: "max", sessionId: "other", transport: "websocket", maxRetries: 7 };
  Object.defineProperty(incoming, "ignoredGetter", { get() { throw new Error("must not inspect"); } });
  f.input.binding.provider = "other";
  await f.streamFn(f.model, f.context, incoming);
  assert.deepEqual(f.originals[0][2], { maxTokens: 71, reasoning: "low", sessionId: "session", transport: "sse", maxRetries: 0, signal: controller.signal });
  const g = fixture();
  const streamFn = createPiDelegateStreamFn({ ...g.input, maxTokens: undefined, reasoning: undefined, sessionId: undefined });
  await streamFn(g.model, g.context);
  assert.deepEqual(g.originals[0][2], { maxTokens: undefined, reasoning: undefined, sessionId: undefined, transport: "sse", maxRetries: 0, signal: undefined });
});

test("invalid request data is a public failure stream without executing accessors", async () => {
  const f = fixture();
  Object.defineProperty(f.model, "api", { get() { throw new Error("synthetic-secret"); }, enumerable: true });
  await denied(f);
  const g = fixture(); g.context.callback = () => {}; await denied(g);
});

test("malformed signal accessors also fail through protocol rather than Promise rejection", async () => {
  const f = fixture();
  await denied(f, { signal: { get aborted() { throw new Error("synthetic-secret"); } } });
});

test("an initial spoofed API, route or schema is denied without poisoning later valid dispatch", async () => {
  for (const mutate of [model => { model.api = "unverified-api"; }, model => { model.baseUrl = "https://spoof.invalid"; },
    model => { model.compat.supportsUsageInStreaming = false; }]) {
    const f = fixture(), originalModel = clone(f.model);
    mutate(f.model);
    const message = await denied(f);
    assert.equal(message.api, "openai-completions");
    assert.equal(f.calls.includes("gate"), false);
    assert.equal(f.calls.includes("check"), false);
    assert.equal(await f.streamFn(originalModel, f.context), f.original);
    assert.equal(f.originals.length, 1);
    assert.deepEqual(f.originals[0][0], originalModel);
  }
});

test("gate receives the original signal separately from cloned authorization data", async () => {
  const controller = new AbortController();
  const f = fixture({ gate: async (snapshot, _count, _fixture, signal) => {
    assert.equal(signal, controller.signal);
    assert.equal(Object.hasOwn(snapshot, "signal"), false);
    assert.equal(Object.hasOwn(snapshot.options, "signal"), false);
    return true;
  } });
  assert.equal(await f.streamFn(f.model, f.context, { signal: controller.signal }), f.original);
});
