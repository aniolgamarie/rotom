import assert from "node:assert/strict";
import test from "node:test";
import { createDurableReadonlyPhaseModelRegistry } from "../src/registry.ts";
import { factory as ai, rawStream, deferred } from "./provider-events.ts";
import { createDurableModelDispatch, createDurableSdkSimpleModelDispatch } from "../src/provider.ts";
import { PublicEventStream } from "./provider-events.ts";
const SECRET = "SYNTHETIC_PRIVATE_PHASE_MODELS";
const tick = () => new Promise(resolve => setImmediate(resolve));
async function collect(stream) { const events = []; for await (const event of stream) events.push(event); return { events, message: await stream.result() }; }
function unknown(value) { assert.equal(value.message.stopReason, "error"); assert.equal(value.message.errorMessage, "dispatch-unknown"); assert.ok(!JSON.stringify(value).includes(SECRET)); }
function invalid(call) { assert.throws(call, /readonly-unavailable/); }
function phaseFixture(hooks = {}) {
  const state = { order: [], rows: new Map(), sends: 0, commitBodies: 0, committedAcks: 0, authorizes: 0, collectors: 0, handlers: [], defined: [], hookCalls: 0, controlExecutes: 0, sdkReads: 0, entryReads: 0, disposals: 0, current: true, listeners: new Set(), nested: [] };
  const actual = { role: "assistant", content: [{ type: "text", text: "synthetic" }], api: "fixture-api", provider: "fictional", model: "model", usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: 1 };
  const model = { provider: "fictional", id: "model", api: "fixture-api", maxTokens: 100 };
  const handlers = {};
  function definition(kind) {
    const name = "pi." + kind, target = kind === "generation" ? "request" : "summarize";
    const phases = { async [target](task, runtime, context) {
      state.handlers.push({ kind, phase: target, receiver: this, args: [...arguments] }); assert.equal(this, phases);
      if (hooks.handler) return hooks.handler(kind, task, runtime, context);
      if (kind === "generation") return collect(runtime.models.streamSimple(model, { messages: [{ role: "user", content: "synthetic" }] }, { signal: runtime.signal, maxRetries: 0, transport: "sse" }));
      return { message: await runtime.models.completeSimple(model, { messages: [] }, { signal: runtime.signal, maxRetries: 0, transport: "sse" }) };
    }, retry(task, runtime, context) { state.handlers.push({ kind, phase: "retry", receiver: this, args: [...arguments] }); return "retry"; } };
    const def = { name, version: 1, phases, initial(input) { assert.equal(this, def); return { phase: target, input }; }, abort(...args) { assert.equal(this, def); return args[0]; }, migrate(...args) { assert.equal(this, def); return args[0]; }, hooks: { marker() {} } };
    handlers[kind] = phases; return def;
  }
  const builtin = [{ definition: definition("generation") }, { definition: { name: "pi.tool", version: 1, initial() {}, abort() {}, phases: { execute() {} } } }, { definition: definition("compaction") }];
  const rootTask = { definition: { name: "rotom.durable.request", version: 1, initial() {}, abort() {}, phases: { fake() {} } } };
  class Snapshot {
    constructor(extensions) { this.extensions = extensions; }
    installed() { hooks.table?.("installed"); return this.extensions; }
    tools() { hooks.table?.("tools"); return this.extensions.flatMap(extension => extension.tools.map(tool => ({ extension, tool }))); }
    tasks() { hooks.table?.("tasks"); return [...builtin, ...this.extensions.flatMap(extension => extension.tasks)]; }
    extension(name) { hooks.table?.("extension", name); return this.extensions.find(value => value.name === name); }
    task(name) { const value = this.tasks().find(task => task.definition.name === name); hooks.table?.("task", name); return value; }
    sections() { hooks.table?.("sections"); return []; }
  }
  class Registry {
    constructor() { this.current = new Snapshot([]); }
    snapshot() { hooks.snapshot?.(); return this.current; }
    install(extension) { this.current = new Snapshot([extension]); }
    uninstall() { this.current = new Snapshot([]); }
    subscribe(listener) { assert.equal(this, state.base); state.listeners.add(listener); hooks.subscribe?.(listener); if (hooks.nonFunctionDisposer) return undefined;
      const disposer = () => { state.disposals++; state.listeners.delete(listener); if (hooks.disposerThrow) throw Error(SECRET); }; state.lastDisposer = disposer; return disposer; }
  }
  const durable = { GenerationTask: builtin[0], ToolTask: builtin[1], CompactionTask: builtin[2], AssistantEntry: { kind: "pi.assistant", is() {} },
    createRegistry() { assert.equal(this, durable); const value = new Registry(); state.base = value; return value; },
    defineTask(def) { assert.equal(this, durable); state.defined.push(def); hooks.defineTask?.(def); return { definition: def }; },
    defineTool(value) { assert.equal(this, durable); hooks.defineTool?.(value); return value; }, defineExtension(value) { assert.equal(this, durable); return value; }, hook() { state.hookCalls++; assert.fail("old hooks not used"); } };
  const control = { async prepare(invocation) { assert.equal(this, control); state.controlInvocation = invocation; hooks.controlPrepare?.(); return {}; }, check() { assert.equal(this, control); return true; }, async execute(ticket, invocation, signal) { assert.equal(this, control); state.controlExecutes++; return { text: "synthetic" }; } };
  const models = { streamSimple(given, context, options) { assert.equal(this, models); state.sends++; state.order.push("send"); return hooks.stream ? hooks.stream(given, context, options) : rawStream([{ type: "done", reason: "stop", message: actual }], actual); },
    async completeSimple(...args) { assert.equal(this, models); const stream = this.streamSimple(...args); for await (const _ of stream) {} return stream.result(); } };
  const store = { async prepare(input) { assert.equal(this, store); state.order.push("prepare"); if (hooks.prepare) await hooks.prepare(input);
      if (state.rows.has(input.attemptId)) { assert.deepEqual(state.rows.get(input.attemptId).input, input); return; } state.rows.set(input.attemptId, { input, state: "prepared" }); },
    async commitSending(id) { assert.equal(this, store); state.commitBodies++; state.order.push("sending"); const row = state.rows.get(id); const committedNow = row.state === "prepared";
      if (committedNow) { row.state = "sending"; state.committedAcks++; } if (hooks.sending) await hooks.sending(row); return { attempt: row, committedNow }; },
    async recordResult(id, result) { assert.equal(this, store); state.order.push("record"); if (hooks.record) await hooks.record(id, result); const row = state.rows.get(id); assert.equal(row.state, "sending"); row.result = result; row.state = "result-recorded"; },
    async settle(id, settlement) { assert.equal(this, store); state.order.push("settle"); if (hooks.settle) await hooks.settle(id, settlement); const row = state.rows.get(id); assert.equal(row.state, "result-recorded"); row.settlement = settlement; row.state = "settled"; } };
  // 显式测试 grant，绝不从 nativeTaskId、signal 或 lease 次数分配新 attempt。
  let grant = { attemptId: "explicit-grant-one", taskId: "explicit-task", phase: "generation", nativeTaskId: 3, nativeConversationId: 9, registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "model" }, budget: { scopeId: "explicit-scope", maxCalls: 3, maxCostUnits: 30, reservationUnits: 10 } };
  const modelDispatch = { models, ai, store, model, limits: { timeoutMs: 1000, maxEvents: 20 },
    async authorize(snapshot, signal) { assert.equal(this, modelDispatch); state.authorizes++; if (hooks.authorize) await hooks.authorize(snapshot, signal); if (state.hold) throw Error("synthetic unknown reservation denied"); return grant; },
    async resultFacts(snapshot, message, signal) { assert.equal(this, modelDispatch); state.collectors++; state.order.push("collector"); assert.equal(message, actual); if (hooks.collector) await hooks.collector(snapshot, message, signal); return { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } }, settlement: { usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 2 } }; } };
  const config = { durable, rootTask, control, verifyCurrent: function() { assert.equal(this, config); hooks.verify?.(); return state.current; }, sourceIdentity: "a".repeat(64), registryIdentity: "b".repeat(64), modelDispatch };
  function scope(wrapper, kind = "generation", id = kind === "generation" ? 3 : 5, existing) {
    const controller = existing?.controller ?? new AbortController(), context = existing?.context ?? { get abortSignal() { hooks.context?.(); return controller.signal; } };
    const runtime = existing?.runtime ?? { taskId: id, conversationId: 9, signal: controller.signal, models: wrapper?.models };
    const task = { id, conversationId: 9, kind: "pi." + kind, version: 1, state: { status: "running", checkpoint: { phase: kind === "generation" ? "request" : "summarize" } } };
    Object.defineProperty(task, "input", { get() { assert.fail("adapter input read"); } });
    return { controller, context, runtime, task, run() { const token = wrapper.registry.snapshot().task(task.kind); return token.definition.phases[task.state.checkpoint.phase](task, runtime, context); } };
  }
  function toolCall(wrapper, snapshot = wrapper.registry.snapshot()) {
    const args = { rootRef: "fake-root", path: "docs/file" }, controller = new AbortController(), context = { abortSignal: controller.signal };
    const toolTask = { id: 4, conversationId: 9, kind: "pi.tool", version: 1, owner: 3, background: false, abortRequested: false, input: { assistant: 2, callId: "call-1" }, state: { status: "running", checkpoint: { phase: "execute", arguments: { ...args }, replay: "unsafe" } } };
    const generation = { id: 3, conversationId: 9, kind: "pi.generation", version: 1, background: false, abortRequested: false, input: {}, state: { status: "running", checkpoint: { phase: "request" } } };
    const entry = { id: 2, conversationId: 9, kind: "pi.assistant", byTaskId: 3, model: [{ role: "assistant", content: [{ type: "toolCall", id: "call-1", name: "rotom_read", arguments: { ...args } }] }] };
    const api = { taskId: 4, conversationId: 9, callId: "call-1", registry: snapshot,
      async getTask(id, ctx) { assert.equal(this, api); assert.equal(ctx, context); state.sdkReads++; if (hooks.getTask) await hooks.getTask(id); return id === 4 ? toolTask : generation; },
      async commit(callback, ctx) { assert.equal(this, api); assert.equal(ctx, context); const tx = { async entry(token, id) { assert.equal(this, tx); assert.equal(token, durable.AssistantEntry); assert.equal(id, 2); state.entryReads++; return entry; } }; return callback(tx); } };
    const tool = snapshot.tools()[0].tool;
    return { api, args, context, controller, run: () => tool.execute(args, api, context) };
  }
  return { state, builtin, handlers, rootTask, durable, control, models, modelDispatch, store, model, actual, config, create: () => createDurableReadonlyPhaseModelRegistry(config), scope, toolCall,
    grant(value) { grant = { ...grant, ...value }; }, hooks };
}


