import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableCallIdentityBridge } from "../src/call-identity.ts";

const secret = "synthetic-key /private/account SQL model-message";
function code(expected) {
  return error => {
    assert.equal(error.message, expected); assert.equal(error.code, expected); assert.equal(error.cause, undefined);
    assert(!String(error.stack).includes(secret)); return true;
  };
}
function scope(taskId = 1, conversationId = 1) {
  const controller = new AbortController();
  class PublicContext { get abortSignal() { return controller.signal; } }
  class PublicApi {
    get taskId() { return taskId; }
    get conversationId() { return conversationId; }
  }
  return { controller, signal: controller.signal, api: new PublicApi(), context: new PublicContext() };
}
function observe(bridge, current, kind = "generation") {
  return kind === "generation" ? bridge.generationHooks.beforeRequest(undefined, current.api, current.context)
    : bridge.compactionHooks.beforeCompact(undefined, current.api, current.context);
}
const expected = (task, conversation, kind) => ({ schema: 1, nativeTaskId: task, nativeConversationId: conversation, call_kind: kind });

for (const [kind, operation] of [["generation", "streamSimple"], ["compaction", "completeSimple"]]) {
  test(`${kind} hook returns undefined and one frozen native observation`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(17, 31);
    assert(Object.isFrozen(bridge)); assert(Object.isFrozen(bridge.generationHooks)); assert(Object.isFrozen(bridge.compactionHooks));
    assert.equal(observe(bridge, current, kind), undefined);
    const result = bridge.take(current.signal, operation);
    assert.deepEqual(result, expected(17, 31, kind)); assert(Object.isFrozen(result));
    assert.throws(() => bridge.take(current.signal, operation), code("identity-consumed"));
    assert.equal(Reflect.ownKeys(result).length, 4);
  });
}
test("multiple interleaved tasks and calls keep their own signal identity", () => {
  const bridge = createDurableCallIdentityBridge(), a = scope(3, 10), b = scope(8, 10), c = scope(4, 29);
  observe(bridge, a); observe(bridge, b, "compaction"); observe(bridge, c);
  assert.deepEqual(bridge.take(c.signal, "streamSimple"), expected(4, 29, "generation"));
  assert.deepEqual(bridge.take(b.signal, "completeSimple"), expected(8, 10, "compaction"));
  assert.deepEqual(bridge.take(a.signal, "streamSimple"), expected(3, 10, "generation"));
  observe(bridge, b, "compaction"); observe(bridge, a);
  assert.deepEqual(bridge.take(a.signal, "streamSimple"), expected(3, 10, "generation"));
  assert.deepEqual(bridge.take(b.signal, "completeSimple"), expected(8, 10, "compaction"));
});
test("same invocation tool loop needs a new hook for every take", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(16, 71);
  for (let turn = 0; turn < 5; turn++) {
    observe(bridge, current);
    assert.deepEqual(bridge.take(current.signal, "streamSimple"), expected(16, 71, "generation"));
    assert.throws(() => bridge.take(current.signal, "streamSimple"), code("identity-consumed"));
  }
});
test("cross-bridge and replacement/composite signals cannot reconstruct identity from numeric IDs", () => {
  const bridge = createDurableCallIdentityBridge(), other = createDurableCallIdentityBridge(), current = scope(9, 2), replacement = scope(9, 2);
  observe(bridge, current);
  assert.throws(() => other.take(current.signal, "streamSimple"), code("identity-unmatched"));
  assert.throws(() => bridge.take(replacement.signal, "streamSimple"), code("identity-unmatched"));
  const composite = AbortSignal.any([current.signal, replacement.signal]);
  assert.notEqual(composite, current.signal);
  assert.throws(() => bridge.take(composite, "streamSimple"), code("identity-unmatched"));
  assert.deepEqual(bridge.take(current.signal, "streamSimple"), expected(9, 2, "generation"));
});
test("a registered genuine composite signal only matches that exact object", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(), other = scope();
  const composite = AbortSignal.any([current.signal, other.signal]);
  observe(bridge, { ...current, context: { abortSignal: composite } });
  assert.throws(() => bridge.take(current.signal, "streamSimple"), code("identity-unmatched"));
  assert.deepEqual(bridge.take(composite, "streamSimple"), expected(1, 1, "generation"));
});
test("duplicate hook swallowed by dispatcher retires whole bridge including unrelated pending records", () => {
  const bridge = createDurableCallIdentityBridge(), old = scope(2, 4), other = scope(5, 6);
  observe(bridge, old); observe(bridge, other);
  let reported = 0;
  // 只模拟自有 dispatcher 吞错，不导入或执行宿主；take 独立拒绝旧登记。
  try { observe(bridge, old); } catch (error) { code("hook-invalid")(error); reported++; }
  assert.equal(reported, 1);
  assert.throws(() => bridge.take(old.signal, "streamSimple"), code("bridge-retired"));
  assert.throws(() => bridge.take(other.signal, "streamSimple"), code("bridge-retired"));
  assert.throws(() => observe(bridge, scope(7, 8)), code("hook-invalid"));
});
for (const conflict of ["task", "conversation", "kind"]) {
  test(`consumed signal ${conflict} conflict retires entire bridge`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(5, 12), unrelated = scope(7, 13);
    observe(bridge, current); bridge.take(current.signal, "streamSimple"); observe(bridge, unrelated);
    const next = { ...current, api: { taskId: conflict === "task" ? 6 : 5, conversationId: conflict === "conversation" ? 14 : 12 } };
    assert.throws(() => observe(bridge, next, conflict === "kind" ? "compaction" : "generation"), code("hook-invalid"));
    assert.throws(() => bridge.take(current.signal, "streamSimple"), code("bridge-retired"));
    assert.throws(() => bridge.take(unrelated.signal, "streamSimple"), code("bridge-retired"));
  });
}
for (const operation of ["completeSimple", "unknown", undefined, {}, "fetchDeferred", "cancelDeferred"]) {
  test(`wrong generation operation ${String(operation)} retires known identity and cannot be rearmed`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
    const error = ["fetchDeferred", "cancelDeferred"].includes(operation) ? "unsupported" : "operation-invalid";
    assert.throws(() => bridge.take(current.signal, operation), code(error));
    assert.throws(() => bridge.take(current.signal, "streamSimple"), code("identity-retired"));
    assert.throws(() => observe(bridge, current), code("hook-invalid"));
    assert.throws(() => bridge.take(current.signal, "streamSimple"), code("bridge-retired"));
  });
}
test("wrong compaction operation retires that identity without retiring other pending identities until a failing hook", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(), other = scope(8, 9);
  observe(bridge, current, "compaction"); observe(bridge, other);
  assert.throws(() => bridge.take(current.signal, "streamSimple"), code("operation-invalid"));
  assert.deepEqual(bridge.take(other.signal, "streamSimple"), expected(8, 9, "generation"));
  assert.throws(() => bridge.take(current.signal, "completeSimple"), code("identity-retired"));
});
for (const operation of ["fetchDeferred", "cancelDeferred"]) {
  test(`${operation} is explicitly unsupported even without hook registration`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope();
    assert.throws(() => bridge.take(current.signal, operation), code("unsupported"));
  });
}
for (const field of ["taskId", "conversationId"]) for (const value of [undefined, null, true, false, "1", 1n, new Number(1), 0, -1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
  test(`invalid native ${field} ${String(value)} retires bridge with old pending signal`, () => {
    const bridge = createDurableCallIdentityBridge(), old = scope(3, 4), current = scope(); observe(bridge, old);
    const api = { taskId: 1, conversationId: 1, [field]: value };
    assert.throws(() => observe(bridge, { ...current, api }), code("hook-invalid"));
    assert.throws(() => bridge.take(old.signal, "streamSimple"), code("bridge-retired"));
  });
}
test("native positive safe integer upper bound accepted without authorization fields", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
  observe(bridge, current); assert.deepEqual(bridge.take(current.signal, "streamSimple"), expected(Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER, "generation"));
});
for (const shape of ["missing-context", "missing-api", "api-getter", "context-getter", "api-proxy", "context-proxy", "revoked-api-proxy", "revoked-context-proxy", "missing-signal", "fake-signal", "prototype-fake", "signal-proxy", "revoked-signal-proxy", "aborted-signal"]) {
  test(`${shape} hook validation fail retires all records and sanitizes raw errors`, () => {
    const bridge = createDurableCallIdentityBridge(), old = scope(6, 7), current = scope(); observe(bridge, old);
    let api = current.api, context = current.context;
    if (shape === "missing-context") context = undefined;
    if (shape === "missing-api") api = undefined;
    if (shape === "api-getter") api = { get taskId() { throw new Error(secret); }, conversationId: 1 };
    if (shape === "context-getter") context = { get abortSignal() { throw new Error(secret); } };
    if (shape === "api-proxy") api = new Proxy(api, {});
    if (shape === "context-proxy") context = new Proxy(context, {});
    if (shape === "revoked-api-proxy") { const p = Proxy.revocable(api, {}); p.revoke(); api = p.proxy; }
    if (shape === "revoked-context-proxy") { const p = Proxy.revocable(context, {}); p.revoke(); context = p.proxy; }
    if (shape === "missing-signal") context = { abortSignal: undefined };
    if (shape === "fake-signal") context = { abortSignal: { aborted: false } };
    if (shape === "prototype-fake") context = { abortSignal: Object.create(AbortSignal.prototype) };
    if (shape === "signal-proxy") context = { abortSignal: new Proxy(current.signal, {}) };
    if (shape === "revoked-signal-proxy") { const p = Proxy.revocable(current.signal, {}); p.revoke(); context = { abortSignal: p.proxy }; }
    if (shape === "aborted-signal") current.controller.abort(secret);
    assert.throws(() => bridge.generationHooks.beforeRequest(undefined, api, context), code("hook-invalid"));
    assert.throws(() => bridge.take(old.signal, "streamSimple"), code("bridge-retired"));
  });
}
test("request/compaction/extra API/Context bodies are never read", () => {
  let reads = 0;
  const body = new Proxy({}, { get() { reads++; throw new Error(secret); }, ownKeys() { reads++; throw new Error(secret); } });
  const bridge = createDurableCallIdentityBridge(), gen = scope(5, 8), compact = scope(6, 8);
  for (const object of [gen.api, gen.context, compact.api, compact.context]) for (const name of ["messages", "entries", "instructions", "memo", "request", "model"]) {
    Object.defineProperty(object, name, { get() { reads++; throw new Error(secret); } });
  }
  assert.equal(bridge.generationHooks.beforeRequest(body, gen.api, gen.context), undefined);
  assert.equal(bridge.compactionHooks.beforeCompact(body, compact.api, compact.context), undefined);
  assert.deepEqual(bridge.take(gen.signal, "streamSimple"), expected(5, 8, "generation"));
  assert.deepEqual(bridge.take(compact.signal, "completeSimple"), expected(6, 8, "compaction"));
  assert.equal(reads, 0);
});
test("native aborted getter rejects abort despite shadowed user aborted property", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
  Object.defineProperty(current.signal, "aborted", { value: false }); current.controller.abort(secret);
  assert.throws(() => bridge.take(current.signal, "streamSimple"), code("signal-invalid"));
  assert.throws(() => observe(bridge, current), code("hook-invalid"));
});
test("close retires pending observations, is repeatable, and does not abort SDK-like work", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
  assert.equal(bridge.close(), undefined); assert.equal(bridge.close(), undefined);
  assert.equal(current.signal.aborted, false);
  assert.throws(() => bridge.take(current.signal, "streamSimple"), code("bridge-retired"));
  assert.throws(() => observe(bridge, current), code("hook-invalid"));
});
test("public Context getter reentrant close cannot arm an observation after retirement", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope();
  const context = { get abortSignal() { bridge.close(); return current.signal; } };
  assert.throws(() => bridge.generationHooks.beforeRequest(undefined, current.api, context), code("hook-invalid"));
  assert.throws(() => bridge.take(current.signal, "streamSimple"), code("bridge-retired"));
});
for (const value of [undefined, {}, { approved: true }, () => {}, new Proxy({}, {})]) {
  test(`factory rejects any argument (${typeof value}) before side effects`, () => {
    assert.throws(() => createDurableCallIdentityBridge(value), code("input-invalid"));
  });
}
for (const value of [undefined, null, {}, Object.create(AbortSignal.prototype), new Proxy(new AbortController().signal, {})]) {
  test(`invalid take signal ${String(value === undefined)} fails without consuming known observation`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
    assert.throws(() => bridge.take(value, "streamSimple"), code("signal-invalid"));
    assert.deepEqual(bridge.take(current.signal, "streamSimple"), expected(1, 1, "generation"));
  });
}

