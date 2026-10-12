import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableReadonlyRegistry } from "../src/registry.ts";

const secret = "SECRET backend/auth/context/message/path";
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const errorResult = result => { assert.deepEqual(result, { isError: true, content: [{ type: "text", text: "readonly-unavailable" }] }); assert(!JSON.stringify(result).includes(secret)); assert(Object.isFrozen(result)); };
function fixture(hooks = {}) {
  const builtin = ["pi.generation", "pi.tool", "pi.compaction"].map(name => ({ definition: { name, version: 1, initial() { return { phase: "fake" }; }, phases: { fake: () => {} } } }));
  const rootTask = { definition: { name: "rotom.durable.request", version: 1, initial: () => ({ phase: "fake" }), phases: { fake: () => {} } } };
  class Snapshot {
    constructor(installed) { this.extensions = installed; this.allTasks = [...builtin, ...installed.flatMap(extension => extension.tasks ?? [])]; }
    installed() { return this.extensions; }
    tools() { return this.extensions.flatMap(extension => extension.tools.map(tool => ({ extension, tool }))); }
    tasks() { return [...this.allTasks]; }
    extension(name) { return this.extensions.find(extension => extension.name === name); }
    task(name) { return this.allTasks.find(task => task.definition.name === name); }
    sections() { return []; }
  }
  class Registry {
    constructor() { this.current = new Snapshot([]); this.installs = 0; }
    snapshot() { return this.current; }
    install(extension) { this.installs++; this.current = new Snapshot([...this.current.extensions.filter(value => value.name !== extension.name), extension]); }
    uninstall(extension) { this.current = new Snapshot(this.current.extensions.filter(value => value.name !== extension.name)); }
    subscribe() { return () => {}; }
  }
  let registry;
  const durable = { AssistantEntry: { kind: "pi.assistant", is: value => value.kind === "pi.assistant" },
    createRegistry() { assert.equal(this, durable); registry = new Registry(); if (hooks.initialRegistry) hooks.initialRegistry(registry); return registry; },
    defineTool(value) { assert.equal(this, durable); return value; }, defineExtension(value) { assert.equal(this, durable); return value; } };
  const state = { callbackPromises: [], callbackInvokers: [], current: true, prepares: 0, checks: 0, executes: 0, invocations: [], signals: [], tickets: [], sdkReads: [], entryReads: 0, writes: 0 };
  const control = {
    async prepare(invocation) { assert.equal(this, control); state.prepares++; state.invocations.push(invocation); const ticket = hooks.ticket ?? {}; state.tickets.push(ticket); if (hooks.prepare) await hooks.prepare(invocation); return ticket; },
    check(ticket, invocation) { assert.equal(this, control); state.checks++; assert(state.tickets.includes(ticket)); assert.equal(invocation, state.invocations.find(value => value === invocation)); return hooks.check ? hooks.check(ticket, invocation, state.checks) : true; },
    async execute(ticket, invocation, signal) { assert.equal(this, control); state.executes++; state.signals.push(signal); assert.equal(ticket, state.tickets.find(value => value === ticket)); if (hooks.execute) return hooks.execute(ticket, invocation, signal); return { text: "Synthetic bounded result" }; },
  };
  const config = { durable, rootTask, control, verifyCurrent: () => state.current, sourceIdentity: "a".repeat(64), registryIdentity: "b".repeat(64) };
  const factory = createDurableReadonlyRegistry(config);
  function invocation(operation = "rotom_read", id = 4) {
    const parameters = operation === "rotom_read" ? { rootRef: "synthetic-root", path: "docs/file.txt" } : { rootRef: "synthetic-root", path: ".", query: "literal * [ text" };
    const controller = new AbortController(), context = { get abortSignal() { return controller.signal; }, secret };
    const toolTask = { id, kind: "pi.tool", version: 1, conversationId: 9, owner: 3, background: false, abortRequested: false, input: { assistant: 2, callId: "call-1" }, state: { status: "running", checkpoint: { phase: "execute", arguments: structuredClone(parameters), replay: "unsafe" } } };
    const generation = { id: 3, kind: "pi.generation", version: 1, conversationId: 9, background: false, abortRequested: false, state: { status: "running", checkpoint: { synthetic: true } }, input: {} };
    const entry = { id: 2, conversationId: 9, kind: "pi.assistant", byTaskId: 3, model: [{ role: "assistant", api: "fictional", provider: "fictional", model: "fictional", usage: { secret }, stopReason: "toolUse", timestamp: 1,
      content: [{ type: "text", text: secret }, { type: "thinking", thinking: secret }, { type: "toolCall", id: "call-1", name: operation, arguments: structuredClone(parameters) }] }] };
    const api = { taskId: id, conversationId: 9, callId: "call-1", registry: registry.snapshot(), broadSecret: secret,
      async getTask(requested, ctx) { assert.equal(this, api); assert.equal(ctx, context); state.sdkReads.push(requested); if (hooks.getTask) await hooks.getTask(requested, state.sdkReads.length); return requested === id ? toolTask : generation; },
      async commit(callback, ctx) { assert.equal(this, api); assert.equal(ctx, context); if (hooks.skipCallback) return {}; const tx = { async entry(token, requested) { assert.equal(this, tx); assert.equal(token, durable.AssistantEntry); assert.equal(requested, 2); state.entryReads++; if (hooks.entry) await hooks.entry(); return entry; }, createTask() { state.writes++; assert.fail("table write"); } };
        state.callbackInvokers.push(() => callback(tx));
        if (hooks.commitMode === "sync-reject") throw Error(secret);
        if (["early", "async-reject"].includes(hooks.commitMode)) { const pending = callback(tx); pending.catch(() => {}); state.callbackPromises.push(pending); if (hooks.commitMode === "async-reject") throw Error(secret); return {}; }
        const result = await callback(tx); if (hooks.commitMode === "repeat") return callback(tx);
        if (hooks.commit) await hooks.commit(); return hooks.replaceReceipt ? {} : hooks.skipCallback ? undefined : result; },
    };
    const tool = registry.snapshot().tools().find(value => value.tool.name === operation).tool;
    return { parameters, controller, context, toolTask, generation, entry, api, tool, run: () => tool.execute(parameters, api, context) };
  }
  return { builtin, rootTask, durable, control, state, config, factory, registry, invocation };
}