function simple(hooks = {}, complete = false) {
  const counts = { factories: 0, take: 0, checks: 0, authorizes: 0, prepares: 0, commits: 0, acks: 0, sends: 0, records: 0 };
  const controller = new AbortController(), model = { provider: "fictional", id: "model", api: "fixture-api", maxTokens: 100 }, context = { messages: [] };
  const originalOptions = { signal: controller.signal, maxRetries: 0, transport: "sse" };
  const identity = Object.freeze({ schema: 1, nativeTaskId: 3, nativeConversationId: 9, call_kind: complete ? "compaction" : "generation" });
  const message = { role: "assistant", content: [], provider: "fictional", model: "model", api: "fixture-api", stopReason: "stop", timestamp: 1 };
  const envelopes = [], order = [];
  const bridge = { take(signal, operation) { assert.equal(this, bridge); counts.take++; assert.equal(signal, controller.signal); hooks.take?.(); return identity; },
    check(signal, operation, original) { assert.equal(this, bridge); assert.equal(original, identity); counts.checks++; hooks.check?.(); return true; } };
  const sdkAI = { createAssistantMessageEventStream() { assert.equal(this, sdkAI); counts.factories++; hooks.factory?.(); return new PublicEventStream(); } };
  const store = { async prepare(input) { assert.equal(this, store); counts.prepares++; order.push("prepare"); if (hooks.prepare) await hooks.prepare(); },
    async commitSending(id) { assert.equal(this, store); assert.equal(id, "explicit-attempt"); counts.commits++; order.push("commit-body"); if (hooks.sending) await hooks.sending(); counts.acks++; order.push("ack"); return { attempt: null, committedNow: hooks.replay ? false : true }; },
    async recordResult() { assert.equal(this, store); counts.records++; }, async settle() { assert.equal(this, store); } };
  const models = { streamSimple(given, ctx, opts) { assert.equal(this, models); counts.sends++; order.push("send"); assert.equal(counts.acks, 1); hooks.entry?.(given, ctx, opts); return rawStream([{ type: "done", reason: "stop", message }], message); },
    async completeSimple(given, ctx, opts) { assert.equal(this, models); counts.sends++; order.push("send"); assert.equal(counts.acks, 1); hooks.entry?.(given, ctx, opts); return message; } };
  const cfg = { models, ai: sdkAI, bridge, store, model, limits: { timeoutMs: 1000, maxEvents: 20 },
    async authorize(snapshot, signal) { counts.authorizes++; envelopes.push(snapshot); if (hooks.authorize) await hooks.authorize(); return { attemptId: "explicit-attempt", taskId: "explicit-task", phase: identity.call_kind, nativeTaskId: 3, nativeConversationId: 9, registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "model" }, budget: { scopeId: "explicit-scope", maxCalls: 1, maxCostUnits: 20, reservationUnits: 10 } }; },
    async resultFacts() { return { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } }, settlement: null }; } };
  return { counts, cfg, model, context, options: originalOptions, controller, envelopes, order, message, hooks, complete,
    create(strict = false) { return (strict ? createDurableModelDispatch : createDurableSdkSimpleModelDispatch)(cfg); },
    async run(wrapper) { if (complete) return { message: await wrapper.models.completeSimple(model, context, originalOptions) }; return collect(wrapper.models.streamSimple(model, context, originalOptions)); } };
}
async function refused(f, wrapper = f.create()) {
  if (f.complete) await assert.rejects(f.run(wrapper), /dispatch-unknown/);
  else unknown(await f.run(wrapper));
  assert.equal(f.counts.sends, 0);
}
for (const complete of [false, true]) for (const explicit of [false, true]) test(`SDK simple ${complete ? "complete" : "stream"} ${explicit ? "explicit" : "missing"} cap persists ACK before entry`, async () => {
  const f = simple({ entry(model, context, options) { assert.equal(options.maxTokens, explicit ? 20 : 100); assert.equal(options.signal, f.controller.signal); } }, complete);
  if (explicit) f.options.maxTokens = 20;
  const wrapper = f.create(); assert.deepEqual(Object.keys(wrapper).sort(), ["close", "models"]); assert.ok(Object.isFrozen(wrapper)); assert.ok(Object.isFrozen(wrapper.models));
  assert.equal((await f.run(wrapper)).message, f.message); assert.equal(f.counts.authorizes, 3); assert.equal(f.counts.commits, 1); assert.equal(f.counts.sends, 1); assert.equal(f.counts.factories, complete ? 0 : 1);
  assert.equal(f.envelopes.length, 3); for (const envelope of f.envelopes) { assert.equal(envelope.options.maxTokens, explicit ? 20 : 100); assert.ok(Object.isFrozen(envelope)); assert.equal(envelope, f.envelopes[0]); }
  assert.deepEqual(f.order, ["prepare", "commit-body", "ack", "send"]); assert.equal(Object.hasOwn(f.options, "maxTokens"), explicit); assert.equal(Object.isFrozen(f.options), false);
});
test("old strict still rejects missing cap and replay ACK cannot send", async () => {
  const f = simple(); await refused(f, f.create(true)); assert.equal(f.counts.take, 0); assert.equal(f.counts.authorizes, 0);
  const g = simple({ replay: true }); await refused(g); assert.equal(g.counts.commits, 1); assert.equal(g.counts.authorizes, 2);
});
for (const cap of [undefined, 0, -1, 1.5, Infinity, NaN, Number.MAX_SAFE_INTEGER + 1]) test(`metadata cap rejects ${String(cap)} before foreign callback`, () => {
  const f = simple(); f.model.maxTokens = cap; assert.throws(f.create, /input-invalid/); assert.deepEqual(f.counts, { factories: 0, take: 0, checks: 0, authorizes: 0, prepares: 0, commits: 0, acks: 0, sends: 0, records: 0 });
});
for (const mode of ["missing", "getter", "proxy"]) test(`metadata ${mode} never reads getter/proxy`, () => {
  const f = simple(); let calls = 0;
  if (mode === "missing") delete f.model.maxTokens;
  if (mode === "getter") Object.defineProperty(f.model, "maxTokens", { get() { calls++; throw Error(SECRET); } });
  if (mode === "proxy") f.cfg.model = new Proxy(f.model, { get() { calls++; throw Error(SECRET); }, ownKeys() { calls++; throw Error(SECRET); } });
  assert.throws(f.create, /input-invalid/); assert.equal(calls, 0); assert.equal(f.counts.factories, 0);
});
for (const mutation of ["own-undefined", "unknown", "getter", "proxy", "signal", "retry", "transport", "reasoning", "optional-undefined"]) test(`invalid original options ${mutation} cannot be repaired by factory`, async () => {
  const f = simple(); let calls = 0;
  if (mutation === "own-undefined") f.options.maxTokens = undefined;
  if (mutation === "unknown") f.options.apiKey = SECRET;
  if (mutation === "getter") Object.defineProperty(f.options, "maxTokens", { configurable: true, enumerable: true, get() { calls++; throw Error(SECRET); } });
  if (mutation === "proxy") f.options = new Proxy(f.options, { ownKeys() { calls++; throw Error(SECRET); } });
  if (mutation === "signal") delete f.options.signal;
  if (mutation === "retry") f.options.maxRetries = 1;
  if (mutation === "transport") f.options.transport = "websocket";
  if (mutation === "reasoning") f.options.reasoning = "off";
  if (mutation === "optional-undefined") f.options.temperature = undefined;
  // run closes over originalOptions; the Proxy case invokes the public entry directly.
  f.hooks.factory = () => { if (mutation !== "proxy") { delete f.options.maxTokens; delete f.options.apiKey; delete f.options.reasoning; delete f.options.temperature; f.options.signal = f.controller.signal; f.options.maxRetries = 0; f.options.transport = "sse"; } };
  const wrapper = f.create();
  if (mutation === "proxy") unknown(await collect(wrapper.models.streamSimple(f.model, f.context, f.options))); else await refused(f, wrapper);
  assert.equal(calls, 0); assert.equal(f.counts.factories, 1); assert.equal(f.counts.take, 0); assert.equal(f.counts.authorizes, 0); assert.equal(f.counts.prepares, 0);
});
function change(f, direction) {
  if (direction === "add") f.options.maxTokens = 100;
  if (direction === "delete") delete f.options.maxTokens;
  if (direction === "order") { const value = f.options.transport; delete f.options.transport; f.options.transport = value; const signal = f.options.signal; delete f.options.signal; f.options.signal = signal; }
  if (direction === "flags") Object.defineProperty(f.options, "transport", { writable: false });
  if (direction === "prototype") Object.setPrototypeOf(f.options, null);
  if (direction === "ref") f.options.signal = new AbortController().signal;
  if (direction === "model") f.model.maxTokens = 101;
  if (direction === "context") f.context.messages.push({ role: "user", content: "drift" });
}
for (const direction of ["add", "delete"]) test(`factory equivalent-cap ${direction} binds before first foreign`, async () => {
  const f = simple(); if (direction === "delete") f.options.maxTokens = 100; f.hooks.factory = () => change(f, direction);
  await refused(f); assert.equal(f.counts.factories, 1); assert.equal(f.counts.take, 0); assert.equal(f.counts.authorizes, 0);
});
for (const cut of ["authorize", "prepare", "sending", "last-check"]) for (const direction of ["add", "delete", "order", "flags", "prototype", "ref", "model", "context"]) test(`${cut} original ${direction} drift cannot enter Models`, async () => {
  const f = simple(); if (direction === "delete") f.options.maxTokens = 100;
  let once = false, checksAfterThird = 0;
  if (cut === "last-check") f.hooks.check = () => { if (f.counts.authorizes === 3 && ++checksAfterThird === 2) change(f, direction); };
  else f.hooks[cut] = async () => { if (once) return; once = true; const gate = deferred(); queueMicrotask(() => { change(f, direction); gate.resolve(); }); await gate.promise; };
  const wrapper = f.create(); await refused(f, wrapper); assert.equal(f.counts.sends, 0);
  if (cut === "last-check") assert.equal(checksAfterThird, 2);
  assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});
