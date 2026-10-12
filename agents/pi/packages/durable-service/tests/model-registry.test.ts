import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableReadonlyModelRegistry, createDurableReadonlyRegistry } from "../src/registry.ts";
import { factory as ai, rawStream, deferred } from "./provider-events.ts";

const tick = () => new Promise(resolve => setImmediate(resolve));
const secret = "SYNTHETIC_PRIVATE model/config/body";
async function collect(stream) { const events = []; for await (const value of stream) events.push(value); return { events, message: await stream.result() }; }
function unknown(result) { assert.equal(result.message.stopReason, "error"); assert.equal(result.message.errorMessage, "dispatch-unknown"); assert(!JSON.stringify(result).includes(secret)); }
const message = () => ({ role: "assistant", content: [{ type: "text", text: "synthetic" }], api: "fixture-api", provider: "fictional", model: "model", usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: 1 });
function fixture(hooks = {}) {
  const builtin = ["pi.generation", "pi.tool", "pi.compaction"].map(name => ({ definition: { name, version: 1, initial: () => ({ phase: "fixture" }), phases: { fixture() {} } } }));
  const rootTask = { definition: { name: "rotom.durable.request", version: 1, initial: () => ({ phase: "fixture" }), phases: { fixture() {} } } };
  class Snapshot {
    constructor(extensions) { this.extensions = extensions; }
    installed() { return this.extensions; }
    tools() { return this.extensions.flatMap(extension => extension.tools.map(tool => ({ extension, tool }))); }
    tasks() { return [...builtin, ...this.extensions.flatMap(extension => extension.tasks)]; }
    extension(name) { return this.extensions.find(value => value.name === name); }
    task(name) { const original = this.tasks().find(value => value.definition.name === name); if (hooks.snapshotTask) hooks.snapshotTask(name, this); return original; }
    sections() { return []; }
  }
  class Registry {
    constructor() { this.current = new Snapshot([]); }
    snapshot() { return this.current; }
    install(extension) { this.current = new Snapshot([extension]); }
    uninstall() { this.current = new Snapshot([]); }
    subscribe() { return () => {}; }
  }
  const registrations = [], state = { order: [], rows: new Map(), sends: 0, authorizes: 0, collectors: 0, current: true };
  const durable = { AssistantEntry: { kind: "pi.assistant", is() {} }, GenerationTask: builtin[0], CompactionTask: builtin[2], createRegistry() { assert.equal(this, durable); return new Registry(); }, defineTool(value) { assert.equal(this, durable); return value; }, defineExtension(value) { assert.equal(this, durable); return value; }, hook(task, handlers) { assert.equal(this, durable); const value = { task: task.definition.name, handlers }; registrations.push(value); if (hooks.registration) return hooks.registration(value); return value; } };
  const control = { prepare: async () => ({}), check: () => true, execute: async () => ({ text: "synthetic readonly" }) };
  const model = { provider: "fictional", id: "model", api: "fixture-api", maxTokens: 100, headers: { private: secret } };
  const actual = message();
  const models = {
    streamSimple(given, context, options) { assert.equal(this, models); state.sends++; state.order.push("send"); return hooks.stream ? hooks.stream(given, context, options) : rawStream([{ type: "done", reason: "stop", message: actual }], actual); },
    async completeSimple(...args) { assert.equal(this, models); const stream = this.streamSimple(...args); for await (const _ of stream) {} return stream.result(); },
  };
  const store = {
    async prepare(input) { assert.equal(this, store); state.order.push("prepare"); if (hooks.prepare) await hooks.prepare(input); state.rows.set(input.attemptId, { input, state: "prepared" }); },
    async commitSending(id) { assert.equal(this, store); state.order.push("sending"); if (hooks.commitSending) await hooks.commitSending(id); const row = state.rows.get(id); row.state = "sending"; return { attempt: row, committedNow: true }; },
    async recordResult(id, result) { assert.equal(this, store); state.order.push("record"); if (hooks.recordResult) await hooks.recordResult(id, result); Object.assign(state.rows.get(id), { result, state: "result-recorded" }); },
    async settle(id, settlement) { assert.equal(this, store); state.order.push("settle"); if (hooks.settle) await hooks.settle(id, settlement); Object.assign(state.rows.get(id), { settlement, state: "settled" }); },
  };
  const modelDispatch = { models, ai, store, model, limits: { timeoutMs: 1000, maxEvents: 20 },
    async authorize(snapshot, signal) { assert.equal(this, modelDispatch); state.authorizes++; if (hooks.authorize) await hooks.authorize(snapshot, signal); return { attemptId: "attempt-" + snapshot.identity.nativeTaskId, taskId: "task-" + snapshot.identity.nativeTaskId, phase: snapshot.identity.call_kind, nativeTaskId: snapshot.identity.nativeTaskId, nativeConversationId: snapshot.identity.nativeConversationId, registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "model" }, budget: { scopeId: "scope-" + snapshot.identity.nativeTaskId, maxCalls: 3, maxCostUnits: 30, reservationUnits: 10 } }; },
    async resultFacts(snapshot, value, signal) { assert.equal(this, modelDispatch); state.collectors++; state.order.push("collector"); assert.equal(value, actual); if (hooks.collector) await hooks.collector(snapshot, value, signal); return { result: { resultRef: "e".repeat(64), outcome: "completed", observedRoute: { provider: "fictional", model: "model" } }, settlement: { usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 }, estimatedCostUnits: 2 } }; },
  };
  const config = { durable, rootTask, control, verifyCurrent: () => state.current, sourceIdentity: "a".repeat(64), registryIdentity: "b".repeat(64), modelDispatch };
  const create = () => createDurableReadonlyModelRegistry(config);
  function scope(wrapper, kind = "generation", id = 4, selected = true) {
    const controller = new AbortController(), context = { get abortSignal() { return controller.signal; } }, api = { taskId: id, conversationId: 9 };
    if (selected) { const registration = wrapper.registry.snapshot().installed()[0].hooks[kind === "generation" ? 0 : 1]; const name = kind === "generation" ? "beforeRequest" : "beforeCompact"; registration.handlers[name].call(registration.handlers, undefined, api, context); }
    return { controller, context, api, prompt: { messages: [{ role: "user", content: "synthetic" }] }, options: { signal: controller.signal, maxTokens: 20, maxRetries: 0, transport: "sse" } };
  }
  return { builtin, rootTask, durable, control, model, models, store, actual, modelDispatch, config, state, registrations, create, scope };
}

