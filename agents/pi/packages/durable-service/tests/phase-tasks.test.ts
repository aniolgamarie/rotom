import test from "node:test";
import assert from "node:assert/strict";
import { createDurablePhaseTasks } from "../src/phase-tasks.ts";

const SECRET = "SYNTHETIC_PRIVATE_PHASE_ERROR";
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function fixture() {
  const state = { calls: [], defined: [], permitted: true, onVerify: null, onDefine: null, generationHandler: null, compactionHandler: null };
  function definition(kind, phase) {
    const phases = {
      [phase]: function(task, runtime, context) { state.calls.push({ kind, method: phase, receiver: this, args: [...arguments] }); return state[kind + "Handler"]?.(task, runtime, context); },
      retry: function(task, runtime, context) { state.calls.push({ kind, method: "retry", receiver: this, args: [...arguments] }); return "retry-result"; },
    };
    return { name: "pi." + kind, version: 1, phases,
      initial: function(...args) { state.calls.push({ kind, method: "initial", receiver: this, args }); return args[0]; },
      abort: function(...args) { state.calls.push({ kind, method: "abort", receiver: this, args }); return args[0]; },
      migrate: function(...args) { state.calls.push({ kind, method: "migrate", receiver: this, args }); return args[0]; }, hooks: { event() {} } };
  }
  const durable = { GenerationTask: { definition: definition("generation", "request") }, CompactionTask: { definition: definition("compaction", "summarize") },
    defineTask(definition) { assert.equal(this, durable); state.defined.push(definition); state.onDefine?.(definition); return { definition }; } };
  const input = { durable, verifyCurrent: function() { assert.equal(this, input); state.onVerify?.(); return state.permitted; } };
  function invocation(kind = "generation", id = 10, controller = new AbortController(), phase = kind === "generation" ? "request" : "summarize") {
    const task = { id, conversationId: 20, kind: "pi." + kind, version: 1, state: { status: "running", checkpoint: { phase } } };
    Object.defineProperty(task, "input", { get() { assert.fail("task input read"); } });
    const runtime = { taskId: id, conversationId: 20, signal: controller.signal };
    const context = { get abortSignal() { return controller.signal; } };
    return { task, runtime, context, controller, signal: controller.signal };
  }
  return { state, durable, input, invocation, create: () => createDurablePhaseTasks(input) };
}
function invalid(call, code = "phase-unavailable") {
  assert.throws(call, error => { assert.equal(error.message, code); assert.equal(error.code, code); assert.deepEqual(error.cause, undefined); assert.ok(!String(error).includes(SECRET)); return true; });
}
function phase(result, item) {
  return (item.task.kind === "pi.generation" ? result.generationTask : result.compactionTask).definition.phases[item.task.state.checkpoint.phase](item.task, item.runtime, item.context);
}


test("two complete definitions and all raw receiver/argument forwarding", async () => {
  const f = fixture(), result = f.create();
  assert.ok(Object.isFrozen(result) && Object.isFrozen(result.bridge)); assert.equal(f.state.defined.length, 2);
  for (const [kind, token, original] of [["generation", result.generationTask, f.durable.GenerationTask], ["compaction", result.compactionTask, f.durable.CompactionTask]]) {
    const def = token.definition;
    assert.ok(Object.isFrozen(def) && Object.isFrozen(def.phases)); assert.deepEqual(Object.keys(def).sort(), ["abort", "hooks", "initial", "migrate", "name", "phases", "version"]);
    assert.equal(def.hooks, original.definition.hooks); assert.ok(!Object.isFrozen(original.definition));
    const argument = { marker: kind };
    for (const method of ["initial", "abort", "migrate"]) {
      assert.equal(def[method](argument, 2, 3, 4), argument);
      const call = f.state.calls.at(-1); assert.equal(call.receiver, original.definition); assert.deepEqual(call.args, [argument, 2, 3, 4]);
    }
    const item = f.invocation(kind); await phase(result, item);
    let call = f.state.calls.at(-1); assert.equal(call.receiver, original.definition.phases); assert.deepEqual(call.args, [item.task, item.runtime, item.context]);
    const other = f.invocation(kind, 11, new AbortController(), "retry"); assert.equal(phase(result, other), "retry-result");
    call = f.state.calls.at(-1); assert.equal(call.receiver, original.definition.phases); assert.deepEqual(call.args, [other.task, other.runtime, other.context]);
    invalid(() => result.bridge.take(other.signal, kind === "generation" ? "streamSimple" : "completeSimple"), "identity-unmatched");
  }
});

