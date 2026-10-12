import assert from "node:assert/strict";
import { test } from "node:test";
import { createPiDelegateAgentInitializer } from "../official-delegate-agent.ts";

const clone = value => structuredClone(value);
function freeze(value) { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }
function fixture(custom = {}) {
  const model = { provider: "fixture", id: "model", api: "openai-completions", baseUrl: "https://fixture.invalid", compat: {} };
  const log = [], instances = [], submitted = [], events = [];
  let current = clone(model), error, count = 0;
  const ai = freeze({ createAssistantMessageEventStream() { const rows = []; return { push(row) { rows.push(row); events.push(row); }, end(message) { this.message = message; },
    async result() { return this.message; }, async *[Symbol.asyncIterator]() { yield* rows; } }; } });
  const runtime = freeze({ getModel() { log.push("getModel"); return current; }, getError() { return error; }, streamSimple(...args) {
    submitted.push(args); if (custom.resultFailure) return { async result() { throw new Error("synthetic-secret"); } }; return { async result() { return { role: "assistant", content: [{ type: "text", text: "reply" }], stopReason: "stop" }; } };
  } });
  const runtimeHandle = freeze({ modelRuntime: runtime, async check() { log.push("check"); await custom.check?.(++count, f); } });
  class FakeAgent {
    constructor(options) { log.push("constructor"); instances.push(this); if (custom.constructorFailure) throw new Error("synthetic-secret"); this.options = options; this.state = { ...options.initialState, messages: [], isStreaming: false };
      this.listeners = []; this.queue = []; this.abortCount = 0; }
    subscribe(listener) { this.listeners.push(listener); return () => { this.listeners = this.listeners.filter(value => value !== listener); }; }
    async emit(event) { for (const listener of this.listeners) { if (custom.nonAwaitingEvents) listener(event, this.signal); else await listener(event, this.signal); } }
    async prompt(value) {
      log.push("prompt"); this.controller = new AbortController(); this.signal = this.controller.signal; this.state.isStreaming = true;
      this.state.messages.push({ role: "user", content: value, timestamp: 1 });
      this.running = (async () => {
        try {
          await custom.prompt?.(this, f);
          await this.emit({ type: "message_start", message: this.state.messages.at(-1) });
          const stream = await this.options.streamFn(this.state.model, { messages: this.state.messages }, { signal: this.signal });
          const message = await stream.result(); this.state.messages.push(message);
          if (message.errorMessage) this.state.errorMessage = message.errorMessage;
          await this.emit({ type: "agent_end", messages: this.state.messages });
        } finally { this.state.isStreaming = false; }
      })();
      await this.running;
    }
    steer(message) { this.queue.push(["steer", message]); }
    followUp(message) { this.queue.push(["followUp", message]); }
    hasQueuedMessages() { return this.queue.length > 0; }
    abort() { this.abortCount++; this.controller?.abort(); }
    async waitForIdle() { await this.running; }
  }
  Object.freeze(FakeAgent.prototype); Object.freeze(FakeAgent);
  const core = freeze({ Agent: FakeAgent });
  const tool = { name: "tk_read", label: "Read", description: "fixture", parameters: { type: "object", properties: { path: { type: "string" } } }, async execute() { return { content: [] }; } };
  const input = { core, ai, runtimeHandle, binding: { provider: "fixture", model: "model" }, systemPrompt: "trusted system", maxTokens: 19, cacheSessionId: "cache-label",
    toolDefinitions: custom.tools ? [tool] : [], authorizeTool: custom.authorizeTool, beforeDispatch: custom.beforeDispatch ?? (async () => true) };
  const f = { log, instances, submitted, events, model, runtime, input, tool, setModel(value) { current = value; }, getModel() { return current; }, setError(value) { error = value; } };
  f.initialize = createPiDelegateAgentInitializer(input);
  return f;
}