for (const [kind, operation] of [["generation", "streamSimple"], ["compaction", "completeSimple"]]) {
  test(`live check ${kind} repeatedly verifies the original consumed identity without rearming`, () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(3, 9);
    observe(bridge, current, kind);
    const identity = bridge.take(current.signal, operation);
    assert.equal(bridge.check(current.signal, operation, identity), true);
    assert.equal(bridge.check(current.signal, operation, identity), true);
    assert.throws(() => bridge.take(current.signal, operation), code("identity-consumed"));
    assert.throws(() => bridge.check(current.signal, operation, { ...identity }), code("identity-stale"));
    assert.throws(() => bridge.check(scope(3, 9).signal, operation, identity), code("identity-stale"));
    assert.throws(() => bridge.check(current.signal, operation === "streamSimple" ? "completeSimple" : "streamSimple", identity), code("identity-stale"));
    assert.equal(bridge.check(current.signal, operation, identity), true);
  });
}
test("live check refuses pending or forged observations without reading their body", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
  let reads = 0;
  const forged = new Proxy({}, { get() { reads++; throw new Error(secret); }, ownKeys() { reads++; throw new Error(secret); } });
  assert.throws(() => bridge.check(current.signal, "streamSimple", forged), code("identity-stale"));
  const identity = bridge.take(current.signal, "streamSimple");
  assert.throws(() => bridge.check(current.signal, "streamSimple", forged), code("identity-stale"));
  assert.equal(reads, 0); assert.equal(bridge.check(current.signal, "streamSimple", identity), true);
});
for (const retire of ["close", "hook-failure", "abort"]) {
  test(`live check observes ${retire} after an asynchronous authorization wait`, async () => {
    const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
    const identity = bridge.take(current.signal, "streamSimple");
    assert.equal(bridge.check(current.signal, "streamSimple", identity), true);
    await Promise.resolve();
    if (retire === "close") bridge.close();
    if (retire === "hook-failure") {
      assert.throws(() => observe(bridge, { ...scope(), api: { taskId: false, conversationId: 1 } }), code("hook-invalid"));
    }
    if (retire === "abort") {
      Object.defineProperty(current.signal, "aborted", { value: false }); current.controller.abort(secret);
    }
    let entries = 0;
    assert.throws(() => { bridge.check(current.signal, "streamSimple", identity); entries++; }, code(retire === "abort" ? "signal-invalid" : "bridge-retired"));
    assert.equal(entries, 0);
  });
}
test("live check invalidates an old call when a new same-signal hook replaces its observation", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
  const old = bridge.take(current.signal, "streamSimple");
  observe(bridge, current);
  assert.throws(() => bridge.check(current.signal, "streamSimple", old), code("identity-stale"));
  const next = bridge.take(current.signal, "streamSimple");
  assert.deepEqual(old, next); assert.notEqual(old, next);
  assert.throws(() => bridge.check(current.signal, "streamSimple", old), code("identity-stale"));
  assert.equal(bridge.check(current.signal, "streamSimple", next), true);
});
test("live check rejects retired records and fake signal brands with fixed errors", () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(); observe(bridge, current);
  const identity = bridge.take(current.signal, "streamSimple");
  for (const value of [undefined, {}, Object.create(AbortSignal.prototype), new Proxy(current.signal, {})]) {
    assert.throws(() => bridge.check(value, "streamSimple", identity), code("signal-invalid"));
  }
  assert.throws(() => bridge.take(current.signal, "completeSimple"), code("operation-invalid"));
  assert.throws(() => bridge.check(current.signal, "streamSimple", identity), code("identity-retired"));
});

for (const kind of ["generation", "compaction"]) test(`owned ${kind} hook cannot acquire an own bind replacement`, () => {
  const bridge = createDurableCallIdentityBridge(), current = scope(21, 31), hooks = kind === "generation" ? bridge.generationHooks : bridge.compactionHooks;
  const handler = kind === "generation" ? hooks.beforeRequest : hooks.beforeCompact; let getter = 0, spy = 0, installed = false;
  try { Object.defineProperty(handler, "bind", { get() { getter++; return () => { spy++; return () => undefined; }; } }); installed = true; } catch {}
  const bound = handler.bind(hooks); bound(undefined, current.api, current.context);
  assert.deepEqual({ installed, getter, spy }, { installed: false, getter: 0, spy: 0 });
  assert.deepEqual(bridge.take(current.signal, kind === "generation" ? "streamSimple" : "completeSimple"), expected(21, 31, kind));
});