for (const kind of ["generation", "compaction"]) test(`${kind} actual handler uses original identity once and exits exact lease`, async () => {
  const f = fixture(), pending = deferred(), result = f.create(), item = f.invocation(kind);
  let identity; f.state[kind + "Handler"] = () => { identity = result.bridge.take(item.signal, kind === "generation" ? "streamSimple" : "completeSimple"); return pending.promise; };
  const running = phase(result, item), operation = kind === "generation" ? "streamSimple" : "completeSimple";
  assert.deepEqual(identity, { schema: 1, nativeTaskId: 10, nativeConversationId: 20, call_kind: kind }); assert.ok(Object.isFrozen(identity));
  assert.equal(result.bridge.check(item.signal, operation, identity), true);
  pending.resolve("actual-value"); assert.equal(await running, "actual-value"); invalid(() => result.bridge.check(item.signal, operation, identity), "identity-stale");
});

test("sequential same invocation can replace record and gets new identity without harming new lease", async () => {
  const f = fixture(), result = f.create(), item = f.invocation(); let first, second;
  f.state.generationHandler = () => { first = result.bridge.take(item.signal, "streamSimple"); };
  await phase(result, item);
  const next = { ...item, task: { id: 10, conversationId: 20, kind: "pi.generation", version: 1, state: { status: "running", checkpoint: { phase: "request" } } } };
  const pending = deferred(); f.state.generationHandler = () => { second = result.bridge.take(item.signal, "streamSimple"); return pending.promise; };
  const running = phase(result, next); assert.notEqual(first, second);
  invalid(() => result.bridge.check(item.signal, "streamSimple", first), "identity-stale"); assert.equal(result.bridge.check(item.signal, "streamSimple", second), true);
  pending.resolve(); await running;
});

for (const fault of ["wrong-operation", "duplicate-take", "abort"]) test(`${fault} does not disable another task`, async () => {
  const f = fixture(), result = f.create(), a = f.invocation(), b = f.invocation("compaction", 11), one = deferred(), two = deferred();
  f.state.generationHandler = () => one.promise; f.state.compactionHandler = () => two.promise;
  const pa = phase(result, a), pb = phase(result, b);
  if (fault === "wrong-operation") invalid(() => result.bridge.take(a.signal, "completeSimple"), "operation-invalid");
  else if (fault === "duplicate-take") { result.bridge.take(a.signal, "streamSimple"); invalid(() => result.bridge.take(a.signal, "streamSimple"), "identity-consumed"); }
  else { a.controller.abort(); invalid(() => result.bridge.take(a.signal, "streamSimple"), "signal-invalid"); }
  const identity = result.bridge.take(b.signal, "completeSimple"); assert.equal(result.bridge.check(b.signal, "completeSimple", identity), true);
  one.resolve(); two.resolve(); await Promise.all([pa, pb]);
});

for (const fault of ["overlap", "runtime", "context", "task", "kind"]) test(`same signal ${fault} association retires component`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation(), pending = deferred(); f.state.generationHandler = () => pending.promise;
  const first = phase(result, item);
  if (fault !== "overlap") { pending.resolve(); await first; }
  const next = { ...item };
  if (fault === "runtime") next.runtime = { ...item.runtime };
  if (fault === "context") next.context = { abortSignal: item.signal };
  if (fault === "task") { next.task = { ...item.task, id: 11 }; next.runtime.taskId = 11; }
  if (fault === "kind") { next.task = { ...item.task, kind: "pi.compaction", state: { status: "running", checkpoint: { phase: "summarize" } } }; }
  await assert.rejects(phase(result, next), { message: "phase-unavailable" }); invalid(result.check);
  pending.resolve(); await first;
});

test("unconsumed and rejected phases clean lease without replacing original exception", async () => {
  const f = fixture(), result = f.create(), item = f.invocation(); await phase(result, item);
  invalid(() => result.bridge.take(item.signal, "streamSimple"), "identity-unmatched");
  const original = new Error(SECRET); f.state.generationHandler = () => { throw original; };
  await assert.rejects(phase(result, item), error => error === original);
  invalid(() => result.bridge.take(item.signal, "streamSimple"), "identity-unmatched"); assert.equal(result.check(), true);
});