test("single original bridge hooks compose generation stream and compaction complete, original receivers and order", async () => {
  const f = fixture(), wrapper = f.create(), extension = wrapper.registry.snapshot().installed()[0]; assert(Object.isFrozen(wrapper)); assert.equal(wrapper.bridge, undefined); assert.equal(extension.hooks.length, 2); assert.equal(wrapper.registry.snapshot().tasks().length, 4); assert.equal(extension.tools.length, 2);
  assert.deepEqual(extension.hooks.map(value => value.task), ["pi.generation", "pi.compaction"]); assert.equal(extension.hooks[0], f.registrations[0]); assert(!Object.isFrozen(f.registrations[0])); assert(!Object.isFrozen(f.rootTask)); assert(!Object.isFrozen(f.builtin[0]));
  const scope = f.scope(wrapper), result = await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); assert.equal(result.message, f.actual); assert.deepEqual(f.state.order, ["prepare", "sending", "send", "collector", "record", "settle"]); assert.equal(f.state.authorizes, 3); assert.equal(f.state.rows.get("attempt-4").state, "settled");
  const compact = f.scope(wrapper, "compaction", 5); assert.equal(await wrapper.models.completeSimple(f.model, compact.prompt, compact.options), f.actual); assert.equal(f.state.sends, 2); assert.equal(f.state.rows.get("attempt-5").state, "settled");
});
test("missing chosen hook is zero underlying send and metadata is never authority", async () => {
  const f = fixture(), wrapper = f.create(), scope = f.scope(wrapper, "generation", 4, false); assert.equal(wrapper.models.getModel("fictional", "model").id, "model"); unknown(await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options))); assert.equal(f.state.sends, 0); wrapper.close(); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});