test("exact builtin3+original root, two unsafe schemas, one extension; SDK values remain mutable", async () => {
  const f = fixture(), call = f.invocation(); assert(Object.isFrozen(f.factory)); assert.equal(f.factory.check(), true);
  const snapshot = f.registry.snapshot(); assert.deepEqual(snapshot.tasks().map(value => value.definition.name), ["pi.generation", "pi.tool", "pi.compaction", "rotom.durable.request"]);
  assert.equal(snapshot.installed().length, 1); assert.equal(f.registry.installs, 1); assert.deepEqual(snapshot.tools().map(value => value.tool.name), ["rotom_read", "rotom_search"]);
  assert(!Object.isFrozen(snapshot)); assert(!Object.isFrozen(f.rootTask)); assert(!Object.isFrozen(f.rootTask.definition)); assert(!Object.isFrozen(f.builtin[0]));
  for (const { tool } of snapshot.tools()) { assert.equal(tool.replay, "unsafe"); assert.equal(tool.prepareArguments, undefined); assert.equal(tool.parameters.type, "object"); assert.equal(tool.parameters.additionalProperties, false); assert(Object.isFrozen(tool.parameters)); assert(Object.isFrozen(tool.parameters.properties)); }
  const result = await call.run(); assert.deepEqual(result, { content: [{ type: "text", text: "Synthetic bounded result" }] }); assert(Object.isFrozen(result.content[0]));
  assert.deepEqual(f.state.sdkReads, [4, 3, 4, 3]); assert.equal(f.state.entryReads, 1); assert.equal(f.state.writes, 0); assert.equal(f.state.executes, 1);
  const metadata = f.state.invocations[0]; assert.deepEqual(Object.keys(metadata).sort(), ["schema", "operation", "parameters", "sourceIdentity", "registryIdentity", "nativeToolTaskId", "nativeGenerationTaskId", "nativeConversationId", "nativeAssistantEntryId", "nativeCallId"].sort());
  assert(Object.isFrozen(metadata) && Object.isFrozen(metadata.parameters)); assert.equal(metadata.operation, "rotom_read"); assert.equal(f.state.signals[0], call.controller.signal); assert(!JSON.stringify(metadata).includes(secret)); assert(!Object.isFrozen(call.parameters)); assert(!Object.isFrozen(call.entry));
});
test("search accepts literal query and authorized-root dot shape without interpreting it", async () => {
  const f = fixture(), call = f.invocation("rotom_search"); assert.equal((await call.run()).isError, undefined); assert.equal(f.state.invocations[0].parameters.query, "literal * [ text");
});
for (const mutate of [f => f.registry.install({ name: "other", tools: [f.registry.snapshot().tools()[0].tool], tasks: [] }), f => f.registry.snapshot().extensions.push({ name: "extra", tools: [], tasks: [] }), f => f.registry.snapshot().allTasks.pop(), f => f.builtin[0].definition.initial = () => {}, f => f.rootTask.definition.phases.fake = () => {}, f => f.durable.AssistantEntry.kind = "other", f => f.durable.defineTool = () => {}, f => f.control.execute = () => {}, f => f.control.extra = true]) test(`source/full snapshot drift closes factory ${mutate.toString()}`, async () => {
  const f = fixture(), call = f.invocation(); mutate(f); assert.throws(f.factory.check, /readonly-unavailable/); errorResult(await call.run()); assert.equal(f.state.executes, 0);
});
for (const mutate of [value => value.path = "/absolute", value => value.path = "../escape", value => value.path = "a//b", value => value.path = "a\\b", value => value.path = ".", value => value.path = "a/./b", value => value.path = "x\u200b", value => value.path = "\ud800", value => value.path = "x".repeat(4097), value => value.rootRef = "/root", value => value.rootRef = 2, value => value.extra = secret]) test(`closed parameters reject ${mutate.toString()}`, async () => {
  const f = fixture(), call = f.invocation(); mutate(call.parameters); errorResult(await call.run()); assert.equal(f.state.prepares, 0); assert.equal(f.state.executes, 0);
});
for (const query of ["", "a\nb", "a\0b", "a\u200bb", "x".repeat(4097), 5]) test(`search invalid literal query ${typeof query}:${JSON.stringify(query).slice(0, 10)}`, async () => {
  const f = fixture(), call = f.invocation("rotom_search"); call.parameters.query = query; errorResult(await call.run()); assert.equal(f.state.executes, 0);
});
for (const selected of ["raw", "intent", "final"]) test(`raw/intent/final full value disagreement ${selected}`, async () => {
  const f = fixture(), call = f.invocation(); const args = selected === "raw" ? call.entry.model[0].content[2].arguments : selected === "intent" ? call.toolTask.state.checkpoint.arguments : call.parameters;
  args.path = "different"; errorResult(await call.run()); assert.equal(f.state.executes, 0);
});
for (const change of [c => c.toolTask.owner = 99, c => c.toolTask.state.status = "pending", c => c.toolTask.state.checkpoint.replay = "safe", c => c.toolTask.input.extra = true, c => c.toolTask.abortRequested = true, c => c.generation.state.status = "completing", c => c.generation.abortRequested = true, c => c.generation.conversationId = 10, c => c.entry.byTaskId = 99, c => c.entry.kind = "pi.user", c => c.entry.model[0].role = "user", c => c.entry.model[0].content.pop(), c => c.entry.model[0].content.push(structuredClone(c.entry.model[0].content[2])), c => c.entry.model[0].content[2].name = "other", c => c.entry.model[0].content[2].namespace = "unsupported", c => c.entry.extra = true, c => c.entry.model[0].extra = true]) test(`public record/ancestor/call mismatch ${change.toString()}`, async () => {
  const f = fixture(), call = f.invocation(); change(call); errorResult(await call.run()); assert.equal(f.state.executes, 0);
});
test("legitimate public metadata/signatures stay in SDK record and never flow to control", async () => {
  const f = fixture(), call = f.invocation(); Object.assign(call.entry, { data: { secret }, head: 1, edits: [] }); Object.assign(call.entry.model[0], { responseModel: secret, responseId: secret, providerThinkingLevel: secret, thinkingLevel: secret, diagnostics: [{ secret }], deferred: { secret }, errorMessage: secret, rawStopReason: secret, endTurn: false });
  call.entry.model[0].content[2].thoughtSignature = secret; assert.equal((await call.run()).isError, undefined); assert(!JSON.stringify(f.state.invocations).includes(secret));
});
for (const where of ["parameters", "api", "context", "toolTask", "entry", "message", "call"]) test(`proxy ${where} zero backend`, async () => {
  const f = fixture(), call = f.invocation(); const proxy = value => new Proxy(value, { get() { throw Error(secret); } });
  if (where === "parameters") call.parameters.path = proxy({});
  if (where === "api" || where === "context") { errorResult(await call.tool.execute(call.parameters, where === "api" ? proxy(call.api) : call.api, where === "context" ? proxy(call.context) : call.context)); }
  else { if (where === "toolTask") call.toolTask.input = proxy(call.toolTask.input); if (where === "entry") call.entry.model = proxy(call.entry.model); if (where === "message") call.entry.model[0] = proxy(call.entry.model[0]); if (where === "call") call.entry.model[0].content[2] = proxy(call.entry.model[0].content[2]); errorResult(await call.run()); }
  assert.equal(f.state.executes, 0);
});
test("getter and prototype fields never complete required arguments or expose exception", async () => {
  let reads = 0; const f = fixture(), call = f.invocation(); Object.defineProperty(call.entry.model[0], "usage", { enumerable: true, get() { reads++; throw Error(secret); } }); errorResult(await call.run()); assert.equal(reads, 0);
  const c = f.invocation(); Object.defineProperty(c.parameters, "path", { enumerable: true, get() { reads++; throw Error(secret); } }); errorResult(await c.run()); assert.equal(reads, 0); assert.equal(f.state.executes, 0);
});
for (const signal of [{ aborted: false }, Object.create(AbortSignal.prototype), new Proxy(new AbortController().signal, {})]) test("fake/proxy signal brand cannot authorize", async () => {
  const f = fixture(), call = f.invocation(); errorResult(await call.tool.execute(call.parameters, call.api, { abortSignal: signal })); assert.equal(f.state.executes, 0);
});
test("aborted native signal and closed factory zero dispatch", async () => {
  const f = fixture(), c = f.invocation(); c.controller.abort(); errorResult(await c.run()); f.factory.close(); errorResult(await f.invocation().run()); assert.equal(f.state.executes, 0);
});
for (const stage of ["getTask", "entry", "commit", "prepare", "execute"]) for (const mutation of ["close", "abort", "parameters", "source", "api", "record"]) test(`await ${stage} rechecks ${mutation}`, async () => {
  const gate = deferred(); let entered = false; const hooks = { [stage]: async () => { entered = true; await gate.promise; } }; const f = fixture(hooks), call = f.invocation(), pending = call.run();
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered);
  if (mutation === "close") f.factory.close(); if (mutation === "abort") call.controller.abort(); if (mutation === "parameters") call.parameters.path = "changed"; if (mutation === "source") f.config.sourceIdentity = "c".repeat(64); if (mutation === "api") call.api.callId = "changed"; if (mutation === "record") call.toolTask.state.checkpoint.arguments.path = "changed";
  gate.resolve(); errorResult(await pending); assert.equal(f.state.executes, stage === "execute" ? 1 : 0);
});
test("control exact true, opaque ticket, once-only concurrent ticket and lost result remain spent", async () => {
  const ticket = {}, f = fixture({ ticket }); const first = f.invocation(), second = f.invocation(); const results = await Promise.all([first.run(), second.run()]); assert.equal(f.state.executes, 1); assert.equal(results.filter(value => value.isError).length, 1);
  const denied = fixture({ check: () => Promise.resolve(true) }); errorResult(await denied.invocation().run()); assert.equal(denied.state.executes, 0);
  const missing = fixture({ ticket: new Proxy({}, {}) }); errorResult(await missing.invocation().run()); assert.equal(missing.state.executes, 0);
  const lost = fixture({ ticket: {}, execute: () => { throw Error(secret); } }); errorResult(await lost.invocation().run()); errorResult(await lost.invocation().run()); assert.equal(lost.state.executes, 1);
});
for (const value of [{ text: secret, extra: true }, { text: "x".repeat(256 * 1024 + 1) }, { text: "\ud800" }, { text: "a\0b" }, { text: 1 }]) test("closed bounded result rejects without leaking", async () => {
  const f = fixture({ execute: () => value }); errorResult(await f.invocation().run()); assert.equal(f.state.executes, 1);
});
test("method/control drift during prepare permanently closes and blocks other pending calls", async () => {
  const gate = deferred(), f = fixture({ prepare: () => gate.promise }), c = f.invocation(), pending = c.run(); await tick(); f.control.execute = () => assert.fail("drift entered"); gate.resolve(); errorResult(await pending); errorResult(await f.invocation().run()); assert.equal(f.state.executes, 0);
});
test("readonly callback receipt must be original and cannot be replaced", async () => {
  const f = fixture({ replaceReceipt: true }); errorResult(await f.invocation().run()); assert.equal(f.state.executes, 0);
});