test("close denies active bridge but does not cancel or replace handler result", async () => {
  const f = fixture(), result = f.create(), item = f.invocation(), pending = deferred(); let identity;
  f.state.generationHandler = () => { identity = result.bridge.take(item.signal, "streamSimple"); return pending.promise; };
  const running = phase(result, item); result.close(); invalid(() => result.bridge.check(item.signal, "streamSimple", identity));
  assert.equal(item.signal.aborted, false); pending.resolve("late"); assert.equal(await running, "late"); invalid(result.check);
});

for (const mutation of ["verify-phase", "verify-input", "context-source", "context-identity", "verify-reentry", "context-reentry"]) test(`${mutation} must precede zero original entry`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation();
  if (mutation === "verify-phase") f.state.onVerify = () => { f.durable.GenerationTask.definition.phases.request = () => assert.fail("new handler entered"); };
  if (mutation === "verify-input") f.state.onVerify = () => { f.input.verifyCurrent = () => true; };
  if (mutation === "verify-reentry") f.state.onVerify = () => { try { result.check(); } catch {} };
  if (mutation.startsWith("context-")) Object.defineProperty(item.context, "abortSignal", { configurable: true, get() {
    if (mutation === "context-source") f.durable.defineTask = () => assert.fail("new define entered");
    else if (mutation === "context-identity") item.task.id = 11;
    else { try { result.bridge.take(item.signal, "streamSimple"); } catch {} }
    return item.signal;
  } });
  await assert.rejects(phase(result, item), { message: "phase-unavailable" }); assert.equal(f.state.calls.length, 0); invalid(result.check);
});

test("constructor callback cannot invoke phase before ready", () => {
  const f = fixture(), item = f.invocation(); let invoked;
  f.state.onDefine = def => { invoked = def.phases.request?.(item.task, item.runtime, item.context); invoked?.catch(() => undefined); };
  invalid(f.create); assert.equal(f.state.calls.length, 0);
});

test("ordinary rejected checker Promise is observed but never grants, including own then getter", async () => {
  const f = fixture(); let calls = 0;
  const rejected = Promise.reject(new Error(SECRET)); Object.defineProperty(rejected, "then", { get() { calls++; throw new Error(SECRET); } });
  f.state.permitted = rejected; invalid(f.create); assert.equal(calls, 0); await new Promise(resolve => setImmediate(resolve));
});

test("unknown thenable and custom Promise constructor accessors are not read", () => {
  let calls = 0; const f = fixture(); f.state.permitted = { get then() { calls++; throw new Error(SECRET); } }; invalid(f.create);
  const other = fixture(), promise = Promise.resolve(true); Object.defineProperty(promise, "constructor", { get() { calls++; throw new Error(SECRET); } }); other.state.permitted = promise; invalid(other.create);
  assert.equal(calls, 0);
});

for (const fault of ["task-id", "runtime-id", "version", "status", "phase", "runtime-getter", "context-signal", "signal-fake"]) test(`native invocation ${fault} rejected before original handler`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation();
  if (fault === "task-id") item.task.id = true;
  if (fault === "runtime-id") item.runtime.conversationId = 21;
  if (fault === "version") item.task.version = 2;
  if (fault === "status") item.task.state.status = "pending";
  if (fault === "phase") item.task.state.checkpoint.phase = "retry";
  if (fault === "runtime-getter") Object.defineProperty(item.runtime, "taskId", { get() { assert.fail("runtime getter called"); } });
  if (fault === "context-signal") Object.defineProperty(item.context, "abortSignal", { get() { return new AbortController().signal; } });
  if (fault === "signal-fake") item.runtime.signal = {};
  await assert.rejects(result.generationTask.definition.phases.request(item.task, item.runtime, item.context)); assert.equal(f.state.calls.length, 0);
});

for (const fault of ["extra-config", "proxy", "extra-definition", "missing-target", "accessor", "wrong-return"]) test(`construction ${fault} fails closed`, () => {
  const f = fixture();
  if (fault === "extra-config") f.input.extra = true;
  if (fault === "proxy") f.input.durable = new Proxy(f.durable, { get() { assert.fail("proxy trap"); } });
  if (fault === "extra-definition") f.durable.GenerationTask.definition.input = {};
  if (fault === "missing-target") delete f.durable.GenerationTask.definition.phases.request;
  if (fault === "accessor") Object.defineProperty(f.durable, "defineTask", { get() { assert.fail("method getter called"); } });
  if (fault === "wrong-return") f.durable.defineTask = () => ({ definition: {} });
  invalid(f.create);
});