test("old six-field factory stays hooks-free and refuses hidden seventh field", () => {
  const f = fixture(), { modelDispatch, ...old } = f.config; const wrapper = createDurableReadonlyRegistry(old); assert.equal(Object.hasOwn(wrapper.registry.snapshot().installed()[0], "hooks"), false); assert.throws(() => createDurableReadonlyRegistry(f.config), /readonly-unavailable/);
});
for (const mutation of [f => f.durable.GenerationTask = { ...f.builtin[0] }, f => f.durable.CompactionTask = f.builtin[0]]) test("generation/compaction must be original builtin tokens", () => { const f = fixture(); mutation(f); assert.throws(f.create, /readonly-unavailable/); });
for (const registration of [value => ({ ...value, handlers: { ...value.handlers } }), value => ({ ...value, task: "pi.tool" }), value => ({ ...value, extra: true })]) test("malformed hook return never installs partial composition", () => { const f = fixture({ registration }); assert.throws(f.create, /readonly-unavailable/); });
for (const stage of ["authorize", "prepare", "commitSending"]) for (const mutation of ["registry", "input", "store-method", "hook", "callback"]) test(`pending ${stage} whole source drift ${mutation} no underlying`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [stage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered);
  if (mutation === "registry") wrapper.registry.uninstall(); if (mutation === "input") f.config.modelDispatch = { ...f.modelDispatch }; if (mutation === "store-method") f.store.prepare = () => assert.fail("drift entered"); if (mutation === "hook") f.registrations[0].handlers = { ...f.registrations[0].handlers }; if (mutation === "callback") f.modelDispatch.authorize = () => assert.fail("drift entered");
  gate.resolve(); unknown(await pending); assert.equal(f.state.sends, 0); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});
test("new hook invalidates consumed original identity across authorize await", async () => {
  const gate = deferred(), f = fixture({ authorize: () => gate.promise }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick(); const hooks = wrapper.registry.snapshot().installed()[0].hooks[0].handlers; hooks.beforeRequest(undefined, scope.api, scope.context); gate.resolve(); unknown(await pending); assert.equal(f.state.sends, 0);
});
for (const stage of ["collector", "recordResult", "settle"]) test(`closed unchanged facts through ${stage} remain recorded without reopening output`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [stage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), scope = f.scope(wrapper), stream = wrapper.models.streamSimple(f.model, scope.prompt, scope.options), pending = collect(stream);
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered); wrapper.close(); unknown(await pending); gate.resolve(); for (let i = 0; i < 10 && f.state.rows.get("attempt-4").state !== "settled"; i++) await tick(); assert.equal(f.state.rows.get("attempt-4").state, "settled"); assert.equal(f.state.sends, 1); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});
for (const stage of ["collector", "recordResult", "settle"]) for (const mutation of ["modelDispatch", "collector", "store", "record-method", "settle-method"]) test(`closed late ${stage} facts source ${mutation} cannot continue via stable copy`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [stage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered); wrapper.close(); unknown(await pending);
  if (mutation === "modelDispatch") f.config.modelDispatch = { ...f.modelDispatch }; if (mutation === "collector") f.modelDispatch.resultFacts = () => assert.fail("drift entered"); if (mutation === "store") f.modelDispatch.store = { ...f.store }; if (mutation === "record-method") f.store.recordResult = () => assert.fail("drift entered"); if (mutation === "settle-method") f.store.settle = () => assert.fail("drift entered");
  gate.resolve(); await tick(); await tick(); assert.equal(f.state.sends, 1); const row = f.state.rows.get("attempt-4"); assert.equal(row.state, stage === "collector" ? "sending" : stage === "recordResult" ? "result-recorded" : "settled"); assert.equal(f.state.order.filter(value => value === "settle").length, stage === "settle" ? 1 : 0);
});