for (const stage of ["getTask", "entry", "commit", "prepare", "execute"]) test(`rejected await ${stage} still checks changed global source and permanently closes`, async () => {
  const gate = deferred(); let entered = false;
  const f = fixture({ [stage]: async () => { entered = true; await gate.promise; throw Error(secret); } }), call = f.invocation(), pending = call.run();
  for (let i = 0; i < 10 && !entered; i++) await tick(); assert(entered);
  f.config.sourceIdentity = "c".repeat(64); gate.resolve(); errorResult(await pending); f.config.sourceIdentity = "a".repeat(64);
  assert.throws(f.factory.check, /readonly-unavailable/); errorResult(await f.invocation().run()); assert.equal(f.state.executes, stage === "execute" ? 1 : 0);
});
test("initial current false/promise, malformed control/source, extra builtin and define replacement reject", () => {
  for (const hooks of [{ initialRegistry(registry) { registry.current.allTasks.push({ definition: { name: "extra", version: 1 } }); } }]) assert.throws(() => fixture(hooks), /readonly-unavailable/);
  const f = fixture(); for (const value of [() => false, () => Promise.resolve(true), () => { throw Error(secret); }]) assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: value }), /readonly-unavailable/);
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, control: { ...f.control, extra: true } }), /readonly-unavailable/);
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, sourceIdentity: "not-hash" }), /readonly-unavailable/);
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, durable: { ...f.durable, defineTool: value => ({ ...value }) } }), /readonly-unavailable/);
});
test("read callback not invoked cannot qualify and actual commit has zero writes", async () => {
  const f = fixture({ skipCallback: true }); errorResult(await f.invocation().run()); assert.equal(f.state.entryReads, 0); assert.equal(f.state.executes, 0); assert.equal(f.state.writes, 0);
});
test("unselected call arguments are not traversed but duplicate same call never qualifies", async () => {
  const f = fixture(), call = f.invocation(); let reads = 0;
  call.entry.model[0].content.push({ type: "toolCall", id: "other", name: "unrelated", arguments: new Proxy({}, { ownKeys() { reads++; throw Error(secret); } }) });
  assert.equal((await call.run()).isError, undefined); assert.equal(reads, 0);
});
test("namespace even undefined and accessor ignored metadata reject without execution", async () => {
  for (const kind of ["namespace", "signature", "entry-data", "text-getter"]) {
    const f = fixture(), call = f.invocation(); let reads = 0;
    if (kind === "namespace") call.entry.model[0].content[2].namespace = undefined;
    if (kind === "signature") call.entry.model[0].content[2].thoughtSignature = "x".repeat(256 * 1024 + 1);
    if (kind === "entry-data") Object.defineProperty(call.entry, "data", { enumerable: true, get() { reads++; throw Error(secret); } });
    if (kind === "text-getter") Object.defineProperty(call.entry.model[0].content[0], "text", { enumerable: true, get() { reads++; throw Error(secret); } });
    errorResult(await call.run()); assert.equal(reads, 0); assert.equal(f.state.executes, 0);
  }
});
test("context signal getter changes, shared Entry changes and second Task query drift refuse", async () => {
  const f = fixture(), call = f.invocation(), other = new AbortController(); let seen = 0;
  const context = { get abortSignal() { return seen++ < 2 ? call.controller.signal : other.signal; } };
  // 自有api精确固定Context receiver替身，不触碰SDK。
  const api = { ...call.api, getTask: async id => id === 4 ? call.toolTask : call.generation, commit: () => assert.fail("must not reach entry") };
  errorResult(await call.tool.execute(call.parameters, api, context)); assert.equal(f.state.executes, 0);
  const gate = deferred(), g = fixture({ prepare: () => gate.promise }), c = g.invocation(), pending = c.run(); await tick(); c.entry.model[0].content[2].arguments.path = "after-await"; gate.resolve(); errorResult(await pending); assert.equal(g.state.executes, 0);
});
test("native task ids and call label caps are independent of control authorization", async () => {
  for (const mutation of [c => c.api.taskId = true, c => c.api.taskId = 2**60, c => c.api.conversationId = 0, c => c.api.callId = "x".repeat(201), c => c.api.callId = "x\u200b"]) {
    const f = fixture(), call = f.invocation(); mutation(call); errorResult(await call.run()); assert.equal(f.state.prepares, 0);
  }
});