test("initializer is inert, concurrent initialization constructs exactly once and exposes only facade", async () => {
  const f = fixture(); assert.deepEqual(f.log, []);
  const first = f.initialize(), second = f.initialize(); assert.equal(first, second);
  const [a, b] = await Promise.all([first, second]); assert.equal(a, b); assert.equal(Object.isFrozen(a), true);
  assert.equal(f.instances.length, 1);
  assert.deepEqual(Object.keys(a).sort(), ["abort", "followUp", "prompt", "snapshot", "steer", "subscribe", "waitForIdle"].sort());
  const options = f.instances[0].options;
  assert.deepEqual(Object.keys(options).sort(), ["initialState", "streamFn", "beforeToolCall", "sessionId", "transport", "toolExecution", "steeringMode", "followUpMode"].sort());
  assert.deepEqual(options.initialState, { model: f.model, thinkingLevel: "off", systemPrompt: "trusted system", tools: [], messages: [] });
  assert.equal(options.transport, "sse"); assert.equal(options.toolExecution, "sequential");
  assert.equal(options.sessionId, "cache-label"); assert.equal(options.steeringMode, "one-at-a-time"); assert.equal(options.followUpMode, "one-at-a-time");
});

test("initialization failure remains memoized without constructor or retry", async () => {
  const f = fixture({ check: async () => { throw new Error("synthetic-secret"); } });
  const first = f.initialize(); await assert.rejects(first, /^Error: pi-delegate-agent-initialize-failed$/);
  assert.equal(f.initialize(), first); await assert.rejects(f.initialize()); assert.deepEqual(f.log, ["check"]); assert.equal(f.instances.length, 0);
  const g = fixture({ check: async (count, value) => { if (count === 2) value.getModel().baseUrl += "/drift"; } });
  await assert.rejects(g.initialize(), /initialize-failed/); assert.equal(g.instances.length, 0);
});

test("literal repeated prompts retain one Agent transcript and gate every actual request", async () => {
  let gates = 0;
  const f = fixture({ beforeDispatch: async () => { gates++; return true; } }), agent = await f.initialize();
  await agent.prompt(" /skill literal "); await agent.prompt("second");
  assert.equal(f.instances.length, 1); assert.equal(gates, 2); assert.equal(f.submitted.length, 2);
  assert.deepEqual(agent.snapshot().messages.filter(message => message.role === "user").map(message => message.content), [" /skill literal ", "second"]);
  assert.equal(f.submitted[0][2].reasoning, undefined); assert.equal(f.submitted[0][2].maxTokens, 19);
  for (const thinkingLevel of ["minimal", "low", "medium", "high", "xhigh", "max"]) {
    const g = fixture(); const initialize = createPiDelegateAgentInitializer({ ...g.input, thinkingLevel }); const a = await initialize();
    await a.prompt("fixture"); assert.equal(g.submitted[0][2].reasoning, thinkingLevel);
  }
});

test("busy-only steering and followup preserve slash literals, prompt refuses overlapping calls", async () => {
  let release, entered; const ready = new Promise(resolve => { entered = resolve; });
  const f = fixture({ prompt: async () => { entered(); await new Promise(resolve => { release = resolve; }); } }), agent = await f.initialize();
  assert.throws(() => agent.steer("idle"), /idle/); assert.throws(() => agent.followUp("idle"), /idle/);
  const pending = agent.prompt("first"); await ready;
  await assert.rejects(agent.prompt("overlap"), /busy/);
  await agent.steer("/skill raw"); await agent.followUp(" /template raw ");
  assert.equal(agent.snapshot().hasQueuedMessages, true);
  assert.deepEqual(f.instances[0].queue.map(([kind, message]) => [kind, message.role, message.content]), [["steer", "user", "/skill raw"], ["followUp", "user", " /template raw "]]);
  release(); await pending; await agent.waitForIdle();
});

test("invalid or oversized control text is rejected before SDK methods", async () => {
  const f = fixture(), agent = await f.initialize();
  for (const value of [undefined, "", " \n\t ", "界".repeat(21846), {}]) {
    await assert.rejects(agent.prompt(value), /text/); assert.throws(() => agent.steer(value), /text/); assert.throws(() => agent.followUp(value), /text/);
  }
  assert.equal(f.log.includes("prompt"), false); assert.equal(f.submitted.length, 0);
});