for (const direction of ["add", "delete"]) test(`bridge take equivalent ${direction} has no authorize`, async () => {
  const f = simple(); if (direction === "delete") f.options.maxTokens = 100; f.hooks.take = () => change(f, direction);
  await refused(f); assert.equal(f.counts.take, 1); assert.equal(f.counts.authorizes, 0);
});
test("new phase factory admits SDK-like missing-cap generation and compaction without changing handlers", async () => {
  const f = phaseFixture(), wrapper = f.create(); assert.equal(f.state.authorizes, 0);
  assert.equal((await f.scope(wrapper).run()).message, f.actual); assert.equal(f.state.sends, 1); assert.equal(f.state.commitBodies, 1); assert.equal(f.state.committedAcks, 1);
  f.grant({ attemptId: "explicit-cmp", taskId: "explicit-cmp-task", phase: "compaction", nativeTaskId: 5, budget: { scopeId: "explicit-cmp-scope", maxCalls: 2, maxCostUnits: 20, reservationUnits: 10 } });
  assert.equal((await f.scope(wrapper, "compaction").run()).message, f.actual); assert.equal(f.state.sends, 2);
});
for (const direction of ["add", "delete"]) test(`last phase Context getter equivalent-cap ${direction} rejects send`, async () => {
  let f, options, checks = 0;
  f = phaseFixture({ handler: async (kind, task, runtime, context) => {
    options = { signal: runtime.signal, maxRetries: 0, transport: "sse" }; if (direction === "delete") options.maxTokens = 100;
    return collect(runtime.models.streamSimple(f.model, { messages: [] }, options));
  }, context: () => { if (options && f.state.authorizes === 3 && ++checks === 2) { if (direction === "add") options.maxTokens = 100; else delete options.maxTokens; } } });
  const wrapper = f.create(); unknown(await f.scope(wrapper).run()); assert.equal(checks, 2); assert.equal(f.state.sends, 0); assert.equal(f.state.commitBodies, 1);
});

for (const mode of ["throw", "malformed-stream"]) test(`factory ${mode} cannot trigger a second allocation`, () => {
  const f = simple(); f.cfg.ai.createAssistantMessageEventStream = function() { f.counts.factories++; if (mode === "throw") throw Error(SECRET); return {}; };
  const wrapper = f.create(); assert.throws(() => wrapper.models.streamSimple(f.model, f.context, f.options), /dispatch-unknown/);
  assert.equal(f.counts.factories, 1); assert.equal(f.counts.take, 0); assert.equal(f.counts.authorizes, 0); assert.equal(f.counts.sends, 0);
});
test("factory cannot replace original Context baseline before bridge", async () => {
  const f = simple(); f.hooks.factory = () => f.context.messages.push({ role: "user", content: "changed" });
  await refused(f); assert.equal(f.counts.factories, 1); assert.equal(f.counts.take, 0); assert.equal(f.counts.authorizes, 0);
});