test("configuration identities reject native nonstrings without implicit coercion", () => {
  const f = fixture(); let conversions = 0;
  const identity = { [Symbol.toPrimitive]() { conversions++; return "a".repeat(64); } };
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, sourceIdentity: identity }), /readonly-unavailable/);
  assert.equal(conversions, 0);
});

test("SDK number-to-string normalization cannot qualify final strings against original call", async () => {
  const f = fixture(), call = f.invocation(); call.parameters.rootRef = "42"; call.toolTask.state.checkpoint.arguments.rootRef = "42"; call.entry.model[0].content[2].arguments.rootRef = 42;
  errorResult(await call.run()); assert.equal(f.state.prepares, 0); assert.equal(f.state.executes, 0);
});
test("transparent/revoked business Proxy and inherited parameters reject before any trap/control", async () => {
  const f = fixture(), call = f.invocation(); let traps = 0;
  const proxy = new Proxy(call.parameters, { ownKeys() { traps++; throw Error(secret); }, get() { traps++; throw Error(secret); } });
  errorResult(await call.tool.execute(proxy, call.api, call.context));
  const revoked = Proxy.revocable(call.parameters, {}); revoked.revoke(); errorResult(await call.tool.execute(revoked.proxy, call.api, call.context));
  errorResult(await call.tool.execute(Object.create(call.parameters), call.api, call.context)); assert.equal(traps, 0); assert.equal(f.state.prepares, 0);
});