test("subscription events and snapshots are independent data copies with original signal", async () => {
  const f = fixture(), agent = await f.initialize();
  const unsubscribe = agent.subscribe((event, signal) => { assert.equal(signal, f.instances[0].signal);
    if (event.message) event.message.content = "observer mutation";
    if (event.messages) event.messages[0].content = "observer mutation";
  });
  await agent.prompt("original");
  const view = agent.snapshot(); view.binding.provider = "other"; view.messages[0].content = "view mutation";
  assert.equal(agent.snapshot().messages[0].content, "original"); assert.equal(agent.snapshot().binding.provider, "fixture"); unsubscribe();
});

test("runtime drift on control precheck prevents requests", async () => {
  const f = fixture(), agent = await f.initialize(); f.getModel().baseUrl += "/drift";
  await assert.rejects(agent.prompt("fixture"), /sdk-error/); assert.equal(f.submitted.length, 0);
});

test("tool authorization denies false undefined and throws; snapshots exclude executable tools", async () => {
  for (const authorizeTool of [async () => false, async () => undefined, async () => { throw new Error("synthetic-secret"); }]) {
    const f = fixture({ tools: true, authorizeTool }); await f.initialize();
    const result = await f.instances[0].options.beforeToolCall({ toolCall: { type: "toolCall", id: "call", name: "tk_read", arguments: {} }, args: {}, assistantMessage: { content: [] }, context: { tools: [f.tool] } });
    assert.deepEqual(result, { block: true, reason: "pi-delegate-tool-denied", terminate: true });
  }
  const f = fixture({ tools: true, authorizeTool: async (snapshot, signal) => {
    assert.equal(Object.hasOwn(snapshot, "context"), false); assert.equal(signal, controller.signal);
    snapshot.args.path = "mutation"; snapshot.toolCall.name = "mutation"; snapshot.assistantMessage.content.push("mutation"); return true;
  } }); const controller = new AbortController(); await f.initialize();
  const context = { toolCall: { name: "tk_read" }, args: { path: "original" }, assistantMessage: { content: [] }, context: { tools: [f.tool] } };
  assert.equal(await f.instances[0].options.beforeToolCall(context, controller.signal), undefined);
  assert.equal(context.args.path, "original"); assert.equal(context.toolCall.name, "tk_read"); assert.deepEqual(context.assistantMessage.content, []);
  assert.equal(f.instances[0].options.initialState.tools[0].execute, f.tool.execute);
});

test("tool gate cancellation and runtime drift after authorization fail closed", async () => {
  for (const phase of ["cancel", "drift"]) {
    const controller = new AbortController();
    const f = fixture({ tools: true, authorizeTool: async () => { if (phase === "cancel") controller.abort(); else f.getModel().compat.changed = true; return true; } });
    await f.initialize();
    assert.deepEqual(await f.instances[0].options.beforeToolCall({ toolCall: {}, args: {}, assistantMessage: {} }, controller.signal),
      { block: true, reason: "pi-delegate-tool-denied", terminate: true });
  }
});

test("abort during pending dispatch gate submits nothing and permanently retires facade", async () => {
  let entered, release; const ready = new Promise(resolve => { entered = resolve; });
  const f = fixture({ beforeDispatch: async (_snapshot, signal) => { assert.equal(signal, f.instances[0].signal); entered(); await new Promise(resolve => { release = resolve; }); return true; } });
  const agent = await f.initialize(), pending = agent.prompt("fixture"); await ready;
  agent.abort(); agent.abort(); release(); await assert.rejects(pending, /retired/);
  assert.equal(f.submitted.length, 0); assert.equal(f.instances[0].abortCount, 1); assert.equal(agent.snapshot().retired, true);
  await assert.rejects(agent.prompt("after"), /retired/); assert.throws(() => agent.steer("after"), /retired/); assert.throws(() => agent.followUp("after"), /retired/);
  assert.throws(() => agent.subscribe(() => {}), /retired/); await agent.waitForIdle();
  assert.deepEqual(await f.instances[0].options.beforeToolCall({}, f.instances[0].signal), { block: true, reason: "pi-delegate-tool-denied", terminate: true });
});