for (const stage of ["authorize", "prepare", "commitSending", "collector", "recordResult", "settle"]) test(`rejected await ${stage} still rechecks original config and fully closes`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [stage]: async () => { entered = true; await gate.promise; throw Error(secret); } }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered); f.config.modelDispatch = { ...f.modelDispatch }; gate.resolve(); unknown(await pending); await tick(); assert.throws(wrapper.check, /readonly-unavailable/); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});
test("close flags readonly and bridge before outer-error callback can reenter", async () => {
  const f = fixture({ authorize: () => gate.promise }), gate = deferred(); let wrapper, entered = false, reentered;
  const original = f.modelDispatch.ai;
  f.modelDispatch.ai = { createAssistantMessageEventStream() { const stream = original.createAssistantMessageEventStream(); const push = stream.push; stream.push = function(event) {
    if (event.type === "error" && !entered) {
      entered = true; assert.throws(wrapper.check, /readonly-unavailable/);
      const handler = wrapper.registry.snapshot().installed()[0].hooks[0].handlers; const fresh = f.scope(wrapper, "generation", 66, false);
      assert.throws(() => handler.beforeRequest(undefined, fresh.api, fresh.context), /hook-invalid/);
      reentered = collect(wrapper.models.streamSimple(f.model, fresh.prompt, fresh.options));
    }
    return push.call(this, event);
  }; return stream; } };
  wrapper = f.create(); const scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick(); wrapper.close(); unknown(await pending); unknown(await reentered); gate.resolve(); await tick(); assert.equal(f.state.sends, 0); wrapper.close();
});
test("source descriptors and namespace method drift cannot hide behind stable facades", async () => {
  for (const mutate of [f => Object.defineProperty(f.config, "modelDispatch", { get() { throw Error(secret); } }), f => Object.defineProperty(f.modelDispatch, "resultFacts", { get() { throw Error(secret); } }), f => f.durable.hook = () => assert.fail("changed hook entered"), f => f.durable.GenerationTask = { ...f.builtin[0] }]) {
    const f = fixture(), wrapper = f.create(), scope = f.scope(wrapper); mutate(f); unknown(await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options))); assert.equal(f.state.sends, 0); assert.throws(wrapper.check, /readonly-unavailable/);
  }
});
test("closed late facts do not require new current authorization or live registry/bridge", async () => {
  const gate = deferred(); let entered = false; const f = fixture({ collector: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  for (let i = 0; i < 10 && !entered; i++) await tick(); wrapper.close(); unknown(await pending); f.state.current = false; wrapper.registry.uninstall(); gate.resolve(); await tick(); await tick(); assert.equal(f.state.rows.get("attempt-4").state, "settled"); assert.equal(f.state.authorizes, 3); assert.equal(f.state.sends, 1);
});
test("old hook object or copied handlers cannot qualify another factory bridge", async () => {
  const f = fixture(), first = f.create(), second = f.create(), scope = f.scope(first, "generation", 4, false); const hooks = first.registry.snapshot().installed()[0].hooks[0].handlers;
  hooks.beforeRequest(undefined, scope.api, scope.context); unknown(await collect(second.models.streamSimple(f.model, scope.prompt, scope.options))); assert.equal(f.state.sends, 0);
});

for (const mutation of ["model", "limits", "models-method", "ai-method"]) test(`original provider configuration ${mutation} closes entire factory during authorize wait`, async () => {
  const gate = deferred(), f = fixture({ authorize: () => gate.promise }), wrapper = f.create(), scope = f.scope(wrapper), pending = collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options)); await tick();
  if (mutation === "model") f.model.maxTokens = 200; if (mutation === "limits") f.modelDispatch.limits.timeoutMs = 800;
  if (mutation === "models-method") f.models.streamSimple = () => assert.fail("changed Models method entered"); if (mutation === "ai-method") f.modelDispatch.ai = { ...f.modelDispatch.ai, createAssistantMessageEventStream: () => assert.fail("changed ai entered") };
  gate.resolve(); unknown(await pending); assert.throws(wrapper.check, /readonly-unavailable/); assert.equal(wrapper.models.getModel("fictional", "model"), undefined); assert.equal(f.state.sends, 0);
});
test("failed composition closes before exposing registry/model handles and does not freeze SDK hook returns", () => {
  const f = fixture(); f.modelDispatch.limits = { timeoutMs: 0, maxEvents: 1 }; assert.throws(f.create, /readonly-unavailable/); assert.equal(f.state.sends, 0); assert(f.registrations.every(value => !Object.isFrozen(value)));
});