test("shared original ticket across factory instances admits exactly one execution", async () => {
  const ticket = {}, f = fixture({ ticket }), first = f.invocation(); const secondFactory = createDurableReadonlyRegistry(f.config), second = f.invocation();
  const results = await Promise.all([first.run(), second.run()]); assert.equal(f.state.executes, 1); assert.equal(results.filter(value => value.isError).length, 1); secondFactory.close(); f.factory.close();
});
test("close/new control cannot reuse spent ticket, independent new ticket remains usable", async () => {
  const ticket = {}, first = fixture({ ticket }); assert.equal((await first.invocation().run()).isError, undefined); first.factory.close();
  const next = fixture({ ticket }); errorResult(await next.invocation().run()); assert.equal(next.state.executes, 0);
  const independent = fixture({ ticket: {} }); assert.equal((await independent.invocation().run()).isError, undefined); assert.equal(independent.state.executes, 1);
});

for (const phase of [1, 2]) for (const mutation of ["close", "abort", "source", "args", "execute-method", "api-method"]) test(`control.check callback phase${phase} ${mutation} cannot dispatch/publish`, async () => {
  let f, call;
  f = fixture({ check(_ticket, _invocation, count) {
    if (count === phase) {
      if (mutation === "close") f.factory.close(); if (mutation === "abort") call.controller.abort(); if (mutation === "source") f.config.sourceIdentity = "c".repeat(64);
      if (mutation === "args") call.parameters.path = "changed"; if (mutation === "execute-method") f.control.execute = () => assert.fail("drift entered"); if (mutation === "api-method") call.api.getTask = () => assert.fail("drift entered");
    }
    return true;
  } }); call = f.invocation(); errorResult(await call.run()); assert.equal(f.state.executes, phase === 1 ? 0 : 1);
});
for (const phase of [1, 2]) test(`Context getter closing after control.check phase${phase} refuses dispatch/publish`, async () => {
  let f, call, armed = false;
  f = fixture({ check(_ticket, _invocation, count) { if (count === phase) armed = true; return true; } }); call = f.invocation();
  Object.defineProperty(call.context, "abortSignal", { configurable: true, get() { if (armed) { armed = false; f.factory.close(); } return call.controller.signal; } });
  errorResult(await call.run()); assert.equal(f.state.executes, phase === 1 ? 0 : 1);
});