test("observer failure retires and aborts, prompt and settlement cannot report success or leak exception", async () => {
  const f = fixture(), agent = await f.initialize(); agent.subscribe(async () => { throw new Error("synthetic-secret"); });
  await assert.rejects(agent.prompt("fixture"), /^Error: pi-delegate-agent-observer-failed$/);
  await assert.rejects(agent.waitForIdle(), /^Error: pi-delegate-agent-observer-failed$/);
  assert.equal(f.submitted.length, 0); assert.equal(agent.snapshot().observerFailure, "pi-delegate-agent-observer-failed");
  assert.equal(JSON.stringify(agent.snapshot()).includes("synthetic-secret"), false); assert.equal(f.instances[0].abortCount, 1);
});

test("unsupported tool fields and symbol schemas fail explicitly at capture", () => {
  const f = fixture();
  for (const tool of [{ ...f.tool, replay: "safe" }, { ...f.tool, parameters: { type: "object", [Symbol.for("TypeBox.Kind")]: "Object" } },
    { ...f.tool, outputSchema: {} }, { ...f.tool, prepareArguments() {} }, { ...f.tool, executionMode: "parallel" }]) {
    assert.throws(() => createPiDelegateAgentInitializer({ ...f.input, toolDefinitions: [tool], authorizeTool: async () => true }), /tools-unsupported/);
  }
  assert.throws(() => createPiDelegateAgentInitializer({ ...f.input, toolDefinitions: [f.tool] }), /tool-authorizer/);
  assert.deepEqual(f.log, []);
});

test("schema capture preserves candidate nonenumerable metadata and nested descriptor flags", async () => {
  const f = fixture();
  const nested = { type: "string" };
  Object.defineProperty(nested, "~kind", { value: "String", enumerable: false, writable: false, configurable: false });
  Object.defineProperty(nested, "~optional", { value: { enabled: true }, enumerable: false, writable: true, configurable: true });
  const schema = { type: "object", properties: { path: nested } };
  Object.defineProperty(schema, "~kind", { value: "Object", enumerable: false, writable: false, configurable: false });
  const initialize = createPiDelegateAgentInitializer({ ...f.input, toolDefinitions: [{ ...f.tool, parameters: schema }], authorizeTool: async () => true });
  nested.type = "number"; nested["~optional"].enabled = false;
  await initialize();
  const actual = f.instances[0].options.initialState.tools[0].parameters;
  assert.equal(actual.properties.path.type, "string"); assert.equal(actual.properties.path["~optional"].enabled, true);
  assert.deepEqual(Object.getOwnPropertyDescriptor(actual, "~kind"), Object.getOwnPropertyDescriptor(schema, "~kind"));
  assert.deepEqual(Object.getOwnPropertyDescriptor(actual.properties.path, "~kind"), Object.getOwnPropertyDescriptor(nested, "~kind"));
  const descriptor = Object.getOwnPropertyDescriptor(actual.properties.path, "~optional");
  assert.equal(descriptor.enumerable, false); assert.equal(descriptor.writable, true); assert.equal(descriptor.configurable, true);
  assert.notEqual(actual, schema); assert.notEqual(descriptor.value, nested["~optional"]);
});

test("abort does not clear native queues and retired dispatch gate blocks later model requests", async () => {
  let release, entered; const ready = new Promise(resolve => { entered = resolve; });
  const f = fixture({ prompt: async () => { entered(); await new Promise(resolve => { release = resolve; }); } });
  const agent = await f.initialize(), pending = agent.prompt("fixture"); await ready;
  await agent.followUp("queued literal"); agent.abort(); release(); await assert.rejects(pending, /retired/);
  assert.equal(agent.snapshot().hasQueuedMessages, true); assert.equal(f.submitted.length, 0);
  const stream = await f.instances[0].options.streamFn(f.model, { messages: [] });
  assert.equal((await stream.result()).errorMessage, "pi-delegate-dispatch-denied"); assert.equal(f.submitted.length, 0);
});