test("unregistered fake and Proxy signals reject only this call, legitimate lease remains usable", async () => {
  const f = fixture(), result = f.create(), item = f.invocation(), pending = deferred(); f.state.generationHandler = () => pending.promise;
  const running = phase(result, item); let traps = 0;
  const fake = { get aborted() { traps++; throw new Error(SECRET); } };
  const proxy = new Proxy(fake, { get() { traps++; throw new Error(SECRET); } });
  for (const signal of [fake, proxy]) invalid(() => result.bridge.take(signal, "streamSimple"), "signal-invalid");
  const identity = result.bridge.take(item.signal, "streamSimple");
  for (const signal of [fake, proxy]) invalid(() => result.bridge.check(signal, "streamSimple", identity), "signal-invalid");
  assert.equal(result.bridge.check(item.signal, "streamSimple", identity), true); assert.equal(traps, 0);
  pending.resolve(); await running;
});

test("bounded public hook source counts key bytes as well as values", () => {
  const f = fixture(); f.durable.GenerationTask.definition.hooks = { ["x".repeat(1024 * 1024 + 1)]: () => undefined };
  invalid(f.create); assert.equal(f.state.defined.length, 0);
});


test("SDK namespace extra exports are ignored, its original prototype must remain fixed", () => {
  const f = fixture(); Object.defineProperty(f.durable, "UnrelatedRootExport", { get() { assert.fail("unselected export inspected"); } });
  const result = f.create(); assert.equal(result.check(), true);
  Object.setPrototypeOf(f.durable, null); invalid(result.check);
});


for (const mutation of ["phase-function", "hooks", "returned-token", "runtime-id", "context-getter", "verify-promise"]) test(`await boundary ${mutation} closes before any renewed bridge use`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation(), pending = deferred(); let identity;
  f.state.generationHandler = () => { identity = result.bridge.take(item.signal, "streamSimple"); return pending.promise; };
  const running = phase(result, item);
  if (mutation === "phase-function") f.durable.GenerationTask.definition.phases.retry = () => undefined;
  if (mutation === "hooks") f.durable.GenerationTask.definition.hooks.event = () => undefined;
  if (mutation === "returned-token") result.generationTask.definition = {};
  if (mutation === "runtime-id") item.runtime.taskId = 11;
  if (mutation === "context-getter") Object.defineProperty(item.context, "abortSignal", { get() { return item.signal; } });
  if (mutation === "verify-promise") f.state.permitted = Promise.reject(new Error(SECRET));
  invalid(() => result.bridge.check(item.signal, "streamSimple", identity)); invalid(result.check);
  pending.resolve("already-running"); assert.equal(await running, "already-running");
  await new Promise(resolve => setImmediate(resolve));
});

for (const callback of ["verify-phase", "context-check"]) test(`synchronous callback ${callback} reentry retires before original entry`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation(); let nested;
  if (callback === "verify-phase") f.state.onVerify = () => { nested = phase(result, item); nested.catch(() => undefined); };
  else Object.defineProperty(item.context, "abortSignal", { get() { try { result.check(); } catch {} return item.signal; } });
  await assert.rejects(phase(result, item), { message: "phase-unavailable" });
  if (nested) await assert.rejects(nested, { message: "phase-unavailable" });
  assert.equal(f.state.calls.length, 0); invalid(result.check);
});

test("cancelled signal cannot register sequential lease while other task still works", async () => {
  const f = fixture(), result = f.create(), a = f.invocation(), b = f.invocation("compaction", 12), pending = deferred();
  await phase(result, a); a.controller.abort(); f.state.compactionHandler = () => pending.promise;
  const running = phase(result, b); await assert.rejects(phase(result, a), { message: "signal-invalid" });
  const identity = result.bridge.take(b.signal, "completeSimple"); assert.equal(result.bridge.check(b.signal, "completeSimple", identity), true);
  pending.resolve(); await running;
});

test("equal copied identity is stale without retiring original current lease", async () => {
  const f = fixture(), result = f.create(), item = f.invocation(), pending = deferred(); f.state.generationHandler = () => pending.promise;
  const running = phase(result, item), identity = result.bridge.take(item.signal, "streamSimple");
  invalid(() => result.bridge.check(item.signal, "streamSimple", Object.freeze({ ...identity })), "identity-stale");
  assert.equal(result.bridge.check(item.signal, "streamSimple", identity), true); pending.resolve(); await running;
});