test("read commit repeated callback cannot qualify a latest matching receipt", async () => {
  const f = fixture({ commitMode: "repeat" }); errorResult(await f.invocation().run()); assert.equal(f.state.prepares, 0); assert.equal(f.state.executes, 0);
});
for (const mode of ["early", "async-reject"]) test(`read window ${mode} closes late entry and cannot produce receipt`, async () => {
  const gate = deferred(), f = fixture({ commitMode: mode, entry: () => gate.promise }), call = f.invocation();
  errorResult(await call.run()); assert.equal(f.state.prepares, 0); gate.resolve(); await assert.rejects(f.state.callbackPromises[0], /readonly-unavailable/); assert.equal(f.state.executes, 0);
});
test("read window sync rejection refuses stored late callback before entry read", async () => {
  const f = fixture({ commitMode: "sync-reject" }); errorResult(await f.invocation().run()); assert.equal(f.state.prepares, 0);
  await assert.rejects(f.state.callbackInvokers[0](), /readonly-unavailable/); assert.equal(f.state.entryReads, 0); assert.equal(f.state.executes, 0);
});


test("verifyCurrent rejected native Promise is rejected synchronously and its rejection observed", async () => {
  const f = fixture(), rejected = Promise.reject(new Error(secret));
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: () => rejected }), /readonly-unavailable/);
  await tick(); assert.equal(f.state.executes, 0);
});
test("control.check rejected native Promise never authorizes and its rejection observed", async () => {
  const f = fixture({ check: () => Promise.reject(new Error(secret)) }); errorResult(await f.invocation().run()); await tick(); assert.equal(f.state.executes, 0);
});
test("native Promise own then getter is never read by observer", async () => {
  const f = fixture(), rejected = Promise.reject(new Error(secret)); let reads = 0;
  Object.defineProperty(rejected, "then", { get() { reads++; throw Error(secret); } });
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: () => rejected }), /readonly-unavailable/);
  await tick(); assert.equal(reads, 0);
});
test("unknown thenable accessor is never inspected or invoked", async () => {
  let reads = 0; const unknown = { get then() { reads++; throw Error(secret); } }, f = fixture();
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: () => unknown }), /readonly-unavailable/);
  const g = fixture({ check: () => unknown }); errorResult(await g.invocation().run()); await tick(); assert.equal(reads, 0); assert.equal(g.state.executes, 0);
});