for (const mutation of ["authorize", "streamSimple", "completeSimple", "store", "modelDispatch"]) test(`verifyCurrent synchronous ${mutation} swap after original provider config never enters old or new method`, async () => {
  const f = fixture(); let armed = false, newSends = 0;
  f.config.verifyCurrent = () => {
    if (armed) { armed = false;
      if (mutation === "authorize") f.modelDispatch.authorize = () => { newSends++; throw Error(secret); };
      if (mutation === "streamSimple") f.models.streamSimple = () => { newSends++; throw Error(secret); };
      if (mutation === "completeSimple") f.models.completeSimple = () => { newSends++; throw Error(secret); };
      if (mutation === "store") f.store.commitSending = () => { newSends++; throw Error(secret); };
      if (mutation === "modelDispatch") f.config.modelDispatch = { ...f.modelDispatch };
    }
    return true;
  };
  const wrapper = f.create(), scope = f.scope(wrapper); armed = true;
  unknown(await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options))); assert.equal(f.state.sends, 0); assert.equal(newSends, 0); assert.throws(wrapper.check, /readonly-unavailable/); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});

test("closed composition also seals original readonly tool before any API field or backend read", async () => {
  const f = fixture(), wrapper = f.create(), tool = wrapper.registry.snapshot().tools()[0].tool; wrapper.close(); let reads = 0;
  const api = { get taskId() { reads++; throw Error(secret); } };
  const result = await tool.execute({ rootRef: "synthetic", path: "doc" }, api, {});
  assert.deepEqual(result, { isError: true, content: [{ type: "text", text: "readonly-unavailable" }] }); assert.equal(reads, 0); assert.equal(f.state.sends, 0);
});


test("final snapshot callback root phase replacement invalidates bare check and fully closes", async () => {
  let armed = false, f;
  f = fixture({ snapshotTask(name) { if (armed && name === "rotom.durable.request") { armed = false; f.rootTask.definition.phases.fixture = () => {}; } } });
  const wrapper = f.create(); armed = true;
  assert.throws(wrapper.check, /readonly-unavailable/); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
  const tool = wrapper.registry.snapshot().tools()[0].tool; assert.equal((await tool.execute({ rootRef: "r", path: "p" }, {}, {})).isError, true);
});
for (const mutation of ["root-phase", "builtin-initial", "assistant-is", "defineTool", "control-prepare", "registry-subscribe", "snapshot-sections"]) test(`last original snapshot callback ${mutation} cannot authorize old/new send`, async () => {
  let f, wrapper, lookups = 0, swaps = 0, newSends = 0;
  f = fixture({ snapshotTask(name, snapshot) {
    if (name !== "rotom.durable.request" || f.state.authorizes !== 3) return;
    // 第三次：third authorize boundAwait后、provider gate alive、最后run alive各一轮。
    if (++lookups !== 3) return;
    swaps++;
    if (mutation === "root-phase") f.rootTask.definition.phases.fixture = () => { newSends++; };
    if (mutation === "builtin-initial") f.builtin[0].definition.initial = () => { newSends++; };
    if (mutation === "assistant-is") f.durable.AssistantEntry.is = () => { newSends++; };
    if (mutation === "defineTool") f.durable.defineTool = () => { newSends++; };
    if (mutation === "control-prepare") f.control.prepare = () => { newSends++; };
    if (mutation === "registry-subscribe") wrapper.registry.subscribe = () => { newSends++; };
    if (mutation === "snapshot-sections") snapshot.sections = () => { newSends++; return []; };
  } });
  wrapper = f.create(); const scope = f.scope(wrapper); const result = await collect(wrapper.models.streamSimple(f.model, scope.prompt, scope.options));
  assert.equal(swaps, 1); unknown(result); assert.equal(f.state.sends, 0); assert.equal(newSends, 0); assert.throws(wrapper.check, /readonly-unavailable/); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
  const tool = wrapper.registry.snapshot().tools()[0].tool; assert.equal((await tool.execute({ rootRef: "r", path: "p" }, {}, {})).isError, true);
});