test("unknown SDK exceptions and synthesized errorMessage observations use fixed codes", async () => {
  const f = fixture({ prompt: async () => { throw new Error("synthetic-secret"); } }), agent = await f.initialize();
  await assert.rejects(agent.prompt("fixture"), /^Error: pi-delegate-agent-sdk-error$/);
  assert.equal(f.submitted.length, 0);
  const g = fixture({ prompt: async instance => { instance.state.messages.push({ role: "assistant", content: [], errorMessage: "synthetic-secret" });
    await instance.emit({ type: "message_end", message: instance.state.messages.at(-1) }); } });
  const view = await g.initialize(); let seen;
  view.subscribe(event => { if (event.message?.errorMessage) seen = event.message.errorMessage; });
  await view.prompt("fixture");
  assert.equal(seen, "pi-delegate-sdk-error"); assert.equal(JSON.stringify(view.snapshot()).includes("synthetic-secret"), false);
});

test("constructor failure is memoized and missing or errored models never fall back", async () => {
  const f = fixture({ constructorFailure: true }); const pending = f.initialize();
  await assert.rejects(pending, /^Error: pi-delegate-agent-initialize-failed$/);
  assert.equal(f.initialize(), pending); assert.equal(f.instances.length, 1);
  for (const mutate of [value => value.setModel(undefined), value => value.setError("synthetic-secret"), value => { value.getModel().id = "fallback"; }]) {
    const g = fixture(); mutate(g); await assert.rejects(g.initialize(), /initialize-failed/); assert.equal(g.instances.length, 0);
  }
});

test("dispatch denial cannot yield facade prompt success or submit a runtime request", async () => {
  const f = fixture({ beforeDispatch: async () => false }), agent = await f.initialize();
  await assert.rejects(agent.prompt("fixture"), /^Error: pi-delegate-agent-sdk-error$/);
  assert.equal(f.submitted.length, 0);
  assert.equal(agent.snapshot().messages.at(-1).errorMessage, "pi-delegate-sdk-error");
});

test("a submitted stream decoding failure retires and cannot cause a second request", async () => {
  const f = fixture({ resultFailure: true }), agent = await f.initialize();
  await assert.rejects(agent.prompt("first"), /^Error: pi-delegate-agent-sdk-error$/);
  assert.equal(f.submitted.length, 1);
  let secondError;
  try { await agent.prompt("second"); } catch (error) { secondError = error; }
  assert.equal(f.submitted.length, 1);
  assert.equal(agent.snapshot().retired, true);
  assert.equal(secondError?.message, "pi-delegate-agent-retired");
  assert.equal(f.instances[0].abortCount, 1);
  assert.throws(() => agent.steer("after failure"), /retired/);
  assert.throws(() => agent.followUp("after failure"), /retired/);
  const deniedStream = await f.instances[0].options.streamFn(f.model, { messages: [] });
  assert.equal((await deniedStream.result()).errorMessage, "pi-delegate-dispatch-denied");
  assert.deepEqual(await f.instances[0].options.beforeToolCall({}), { block: true, reason: "pi-delegate-tool-denied", terminate: true });
  assert.equal(f.submitted.length, 1);
});

test("literal tool args and details with errorMessage survive selective SDK error sanitization", async () => {
  const literal = { role: "assistant", errorMessage: "literal business data", nested: { errorMessage: "literal nested data" } };
  const f = fixture({ prompt: async instance => {
    await instance.emit({ type: "tool_execution_end", toolCallId: "call", toolName: "tk_read", args: clone(literal), result: { content: [], details: clone(literal) } });
    instance.state.messages.push({ role: "toolResult", toolCallId: "call", toolName: "tk_read", content: [], details: clone(literal) });
  } }), agent = await f.initialize();
  let event;
  agent.subscribe(value => { if (value.type === "tool_execution_end") event = value; });
  await agent.prompt("fixture");
  assert.deepEqual(event.args, literal); assert.deepEqual(event.result.details, literal);
  assert.deepEqual(agent.snapshot().messages.find(message => message.role === "toolResult").details, literal);
});

