import assert from "node:assert/strict";
import test from "node:test";
import { createDurableReadonlyPhaseModelRegistry } from "../src/registry.ts";
import { factory as ai, rawStream, deferred } from "./provider-events.ts";
const SECRET = "SYNTHETIC_PRIVATE_PHASE_MODELS";
const tick = () => new Promise(resolve => setImmediate(resolve));
async function collect(stream) { const events = []; for await (const event of stream) events.push(event); return { events, message: await stream.result() }; }
function unknown(value) { assert.equal(value.message.stopReason, "error"); assert.equal(value.message.errorMessage, "dispatch-unknown"); assert.ok(!JSON.stringify(value).includes(SECRET)); }
function invalid(call) { assert.throws(call, /readonly-unavailable/); }
function fixture(hooks = {}) {
  const state = { order: [], rows: new Map(), sends: 0, commitBodies: 0, committedAcks: 0, authorizes: 0, collectors: 0, handlers: [], defined: [], hookCalls: 0, controlExecutes: 0, sdkReads: 0, entryReads: 0, disposals: 0, current: true, listeners: new Set(), nested: [] };
  const actual = { role: "assistant", content: [{ type: "text", text: "synthetic" }], api: "fixture-api", provider: "fictional", model: "model", usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: 1 };
  const model = { provider: "fictional", id: "model", api: "fixture-api", maxTokens: 100 };
  const handlers = {};
  function definition(kind) {
    const name = "pi." + kind, target = kind === "generation" ? "request" : "summarize";
    const phases = { async [target](task, runtime, context) {
      state.handlers.push({ kind, phase: target, receiver: this, args: [...arguments] }); assert.equal(this, phases);
      if (hooks.handler) return hooks.handler(kind, task, runtime, context);
      if (kind === "generation") return collect(runtime.models.streamSimple(model, { messages: [{ role: "user", content: "synthetic" }] }, { signal: runtime.signal, maxTokens: 20, maxRetries: 0, transport: "sse" }));
      return { message: await runtime.models.completeSimple(model, { messages: [] }, { signal: runtime.signal, maxTokens: 20, maxRetries: 0, transport: "sse" }) };
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

test("real selected phase stream/complete, raw receivers, true original sending body and no ctor authorize/hooks", async () => {
  const f = fixture(), wrapper = f.create(); assert.equal(f.state.authorizes, 0); assert.equal(f.state.hookCalls, 0); assert.equal(f.state.defined.length, 2);
  assert.deepEqual(Object.keys(wrapper).sort(), ["check", "close", "models", "registry"]); const front = wrapper.registry.snapshot(); assert.ok(Object.isFrozen(front)); assert.equal(wrapper.registry.install, undefined);
  assert.notEqual(front.task("pi.generation"), f.builtin[0]); assert.equal(front.task("pi.tool"), f.builtin[1]); assert.equal(front.task("rotom.durable.request"), f.rootTask);
  const s = f.scope(wrapper), result = await s.run(); assert.equal(result.message, f.actual); assert.deepEqual(f.state.order, ["prepare", "sending", "send", "collector", "record", "settle"]);
  assert.equal(f.state.authorizes, 3); assert.equal(f.state.commitBodies, 1); assert.equal(f.state.committedAcks, 1); assert.equal(f.state.sends, 1);
  assert.equal(f.state.handlers[0].receiver, f.handlers.generation); assert.deepEqual(f.state.handlers[0].args, [s.task, s.runtime, s.context]);
  f.grant({ attemptId: "explicit-grant-two", taskId: "explicit-compaction", phase: "compaction", nativeTaskId: 5, budget: { scopeId: "explicit-compaction-scope", maxCalls: 2, maxCostUnits: 20, reservationUnits: 10 } });
  const c = f.scope(wrapper, "compaction"); assert.equal((await c.run()).message, f.actual); assert.equal(f.state.sends, 2); assert.equal(f.state.commitBodies, 2);
});

test("actual outer front is tool API registry, original pi.tool/backend verify succeeds", async () => {
  const f = fixture(), wrapper = f.create(), front = wrapper.registry.snapshot(), call = f.toolCall(wrapper, front);
  assert.equal(call.api.registry, front); assert.notEqual(front, f.state.base.snapshot());
  assert.deepEqual(await call.run(), { content: [{ type: "text", text: "synthetic" }] }); assert.equal(f.state.controlExecutes, 1); assert.equal(f.state.sdkReads, 4);
  const wrong = f.toolCall(wrapper, f.state.base.snapshot()); assert.equal((await wrong.run()).isError, true); assert.equal(f.state.controlExecutes, 1);
});

test("same invocation sequential new record/explicit grant and new invocation are independent", async () => {
  const f = fixture(), wrapper = f.create(), first = f.scope(wrapper); await first.run();
  f.grant({ attemptId: "explicit-second" }); await f.scope(wrapper, "generation", 3, first).run(); assert.equal(f.state.sends, 2);
  f.grant({ attemptId: "explicit-third" }); await f.scope(wrapper).run(); assert.equal(f.state.sends, 3); assert.equal(f.state.commitBodies, 3);
});

test("same grant replay committed false and unknown row hold cannot cause paid second entry", async () => {
  const f = fixture(), wrapper = f.create(); await f.scope(wrapper).run(); unknown(await f.scope(wrapper).run()); assert.equal(f.state.commitBodies, 2); assert.equal(f.state.committedAcks, 1); assert.equal(f.state.sends, 1);
  const g = fixture({ sending: async () => { g.state.hold = true; throw Error("synthetic sending ack unknown"); } }), other = g.create(); unknown(await g.scope(other).run());
  assert.equal(g.state.rows.get("explicit-grant-one").state, "sending"); assert.equal(g.state.commitBodies, 1); assert.equal(g.state.sends, 0);
  g.grant({ attemptId: "explicit-another" }); unknown(await g.scope(other).run()); assert.equal(g.state.sends, 0); assert.equal(g.state.commitBodies, 1);
});

for (const stage of ["authorize", "prepare", "sending"]) for (const mutation of ["model", "store", "root", "sdk-method"]) test(`pending ${stage} source ${mutation} is zero original/new entry`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [stage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), pending = f.scope(wrapper).run();
  for (let i = 0; i < 20 && !entered; i++) await tick(); assert.equal(entered, true);
  if (mutation === "model") f.model.api = "changed";
  if (mutation === "store") f.store.commitSending = () => assert.fail("changed sending invoked");
  if (mutation === "root") f.rootTask.definition.phases.fake = () => undefined;
  if (mutation === "sdk-method") f.durable.defineTool = () => assert.fail("changed SDK invoked");
  gate.resolve(); unknown(await pending); assert.equal(f.state.sends, 0); invalid(wrapper.check); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});

for (const phaseStage of ["collector", "record", "settle"]) test(`closed unchanged ${phaseStage} actual late facts recorded without output reopening`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [phaseStage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), pending = f.scope(wrapper).run();
  for (let i = 0; i < 20 && !entered; i++) await tick(); assert.equal(entered, true); wrapper.close(); unknown(await pending); gate.resolve();
  for (let i = 0; i < 20 && f.state.rows.get("explicit-grant-one").state !== "settled"; i++) await tick();
  assert.equal(f.state.rows.get("explicit-grant-one").state, "settled"); assert.equal(f.state.sends, 1); assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});

for (const phaseStage of ["collector", "record", "settle"]) test(`closed ${phaseStage} replaced facts source cannot mutate through stable facade`, async () => {
  const gate = deferred(); let entered = false; const f = fixture({ [phaseStage]: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), pending = f.scope(wrapper).run();
  for (let i = 0; i < 20 && !entered; i++) await tick(); assert.equal(entered, true); wrapper.close(); unknown(await pending);
  f.config.modelDispatch = { ...f.modelDispatch }; gate.resolve(); for (let i = 0; i < 20; i++) await tick();
  assert.equal(f.state.rows.get("explicit-grant-one").state, phaseStage === "collector" ? "sending" : phaseStage === "record" ? "result-recorded" : "settled");
  assert.equal(f.state.order.filter(value => value === "settle").length, phaseStage === "settle" ? 1 : 0); assert.equal(f.state.sends, 1);
});

for (const during of ["defineTask", "readonly-final", "runtime-reader"]) test(`metadata callback ${during} cannot execute saved phase before published or during gates`, async () => {
  let f, wrapper, attempted = false;
  const attempt = () => {
    if (attempted || !f.state.defined[0]) return; attempted = true;
    const context = { abortSignal: new AbortController().signal }, task = { id: 3, conversationId: 9, kind: "pi.generation", version: 1, state: { status: "running", checkpoint: { phase: "request" } } }, runtime = { taskId: 3, conversationId: 9, signal: context.abortSignal, models: wrapper?.models };
    const pending = f.state.defined[0].phases.request(task, runtime, context); pending.catch(() => undefined); f.state.nested.push(pending);
  };
  f = fixture(during === "defineTask" ? { defineTask: attempt } : { table: (method, name) => { if (method === "task" && name === "rotom.durable.request" && (during === "readonly-final" || wrapper)) attempt(); } });
  if (during === "runtime-reader") { wrapper = f.create(); invalid(() => wrapper.registry.snapshot()); }
  else invalid(f.create);
  await Promise.allSettled(f.state.nested); assert.equal(attempted, true); assert.equal(f.state.handlers.length, 0); assert.equal(f.state.sends, 0); assert.equal(f.state.authorizes, 0);
});

for (const during of ["constructor", "running-reader"]) test(`metadata ${during} saved readonly tool cannot read API or execute`, async () => {
  let f, wrapper, savedTool, attempted = false;
  const call = () => {
    if (attempted || !savedTool) return; attempted = true;
    const pending = savedTool.execute({ rootRef: "fake", path: "file" }, { get taskId() { assert.fail("early API getter"); } }, {}); f.state.nested.push(pending);
  };
  f = fixture({ defineTool: value => { savedTool ??= value; }, table: (method, name) => { if (method === "task" && name === "rotom.durable.request" && (during === "constructor" || wrapper)) call(); } });
  if (during === "constructor") invalid(f.create); else { wrapper = f.create(); invalid(() => wrapper.registry.snapshot()); }
  const values = await Promise.all(f.state.nested); assert.equal(values.length, 1); assert.equal(values[0].isError, true); assert.equal(f.state.sdkReads, 0); assert.equal(f.state.controlExecutes, 0); assert.equal(f.state.sends, 0);
});

for (const mutation of ["authorize", "models", "commit", "collector"]) test(`last Context getter ${mutation} crosses original source before send`, async () => {
  let armed = false, f;
  f = fixture({ context: () => { if (!armed || f.state.authorizes !== 3) return; armed = false;
    if (mutation === "authorize") f.modelDispatch.authorize = () => assert.fail("new authorizer");
    if (mutation === "models") f.models.streamSimple = () => assert.fail("new model");
    if (mutation === "commit") f.store.commitSending = () => assert.fail("new sender");
    if (mutation === "collector") f.modelDispatch.resultFacts = () => assert.fail("new collector");
  } });
  const wrapper = f.create(); armed = true; unknown(await f.scope(wrapper).run()); assert.equal(f.state.sends, 0); assert.equal(armed, false); invalid(wrapper.check);
});

test("tool await must detect phase internally closed even with identical function refs", async () => {
  const gate = deferred(); let entered = false; const f = fixture({ getTask: async () => { entered = true; await gate.promise; } }), wrapper = f.create(), call = f.toolCall(wrapper), pending = call.run();
  for (let i = 0; i < 20 && !entered; i++) await tick(); assert.equal(entered, true);
  const phaseToken = wrapper.registry.snapshot().task("pi.generation"), bad = f.scope(wrapper); bad.runtime.taskId = 999;
  await assert.rejects(phaseToken.definition.phases.request(bad.task, bad.runtime, bad.context), /phase-unavailable/);
  gate.resolve(); assert.equal((await pending).isError, true); assert.equal(f.state.controlExecutes, 0); invalid(wrapper.check);
});

for (const failure of ["non-function", "inner-source", "outer-model", "outer-model-cleanup-throws"]) test(`outer subscribe ${failure} only cleans actual original disposer once`, () => {
  const f = fixture(), wrapper = f.create(); let armed = false;
  if (failure === "non-function") f.hooks.nonFunctionDisposer = true;
  if (failure === "inner-source") f.hooks.subscribe = () => { f.builtin[0].definition.phases.request = () => undefined; };
  if (failure.startsWith("outer-model")) {
    f.hooks.subscribe = () => { armed = true; };
    f.hooks.table = (method, name) => { if (armed && method === "task" && name === "rotom.durable.request") { armed = false; f.model.api = "changed"; } };
    if (failure.endsWith("throws")) f.hooks.disposerThrow = true;
  }
  invalid(() => wrapper.registry.subscribe(() => {}));
  assert.equal(f.state.disposals, failure === "non-function" ? 0 : 1); invalid(wrapper.check);
  assert.equal(wrapper.models.getModel("fictional", "model"), undefined);
});

test("original disposer returned unchanged and remains usable after full close", () => {
  const f = fixture(), wrapper = f.create(); let notified = 0; const listener = () => { notified++; };
  const disposer = wrapper.registry.subscribe(listener); assert.equal(disposer, f.state.lastDisposer); assert.equal(f.state.listeners.has(listener), true); wrapper.close(); assert.equal(notified, 0); disposer(); assert.equal(f.state.disposals, 1);
});

test("inner Reader reentry caught by caller still permanently closes whole factory", async () => {
  const f = fixture(), wrapper = f.create(); let armed = true;
  f.hooks.table = () => { if (armed) { armed = false; try { wrapper.registry.snapshot(); } catch {} } };
  invalid(() => wrapper.registry.snapshot()); const token = f.state.defined[0], bad = f.scope(wrapper); bad.runtime.models = wrapper.models;
  await assert.rejects(token.phases.request(bad.task, bad.runtime, bad.context), /phase-unavailable/); assert.equal(f.state.handlers.length, 0); assert.equal(f.state.sends, 0); invalid(wrapper.check);
});

test("initial/abort/migrate/non-target preserve receiver/result and original thrown handler error", async () => {
  const f = fixture({ handler: async () => { throw original; } }), original = Error(SECRET), wrapper = f.create(), front = wrapper.registry.snapshot(), token = front.task("pi.generation"), scope = f.scope(wrapper);
  const input = { synthetic: true }; assert.deepEqual(token.definition.initial(input), { phase: "request", input }); assert.equal(token.definition.abort(input, 2, 3), input); assert.equal(token.definition.migrate(input, 2, 3), input);
  scope.task.state.checkpoint.phase = "retry"; assert.equal(token.definition.phases.retry(scope.task, scope.runtime, scope.context), "retry"); scope.task.state.checkpoint.phase = "request";
  await assert.rejects(token.definition.phases.request(scope.task, scope.runtime, scope.context), error => error === original); assert.equal(wrapper.check(), true);
});

for (const mutation of ["input", "descriptor", "sdk-task", "root", "control", "models"]) test(`first foreign verifier cannot establish replacement ${mutation} baseline`, () => {
  let once = false, f; f = fixture({ verify: () => { if (once) return; once = true;
    if (mutation === "input") f.config.modelDispatch = { ...f.modelDispatch };
    if (mutation === "descriptor") Object.defineProperty(f.config, "rootTask", { enumerable: true, get() { assert.fail("new descriptor getter"); } });
    if (mutation === "sdk-task") f.builtin[0].definition.phases.request = () => undefined;
    if (mutation === "root") f.rootTask.definition.phases.fake = () => undefined;
    if (mutation === "control") f.control.execute = () => assert.fail("new control");
    if (mutation === "models") f.models.streamSimple = () => assert.fail("new model");
  } });
  invalid(f.create); assert.equal(f.state.authorizes, 0); assert.equal(f.state.handlers.length, 0); assert.equal(f.state.sends, 0);
});

test("cancel local phase/model call does not disable a different valid task", async () => {
  const gate = deferred(); let firstSignal;
  const f = fixture({ stream: (given, context, options) => rawStream([{ type: "done", reason: "stop", message: f.actual }], f.actual, options.signal === firstSignal ? { gate, resultGate: gate } : {}) }), wrapper = f.create(), first = f.scope(wrapper);
  firstSignal = first.controller.signal; const pending = first.run(); for (let i = 0; i < 20 && f.state.sends === 0; i++) await tick(); assert.equal(f.state.sends, 1);
  first.controller.abort(); unknown(await pending);
  f.grant({ attemptId: "explicit-second-task", taskId: "explicit-compaction", phase: "compaction", nativeTaskId: 5, budget: { scopeId: "explicit-other-scope", maxCalls: 2, maxCostUnits: 20, reservationUnits: 10 } });
  assert.equal((await f.scope(wrapper, "compaction").run()).message, f.actual); assert.equal(f.state.sends, 2); assert.equal(wrapper.check(), true);
  gate.resolve(); for (let i = 0; i < 10; i++) await tick();
});

test("no active phase and stale callback only reject call, do not mint phase permission", async () => {
  const f = fixture(), wrapper = f.create(), signal = new AbortController().signal;
  unknown(await collect(wrapper.models.streamSimple(f.model, { messages: [] }, { signal, maxTokens: 20, maxRetries: 0, transport: "sse" })));
  assert.equal(f.state.sends, 0); assert.equal(wrapper.check(), true); assert.equal((await f.scope(wrapper).run()).message, f.actual);
});

test("metadata check phase window is not a permission for direct nested handler", async () => {
  let armed = false, once = false, f, wrapper;
  f = fixture({ verify: () => {
    if (!armed || once) return; once = true;
    const s = f.scope(wrapper), pending = f.state.defined[0].phases.request(s.task, s.runtime, s.context); pending.catch(() => undefined); f.state.nested.push(pending);
  } });
  wrapper = f.create(); armed = true; invalid(wrapper.check); await Promise.allSettled(f.state.nested);
  assert.equal(f.state.handlers.length, 0); assert.equal(f.state.sends, 0); assert.equal(f.state.authorizes, 0); invalid(wrapper.check);
});

test("closed callback publication cannot reenter new Models or tool work", async () => {
  const gate = deferred(), f = fixture({ authorize: () => gate.promise }), wrapper = f.create(), call = f.toolCall(wrapper), pending = f.scope(wrapper).run(); await tick();
  wrapper.close(); unknown(await pending); assert.equal((await call.run()).isError, true); assert.equal(f.state.sdkReads, 0); assert.equal(f.state.controlExecutes, 0);
  const signal = new AbortController().signal; unknown(await collect(wrapper.models.streamSimple(f.model, { messages: [] }, { signal, maxTokens: 20, maxRetries: 0, transport: "sse" })));
  gate.resolve(); await tick(); assert.equal(f.state.sends, 0);
});

test("new private forwarding ignores function own call/apply accessors", async () => {
  const f = fixture(); let reads = 0;
  for (const fn of [f.config.verifyCurrent, f.modelDispatch.authorize, f.modelDispatch.resultFacts, f.store.prepare, f.store.commitSending, f.store.recordResult, f.store.settle]) {
    Object.defineProperty(fn, "call", { get() { reads++; throw Error(SECRET); } }); Object.defineProperty(fn, "apply", { get() { reads++; throw Error(SECRET); } });
  }
  const wrapper = f.create(); assert.equal((await f.scope(wrapper).run()).message, f.actual); assert.equal(reads, 0); assert.equal(f.state.commitBodies, 1); assert.equal(f.state.sends, 1);
});

test("ordinary original permit Promise safely rejects; then getter and secret are not leaked", async () => {
  const f = fixture(); const rejected = Promise.reject(Error(SECRET)); let reads = 0;
  Object.defineProperty(rejected, "then", { get() { reads++; throw Error(SECRET); } }); f.config.verifyCurrent = function() { assert.equal(this, f.config); return rejected; };
  invalid(f.create); await tick(); assert.equal(reads, 0); assert.equal(f.state.authorizes, 0); assert.equal(f.state.sends, 0);
});

for (const cut of ["initial", "guard", "post-getTask"]) test(`tool Context ${cut} getter cannot enter saved original phase`, async () => {
  const f = fixture({ handler: async () => undefined }), wrapper = f.create(), phase = f.scope(wrapper);
  const saved = wrapper.registry.snapshot().task("pi.generation").definition.phases.request;
  const call = f.toolCall(wrapper); let reads = 0, fired = false, readsAtCut;
  Object.defineProperty(call.context, "abortSignal", { get() {
    reads++;
    if (!fired && (cut === "initial" ? reads === 1 : cut === "guard" ? reads === 2 : f.state.sdkReads === 1)) {
      fired = true; readsAtCut = f.state.sdkReads;
      const pending = saved(phase.task, phase.runtime, phase.context); pending.catch(() => undefined); f.state.nested.push(pending);
    }
    return call.controller.signal;
  } });
  const result = await call.run(); await Promise.allSettled(f.state.nested);
  assert.equal(fired, true); assert.equal(f.state.handlers.length, 0);
  assert.equal(readsAtCut, cut === "post-getTask" ? 1 : 0);
  assert.equal(result.isError, true); assert.equal(f.state.sdkReads, readsAtCut);
  assert.equal(f.state.sends, 0); assert.equal(f.state.authorizes, 0); assert.equal(f.state.controlExecutes, 0); invalid(wrapper.check);
});

test("initial tool Context getter cannot enter pre-saved tool", async () => {
  const f = fixture(), wrapper = f.create(), call = f.toolCall(wrapper), nested = f.toolCall(wrapper);
  const saved = wrapper.registry.snapshot().tools()[0].tool.execute; let once = false, nestedReads = 0;
  const original = nested.api.getTask; nested.api.getTask = function(...args) { nestedReads++; return Reflect.apply(original, this, args); };
  Object.defineProperty(call.context, "abortSignal", { get() {
    if (!once) { once = true; const pending = saved(nested.args, nested.api, nested.context); pending.catch(() => undefined); f.state.nested.push(pending); }
    return call.controller.signal;
  } });
  const result = await call.run(); await Promise.allSettled(f.state.nested);
  assert.equal(nestedReads, 0); assert.equal(f.state.sdkReads, 0); assert.equal(f.state.entryReads, 0); assert.equal(f.state.controlExecutes, 0);
  assert.equal(result.isError, true); invalid(wrapper.check);
});

test("ordinary tool getter preserves raw signal and reads once at initial cut", async () => {
  const f = fixture(), wrapper = f.create(), call = f.toolCall(wrapper); let reads = 0, firstReadAtSDK;
  Object.defineProperty(call.context, "abortSignal", { get() { reads++; if (reads === 1) firstReadAtSDK = f.state.sdkReads; return call.controller.signal; } });
  const original = call.api.getTask; call.api.getTask = function(...args) { if (f.state.sdkReads === 0) assert.equal(reads, 2); return Reflect.apply(original, this, args); };
  assert.deepEqual(await call.run(), { content: [{ type: "text", text: "synthetic" }] });
  assert.equal(firstReadAtSDK, 0); assert.equal(f.state.controlExecutes, 1); assert.equal(wrapper.check(), true);
});

for (const mode of ["throw", "source-drift"]) test(`tool getter ${mode} closes factory and exits reading window`, async () => {
  const f = fixture(), wrapper = f.create(), call = f.toolCall(wrapper);
  Object.defineProperty(call.context, "abortSignal", { get() {
    if (mode === "throw") throw Error(SECRET);
    f.models.streamSimple = () => assert.fail("replacement send"); return call.controller.signal;
  } });
  const result = await call.run(); assert.equal(result.isError, true); assert.ok(!JSON.stringify(result).includes(SECRET));
  assert.equal(f.state.sdkReads, 0); assert.equal(f.state.controlExecutes, 0); invalid(wrapper.check);
  const phase = f.scope(wrapper); await assert.rejects(f.state.defined[0].phases.request(phase.task, phase.runtime, phase.context), /phase-unavailable/);
  assert.equal(f.state.handlers.length, 0);
});

test("already aborted native tool getter rejects locally while other valid phase remains usable", async () => {
  const f = fixture(), wrapper = f.create(), call = f.toolCall(wrapper); call.controller.abort(); let reads = 0;
  Object.defineProperty(call.context, "abortSignal", { get() { reads++; return call.controller.signal; } });
  assert.equal((await call.run()).isError, true); assert.equal(reads, 1); assert.equal(f.state.sdkReads, 0); assert.equal(wrapper.check(), true);
  assert.equal((await f.scope(wrapper).run()).message, f.actual); assert.equal(f.state.sends, 1);
});