test("ordinary fulfilled Promise and subclass checker never grant permission", () => {
  const f = fixture(); f.state.permitted = Promise.resolve(true); invalid(f.create);
  class CustomPromise extends Promise {} const g = fixture(); g.state.permitted = CustomPromise.resolve(true); invalid(g.create);
});

test("optional fields may be absent and whole original source captured before foreign defineTask", () => {
  const f = fixture(); delete f.durable.GenerationTask.definition.hooks; delete f.durable.CompactionTask.definition.migrate;
  const result = f.create(); assert.ok(!Object.hasOwn(result.generationTask.definition, "hooks") && !Object.hasOwn(result.compactionTask.definition, "migrate"));
  const g = fixture(); g.state.onDefine = () => { g.durable.CompactionTask.definition.initial = () => assert.fail("mutated original invoked"); };
  invalid(g.create); assert.equal(g.state.calls.length, 0);
});


for (const target of [true, false]) for (const mutation of ["task-id", "conversation-id", "signal-context", "context-descriptor"]) test(`first ${target ? "target" : "non-target"} invocation captures before verify ${mutation}`, async () => {
  const f = fixture(), result = f.create(), item = f.invocation("generation", 10, new AbortController(), target ? "request" : "retry");
  let once = false, registrations = 0;
  if (target) f.state.generationHandler = () => { result.bridge.take(item.runtime.signal, "streamSimple"); registrations++; };
  f.state.onVerify = () => {
    if (once) return; once = true;
    if (mutation === "task-id") { item.task.id = 11; item.runtime.taskId = 11; }
    if (mutation === "conversation-id") { item.task.conversationId = 21; item.runtime.conversationId = 21; }
    if (mutation === "signal-context") {
      const changed = new AbortController().signal; item.runtime.signal = changed;
      Object.defineProperty(item.context, "abortSignal", { configurable: true, get() { return changed; } });
    }
    if (mutation === "context-descriptor") Object.defineProperty(item.context, "abortSignal", { configurable: true, get() { return item.signal; } });
  };
  await assert.rejects(async () => phase(result, item), { message: "phase-unavailable" });
  assert.equal(f.state.calls.length, 0); assert.equal(registrations, 0);
});

test("verify own call cannot substitute true for original false permit", () => {
  const f = fixture(); let spy = 0, original = 0;
  f.input.verifyCurrent = function() { original++; assert.equal(this, f.input); return false; };
  f.input.verifyCurrent.call = () => { spy++; return true; };
  invalid(f.create); assert.equal(spy, 0); assert.equal(original, 1); assert.equal(f.state.defined.length, 0);
});

for (const entry of ["defineTask", "phase", "initial", "abort", "migrate", "context-getter"]) test(`function own invocation accessor cannot hijack ${entry}`, async () => {
  const f = fixture(); let spy = 0;
  if (entry === "defineTask") Object.defineProperty(f.durable.defineTask, "call", { get() { spy++; return () => { throw new Error("own call hijack"); }; } });
  const result = f.create(), item = f.invocation();
  if (entry === "phase") Object.defineProperty(f.durable.GenerationTask.definition.phases.request, "call", { get() { spy++; return () => "hijacked"; } });
  if (["initial", "abort", "migrate"].includes(entry)) Object.defineProperty(f.durable.GenerationTask.definition[entry], "apply", { get() { spy++; return () => "hijacked"; } });
  if (entry === "context-getter") {
    const getter = Object.getOwnPropertyDescriptor(item.context, "abortSignal").get;
    Object.defineProperty(getter, "call", { get() { spy++; return () => item.signal; } });
  }
  if (["initial", "abort", "migrate"].includes(entry)) {
    const argument = { original: true }; assert.equal(result.generationTask.definition[entry](argument, 2, 3), argument);
    const call = f.state.calls.at(-1); assert.equal(call.receiver, f.durable.GenerationTask.definition); assert.deepEqual(call.args, [argument, 2, 3]);
  } else if (entry === "defineTask") assert.equal(f.state.defined.length, 2);
  else {
    await phase(result, item); assert.equal(f.state.calls.length, 1);
    assert.equal(f.state.calls[0].receiver, f.durable.GenerationTask.definition.phases); assert.deepEqual(f.state.calls[0].args, [item.task, item.runtime, item.context]);
  }
  assert.equal(spy, 0);
});