test("queue becoming idle during recheck is a known no-effect denial and does not retire", async () => {
  let releasePrompt, enterPrompt, releaseQueueCheck, enterQueueCheck, blockQueueCheck = false, firstPrompt = true;
  const promptReady = new Promise(resolve => { enterPrompt = resolve; });
  const queueReady = new Promise(resolve => { enterQueueCheck = resolve; });
  const f = fixture({ prompt: async () => {
    if (firstPrompt) { firstPrompt = false; enterPrompt(); await new Promise(resolve => { releasePrompt = resolve; }); }
  }, check: async () => {
    if (blockQueueCheck) { blockQueueCheck = false; enterQueueCheck(); await new Promise(resolve => { releaseQueueCheck = resolve; }); }
  } });
  const agent = await f.initialize(), prompt = agent.prompt("first"); await promptReady;
  blockQueueCheck = true; const queue = agent.steer("known unqueued"); await queueReady;
  releasePrompt(); await prompt; releaseQueueCheck();
  await assert.rejects(queue, /^Error: pi-delegate-agent-idle$/);
  assert.equal(agent.snapshot().retired, false); assert.equal(agent.snapshot().hasQueuedMessages, false);
  assert.equal(f.instances[0].abortCount, 0);
  await assert.rejects(agent.prompt(" "), /text/); assert.equal(agent.snapshot().retired, false);
  await agent.prompt("second"); assert.equal(f.submitted.length, 2);
});

test("message_update sanitizes only public assistant positions and keeps nested business messages literal", async () => {
  const literal = { role: "assistant", errorMessage: "literal data" }, observed = [];
  const f = fixture({ prompt: async instance => {
    for (const key of ["partial", "message", "error"]) {
      const message = { role: "assistant", content: [{ type: "toolCall", id: "call", name: "fixture", arguments: clone(literal) }], errorMessage: "synthetic-secret" };
      await instance.emit({ type: "message_update", message: clone(message), assistantMessageEvent: { type: "error", [key]: clone(message) } });
    }
    await instance.emit({ type: "message_end", message: { role: "user", content: "literal", errorMessage: "literal data" } });
  } });
  const agent = await f.initialize(); agent.subscribe(event => { observed.push(event); }); await agent.prompt("fixture");
  for (const event of observed.filter(value => value.type === "message_update")) {
    assert.equal(event.message.errorMessage, "pi-delegate-sdk-error");
    assert.deepEqual(event.message.content[0].arguments, literal);
    const message = event.assistantMessageEvent.partial ?? event.assistantMessageEvent.message ?? event.assistantMessageEvent.error;
    assert.equal(message.errorMessage, "pi-delegate-sdk-error"); assert.deepEqual(message.content[0].arguments, literal);
  }
  assert.equal(observed.find(value => value.message?.role === "user" && value.type === "message_end").message.errorMessage, "literal data");
  assert.equal(JSON.stringify(observed).includes("synthetic-secret"), false);
});


test("explicit restored public messages are captured independently before Agent construction", async () => {
  const f = fixture();
  const messages = [{ role: "user", content: "persisted own request", timestamp: 1 },
    { role: "assistant", content: [{ type: "text", text: "persisted own answer" }], provider: "fixture", model: "model", api: "openai-completions", timestamp: 2 }];
  const initialize = createPiDelegateAgentInitializer({ ...f.input, initialMessages: messages });
  messages[0].content = "caller mutation";
  await initialize();
  assert.equal(f.instances[0].options.initialState.messages[0].content, "persisted own request");
  assert.equal(f.submitted.length, 0);
});

test("public Agent nonawaited observers serialize persistence and block completion acknowledgement", async () => {
  const f = fixture({ nonAwaitingEvents: true }), agent = await f.initialize();
  let release, entered, settled = false;
  const ready = new Promise(resolve => { entered = resolve; });
  const writes = [];
  agent.subscribe(async event => {
    writes.push(event.type);
    if (event.type === "agent_end") { entered(); await new Promise(resolve => { release = resolve; }); writes.push("persisted"); }
  });
  const pending = agent.prompt("own bounded task").then(() => { settled = true; });
  await ready; await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false);
  release(); await pending;
  assert.deepEqual(writes, ["message_start", "agent_end", "persisted"]);
});