test("fulfilled native Promise cannot asynchronously grant either synchronous check", async () => {
  const f = fixture(); assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: () => Promise.resolve(true) }), /readonly-unavailable/);
  const g = fixture({ check: () => Promise.resolve(true) }); errorResult(await g.invocation().run()); await tick(); assert.equal(g.state.executes, 0);
});
test("fulfilled own constructor accessor and subclass species are rejected without unsafe getter reads", async () => {
  const f = fixture(); let reads = 0;
  const own = Promise.resolve(true); Object.defineProperty(own, "constructor", { get() { reads++; throw Error(secret); } });
  assert.throws(() => createDurableReadonlyRegistry({ ...f.config, verifyCurrent: () => own }), /readonly-unavailable/);
  class CustomPromise extends Promise { static get [Symbol.species]() { reads++; throw Error(secret); } }
  const custom = new CustomPromise(resolve => resolve(true));
  const g = fixture({ check: () => custom }); errorResult(await g.invocation().run()); await tick(); assert.equal(reads, 0); assert.equal(g.state.executes, 0);
});

test("original false control check cannot be replaced by own call getter", async () => {
  const f = fixture({ check() { return false; } }), call = f.invocation(); let getter = 0, spy = 0;
  Object.defineProperty(f.control.check, "call", { get() { getter++; return (receiver, ticket, invocation) => { spy++; assert.equal(receiver, f.control); assert.equal(ticket, f.state.tickets[0]); assert.equal(invocation, f.state.invocations[0]); return true; }; } });
  const result = await call.run();
  assert.deepEqual({ getter, spy, originalChecks: f.state.checks, executes: f.state.executes }, { getter: 0, spy: 0, originalChecks: 1, executes: 0 });
  errorResult(result);
});
