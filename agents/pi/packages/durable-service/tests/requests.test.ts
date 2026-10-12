import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableRequestAdmission } from "../src/requests.ts";
import { requestSession, deferred, copy } from "./request-session.ts";

const secret = "PRIVATE request auth SDK failure";
const tick = () => new Promise(resolve => setImmediate(resolve));
const fixed = code => failure => { assert.equal(failure.code, code); assert.equal(failure.message, code); assert.equal(failure.cause, undefined); assert(!failure.stack.includes(secret)); return true; };
function input(extra = {}) { return { requestId: "request-1", input: { text: "  中文 body\n" }, grant: Object.fromEntries(["sourceIdentity", "authorizationIdentity", "registryIdentity", "policyIdentity", "readCapabilityIdentity", "inputSnapshotIdentity", "artifactIdentity"].map((key, index) => [key, (index === 2 ? "b" : "c").repeat(64)])), route: { provider: "fictional/provider", model: "模型" }, budget: { scopeId: "scope-1", maxCalls: 2, maxCostUnits: 30 }, ...extra }; }
function fixture(mode = "create") {
  const f = requestSession(), authority = { current: true }, rootTask = { definition: { name: "rotom.durable.request", version: 1, privateBody: secret } };
  const config = { session: f.session, durable: f.durable, chord: f.chord, rootTask, context: f.state.context, mode, verifyCurrent: () => authority.current, deploymentIdentity: "a".repeat(64), registryIdentity: "b".repeat(64), conversationId: 7 };
  return { ...f, config, rootTask, authority, create: () => createDurableRequestAdmission(config) };
}
test("lazy constructor, private singleton, atomic task/doc and exact frozen original receipt", async () => {
  const f = fixture(), api = f.create(), original = input(), before = copy(original);
  assert(Object.isFrozen(api)); assert.equal(f.state.commits, 0); assert.equal(f.state.snapshots, 0); assert.equal(f.state.creates, 0);
  assert.equal(f.state.token.definition.kind, "rotom.durable.requests"); assert.equal(f.state.token.definition.scope, "session");
  await api.initialize(); assert.equal(f.state.writes, 1);
  const result = await api.submit(original); assert(Object.isFrozen(result)); assert.equal(result.nativeTaskId, 10); assert.equal(result.nativeConversationId, 7);
  assert.match(result.taskId, /^rotom-durable:[a-f0-9]{64}$/); assert.equal(f.state.document.rows[0].taskId, result.taskId);
  assert.equal(f.state.tasks.get(10).input.taskId, result.taskId); assert.deepEqual(original, before); assert(!Object.isFrozen(original));
  assert.deepEqual(await api.lookup(original), result); assert.equal(f.state.gets, 1); assert.equal(f.state.creates, 1);
});
test("concurrent duplicates commit serially, exactly one task, replay reads before table write", async () => {
  const f = fixture(), api = f.create(); await api.initialize();
  const receipts = await Promise.all(Array.from({ length: 12 }, () => api.submit(input())));
  assert(receipts.every(value => value.nativeTaskId === 10)); assert.equal(f.state.creates, 1); assert.equal(f.state.txReads, 11); assert.equal(f.state.document.rows.length, 1);
  f.state.tasks.get(10).state = { status: "terminal", outcome: { status: "completed" } };
  assert.deepEqual(await api.submit(input()), receipts[0]);
});
test("active mode never creates missing doc; create never overwrites existing bound or sentinel doc", async () => {
  const f = fixture("active"), api = f.create(); await assert.rejects(api.initialize(), fixed("recovery-required")); assert.equal(f.state.commits, 0);
  for (const existing of [{ schema: 1, deploymentIdentity: null, registryIdentity: null, conversationId: null, rows: [] }, { wrong: true }]) {
    const f = fixture(); f.state.document = copy(existing); const api = f.create(); await assert.rejects(api.initialize(), fixed("store-exists")); assert.deepEqual(f.state.document, existing); assert.equal(f.state.commits, 0);
  }
});
test("old sentinel inserted after snapshot is not overwritten by create callback", async () => {
  const f = fixture(), api = f.create(); const sentinel = { schema: 1, deploymentIdentity: null, registryIdentity: null, conversationId: null, rows: [] };
  f.state.hooks.snapshot = state => { state.document = copy(sentinel); };
  await assert.rejects(api.initialize(), fixed("store-exists")); assert.deepEqual(f.state.document, sentinel); assert.equal(f.state.writes, 0); assert.equal(f.state.creates, 0);
});
test("active reopen uses original task, lookup is noncreating, healthy absence is only null", async () => {
  const f = fixture(), first = f.create(); await first.initialize(); const receipt = await first.submit(input()); first.close();
  f.config.mode = "active"; const reopened = f.create(); await reopened.initialize();
  const writes = f.state.writes; assert.deepEqual(await reopened.lookup(input()), receipt); assert.equal(await reopened.lookup(input({ requestId: "absent" })), null);
  assert.equal(f.state.writes, writes); assert.equal(f.state.creates, 1);
});
for (const change of [value => value.input.text += "changed", value => value.route.model += "2", value => value.route.provider += "2", value => value.budget.scopeId += "2", value => value.budget.maxCalls++, value => value.budget.maxCostUnits++, ...["authorizationIdentity", "policyIdentity", "readCapabilityIdentity", "inputSnapshotIdentity", "artifactIdentity"].map(key => value => value.grant[key] = "d".repeat(64))]) test(`full body conflict ${change.toString()}`, async () => {
  const f = fixture(), api = f.create(); await api.initialize(); await api.submit(input()); const different = input(); change(different);
  await assert.rejects(api.submit(different), fixed("request-conflict")); await assert.rejects(api.lookup(different), fixed("request-conflict")); assert.equal(f.state.creates, 1);
  assert.equal((await api.submit(input())).nativeTaskId, 10);
});
test("sourceIdentity is part of identity, not a duplicate request key", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const first = await api.submit(input()); const second = input(); second.grant.sourceIdentity = "e".repeat(64);
  const result = await api.submit(second); assert.notEqual(result.taskId, first.taskId); assert.equal(f.state.creates, 2);
});
for (const stage of ["beforeCallback", "beforeAdopt", "afterAdopt"]) test(`SDK secret failure ${stage} closes without claiming not-sent; lookup recovers only persisted ID`, async () => {
  const f = fixture(), api = f.create(); await api.initialize();
  f.state.hooks[stage] = () => { throw new Error(secret); };
  await assert.rejects(api.submit(input()), fixed("recovery-required")); delete f.state.hooks[stage];
  await assert.rejects(api.submit(input({ requestId: "new" })), fixed("recovery-required"));
  if (stage === "afterAdopt") { assert.equal((await api.lookup(input())).nativeTaskId, 10); assert.equal(f.state.document.rows.length, 1); }
  else { assert.equal(await api.lookup(input()), null); assert.equal(f.state.document.rows.length, 0); }
});
for (const mode of ["skipCallback", "replaceReceipt"]) for (const operation of ["initialize", "submit"]) test(`${operation} rejects ${mode} success`, async () => {
  const f = fixture(), api = f.create(); if (operation === "submit") await api.initialize(); f.state.hooks[mode] = true;
  await assert.rejects(operation === "initialize" ? api.initialize() : api.submit(input()), fixed("recovery-required"));
  await assert.rejects(api.submit(input()), fixed("recovery-required"));
});
for (const stage of ["doc", "createTask", "afterAdopt"]) for (const action of ["close", "authority"]) test(`${action} during ${stage} await cannot return accepted`, async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const gate = deferred(); f.state.hooks[stage] = () => gate.promise;
  const pending = api.submit(input()); await tick(); if (action === "close") api.close(); else f.authority.current = false; gate.resolve();
  await assert.rejects(pending, failure => { assert(["recovery-required", "current-invalid"].includes(failure.code)); return true; });
  assert.equal(f.state.document.rows.length, stage === "afterAdopt" ? 1 : 0);
  if (action === "close" && stage === "afterAdopt") assert.equal((await api.lookup(input())).nativeTaskId, 10);
});
for (const change of [task => task.kind = "other", task => task.version = 2, task => task.conversationId++, task => task.owner = 1, task => task.background = true, task => task.id++, task => task.input.request.input.text += "changed"]) test(`exact original TaskRecord rejects ${change.toString()}`, async () => {
  const f = fixture(), api = f.create(); await api.initialize(); await api.submit(input()); change(f.state.tasks.get(10));
  await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.creates, 1); await assert.rejects(api.lookup(input()), fixed("recovery-required"));
});
test("missing task/document do not recreate and malformed stored hashes retire", async () => {
  for (const corrupt of [state => state.tasks.clear(), state => state.document = undefined, state => state.document.rows[0].inputIdentity = "f".repeat(64), state => state.document.rows.push(copy(state.document.rows[0]))]) {
    const f = fixture(), api = f.create(); await api.initialize(); await api.submit(input()); corrupt(f.state);
    await assert.rejects(api.lookup(input()), fixed("recovery-required")); await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.creates, 1);
  }
});
for (const alter of [value => value.extra = 1, value => value.input.text = "\ud800", value => value.input.text = "x".repeat(65537), value => value.budget.maxCalls = 4097, value => value.budget.maxCostUnits = NaN, value => value.grant.registryIdentity = "d".repeat(64), value => value.route.model = "\u0000", value => value.requestId = "bad id", value => value[Symbol("x")] = 1]) test(`invalid business input ${alter.toString()} is call-local and zero task`, async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const value = input(); alter(value); await assert.rejects(api.submit(value), fixed("input-invalid")); assert.equal(f.state.creates, 0); await api.submit(input());
});
test("proxy/revoked proxy/getters/inherited fields/cycle/toJSON rejected without execution", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); let reads = 0;
  const values = [new Proxy(input(), { ownKeys() { reads++; throw Error(secret); } }), Object.create(input()), Object.assign(input(), { toJSON() { reads++; throw Error(secret); } })];
  const accessor = input(); Object.defineProperty(accessor.input, "text", { enumerable: true, get() { reads++; throw Error(secret); } }); values.push(accessor);
  const cycle = input(); cycle.input.text = cycle; values.push(cycle);
  const revoked = Proxy.revocable(input(), {}); revoked.revoke(); values.push(revoked.proxy);
  for (const value of values) await assert.rejects(api.submit(value), fixed("input-invalid")); assert.equal(reads, 0); assert.equal(f.state.creates, 0);
});
test("Object.prototype getters/toJSON do not supply missing fields or execute", async () => {
  let count = 0; const saved = Object.getOwnPropertyDescriptor(Object.prototype, "text"), savedJson = Object.getOwnPropertyDescriptor(Object.prototype, "toJSON");
  try {
    Object.defineProperty(Object.prototype, "text", { configurable: true, get() { count++; throw Error(secret); } });
    Object.defineProperty(Object.prototype, "toJSON", { configurable: true, get() { count++; throw Error(secret); } });
    const f = fixture(), api = f.create(); await api.initialize(); const invalid = input(); invalid.input = {}; await assert.rejects(api.submit(invalid), fixed("input-invalid")); await api.submit(input()); assert.equal(count, 0);
  } finally { if (saved) Object.defineProperty(Object.prototype, "text", saved); else delete Object.prototype.text; if (savedJson) Object.defineProperty(Object.prototype, "toJSON", savedJson); else delete Object.prototype.toJSON; }
});
test("method drift or root definition drift retires before entry and late drift cannot return receipt", async () => {
  for (const action of [f => f.session.commit = () => assert.fail("drift entered"), f => f.chord.copyJson = () => assert.fail("drift entered"), f => f.rootTask.definition.version = 2]) {
    const f = fixture(), api = f.create(); await api.initialize(); action(f); await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.creates, 0);
  }
  const f = fixture(), api = f.create(); await api.initialize(); f.state.hooks.afterAdopt = () => { f.session.getTask = () => assert.fail("drift entered"); };
  await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.document.rows.length, 1);
});
test("untrusted error code getter is not read; staged semantic-looking error still unknown", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); let reads = 0;
  f.state.hooks.createTask = () => { const failure = new Error(secret); Object.defineProperty(failure, "code", { get() { reads++; throw Error(secret); } }); throw failure; };
  await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(reads, 0); assert.equal(f.state.document.rows.length, 0);
});
test("opaque Context rejects proxy/null; generic prototype methods cannot impersonate public API", () => {
  for (const context of [null, undefined, new Proxy({}, {})]) { const f = fixture(); f.config.context = context; assert.throws(f.create, fixed("input-invalid")); }
  const f = fixture(); f.config.session = {}; assert.throws(f.create, fixed("recovery-required"));
});

test("initialize lost ack retains binding but never reinitializes or accepts submit", async () => {
  const f = fixture(), api = f.create(); f.state.hooks.afterAdopt = () => { throw Error(secret); };
  await assert.rejects(api.initialize(), fixed("recovery-required")); delete f.state.hooks.afterAdopt;
  assert.equal(f.state.document.deploymentIdentity, "a".repeat(64)); assert.equal(await api.lookup(input()), null);
  await assert.rejects(api.initialize(), fixed("recovery-required")); await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.commits, 1);
});
for (const operation of ["initialize", "submit"]) test(`${operation} late close before adoption rejects without closing shared Session`, async () => {
  const f = fixture(), api = f.create(); if (operation === "submit") await api.initialize(); const gate = deferred(); f.state.hooks.beforeAdopt = () => gate.promise;
  const pending = operation === "initialize" ? api.initialize() : api.submit(input()); await tick(); api.close(); gate.resolve(); await assert.rejects(pending, fixed("recovery-required"));
  assert.equal(f.state.document.deploymentIdentity, "a".repeat(64)); assert.equal(f.state.document.rows.length, operation === "submit" ? 1 : 0); assert.equal(typeof f.session.close, "undefined");
});
test("a saved own validation error thrown later by SDK cannot spoof safe rollback", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); let previous;
  const bad = input(); bad.extra = true; try { await api.submit(bad); } catch (failure) { previous = failure; }
  f.state.hooks.beforeCallback = () => { throw previous; };
  await assert.rejects(api.submit(input()), fixed("recovery-required")); delete f.state.hooks.beforeCallback; await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.creates, 0);
});
test("original business input can mutate during await without changing captured full task input", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const gate = deferred(); f.state.hooks.snapshot = () => gate.promise;
  const value = input(), expected = copy(value), pending = api.submit(value); await tick(); value.input.text = "later mutation"; value.budget.maxCalls = 3; gate.resolve();
  const receipt = await pending; assert.deepEqual(f.state.tasks.get(receipt.nativeTaskId).input.request, expected); assert(!Object.isFrozen(value));
});
test("native ID reuse/invalid ID after createTask closes without adopting duplicate row", async () => {
  for (const nativeId of [10, 0, "11", Number.MAX_SAFE_INTEGER + 1]) {
    const f = fixture(), api = f.create(); await api.initialize(); await api.submit(input()); f.state.hooks.nativeId = nativeId;
    await assert.rejects(api.submit(input({ requestId: "second" })), fixed("recovery-required")); assert.equal(f.state.document.rows.length, 1); assert.equal(f.state.tasks.size, 1);
  }
});
test("private document definition drift fails before any snapshot or task write", async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const reads = f.state.snapshots;
  f.state.token.definition.initial = () => assert.fail("changed initial entered"); await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.snapshots, reads); assert.equal(f.state.creates, 0);
});
test("4096 permanent rows reach capacity before createTask; replay still reads original task", async () => {
  const { createHash } = await import("node:crypto");
  const encode = value => Array.isArray(value) ? "[" + value.map(encode).join(",") + "]" : value && typeof value === "object" ? "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + encode(value[key])).join(",") + "}" : JSON.stringify(value);
  const digest = value => createHash("sha256").update(encode(value)).digest("hex");
  const f = fixture(), api = f.create(); await api.initialize(); const receipt = await api.submit(input());
  for (let index = 1; index < 4096; index++) {
    const request = input({ requestId: "retained-" + index }); f.state.document.rows.push({ request, taskId: "rotom-durable:" + digest(["a".repeat(64), request.grant.sourceIdentity, request.requestId]), inputIdentity: digest(request), nativeTaskId: 100 + index });
  }
  f.state.document.rows.sort((a, b) => a.taskId < b.taskId ? -1 : 1);
  await assert.rejects(api.submit(input({ requestId: "overflow" })), fixed("capacity-exceeded")); assert.equal(f.state.creates, 1); assert.equal(f.state.document.rows.length, 4096); assert.deepEqual(await api.submit(input()), receipt);
});
test("oversized or nonclosed stored document never silently drops rows", async () => {
  for (const alter of [doc => doc.extra = true, doc => doc.rows = new Array(4097), doc => doc.registryIdentity = "f".repeat(64), doc => doc.conversationId++]) {
    const f = fixture(), api = f.create(); await api.initialize(); alter(f.state.document); await assert.rejects(api.lookup(input()), fixed("recovery-required")); await assert.rejects(api.submit(input()), fixed("recovery-required")); assert.equal(f.state.creates, 0);
  }
});
test("verifyCurrent must be exact true and thrown secrets are sanitized", async () => {
  for (const verifyCurrent of [() => 1, () => { throw Error(secret); }]) {
    const f = fixture(); f.config.verifyCurrent = verifyCurrent; const api = f.create();
    await assert.rejects(api.initialize(), failure => { assert(["current-invalid", "recovery-required"].includes(failure.code)); assert(!failure.stack.includes(secret)); return true; }); assert.equal(f.state.commits, 0);
  }
});
test("defineDoc unknown error is fixed and no factory I/O occurs", () => {
  const f = fixture(); f.durable.defineDoc = () => { throw Error(secret); }; assert.throws(f.create, fixed("recovery-required")); assert.equal(f.state.commits, 0); assert.equal(f.state.snapshots, 0);
});

test("SDK doc/extractor cannot reuse a saved own error as safe semantic callback failure", async () => {
  for (const target of ["doc", "copyJson"]) {
    const f = fixture(); let saved;
    const bad = input(); bad.extra = true;
    if (target === "copyJson") f.chord.copyJson = () => { throw saved; };
    const api = f.create(); if (target === "doc") await api.initialize();
    try { await api.submit(bad); } catch (failure) { saved = failure; }
    if (target === "doc") f.state.hooks.doc = () => { throw saved; };
    await assert.rejects(target === "doc" ? api.submit(input()) : api.initialize(), fixed("recovery-required"));
    if (target === "doc") delete f.state.hooks.doc;
    await assert.rejects(api.submit(input()), fixed("recovery-required"));
  }
});
test("8 MiB document cap refuses a new row before creating a task and rejects oversized existing document", async () => {
  const { createHash } = await import("node:crypto");
  const encode = value => Array.isArray(value) ? "[" + value.map(encode).join(",") + "]" : value && typeof value === "object" ? "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + encode(value[key])).join(",") + "}" : JSON.stringify(value);
  const digest = value => createHash("sha256").update(encode(value)).digest("hex");
  const f = fixture(), api = f.create(); await api.initialize(); let overflow;
  for (let index = 0; index < 200; index++) {
    const request = input({ requestId: "bytes-" + index, input: { text: "x".repeat(65536) } });
    const row = { request, taskId: "rotom-durable:" + digest(["a".repeat(64), request.grant.sourceIdentity, request.requestId]), inputIdentity: digest(request), nativeTaskId: index + 10 };
    const next = { ...f.state.document, rows: [...f.state.document.rows, row] };
    if (Buffer.byteLength(encode(next), "utf8") > 8 * 1024 * 1024) { overflow = row; break; }
    f.state.document.rows.push(row);
  }
  f.state.document.rows.sort((a, b) => a.taskId < b.taskId ? -1 : 1);
  assert(overflow); await assert.rejects(api.submit(overflow.request), fixed("capacity-exceeded")); assert.equal(f.state.creates, 0);
  f.state.document.rows.push(overflow); f.state.document.rows.sort((a, b) => a.taskId < b.taskId ? -1 : 1);
  await assert.rejects(api.lookup(input()), fixed("recovery-required")); assert.equal(f.state.creates, 0);
});

for (const action of ["close", "authority", "method-drift"]) test(`cached successful initialize rechecks ${action} and performs no new commit`, async () => {
  const f = fixture(), api = f.create(); await api.initialize(); const commits = f.state.commits;
  if (action === "close") api.close(); else if (action === "authority") f.authority.current = false; else f.session.snapshot = () => assert.fail("drift entered");
  const retry = api.initialize(); assert(retry instanceof Promise); await assert.rejects(retry, fixed(action === "authority" ? "current-invalid" : "recovery-required")); assert.equal(f.state.commits, commits);
});
test("closed caller cannot obtain shared in-flight initialization promise", async () => {
  const f = fixture(), api = f.create(), gate = deferred(); f.state.hooks.beforeAdopt = () => gate.promise;
  const pending = api.initialize(); const originalFailure = assert.rejects(pending, fixed("recovery-required")); await tick(); api.close();
  const retry = api.initialize(); assert(retry instanceof Promise);
  const state = await Promise.race([retry.then(() => "success", () => "rejected"), tick().then(() => "pending")]);
  gate.resolve(); await originalFailure; assert.equal(state, "rejected"); assert.equal(f.state.commits, 1);
});

for (const operation of ["initialize", "submit", "lookup"]) test(`ordinary rejected verifyCurrent Promise at ${operation} is never permission and rejection is observed`, async () => {
  const f = fixture(); let current = true; f.config.verifyCurrent = () => current; const api = f.create();
  if (operation !== "initialize") await api.initialize();
  const writes = f.state.writes, commits = f.state.commits; current = Promise.reject(new Error(secret));
  await assert.rejects(operation === "initialize" ? api.initialize() : api[operation](input()), fixed("current-invalid"));
  await tick(); assert.equal(f.state.writes, writes); assert.equal(f.state.commits, commits); assert.equal(f.state.creates, 0);
});
test("rejected native Promise with own then accessor does not read it", async () => {
  const f = fixture(); let reads = 0; const rejected = Promise.reject(new Error(secret));
  Object.defineProperty(rejected, "then", { get() { reads++; throw Error(secret); } }); f.config.verifyCurrent = () => rejected;
  const api = f.create(); await assert.rejects(api.initialize(), fixed("current-invalid")); await tick(); assert.equal(reads, 0); assert.equal(f.state.writes, 0);
});
test("unknown thenable accessor is never read or invoked by current check", async () => {
  const f = fixture(); let reads = 0; const unknown = { get then() { reads++; throw Error(secret); } }; f.config.verifyCurrent = () => unknown;
  const api = f.create(); await assert.rejects(api.initialize(), fixed("current-invalid")); await tick(); assert.equal(reads, 0); assert.equal(f.state.writes, 0);
});

for (const operation of ["initialize", "submit", "lookup"]) test(`fulfilled verifyCurrent Promise at ${operation} cannot grant after resolve`, async () => {
  const f = fixture(); let current = true; f.config.verifyCurrent = () => current; const api = f.create(); if (operation !== "initialize") await api.initialize();
  const writes = f.state.writes; current = Promise.resolve(true);
  await assert.rejects(operation === "initialize" ? api.initialize() : api[operation](input()), fixed("current-invalid")); await tick(); assert.equal(f.state.writes, writes); assert.equal(f.state.creates, 0);
});
test("fulfilled custom constructor/subclass are refused without unsafe getter execution", async () => {
  let reads = 0; const own = Promise.resolve(true); Object.defineProperty(own, "constructor", { get() { reads++; throw Error(secret); } });
  class CustomPromise extends Promise { static get [Symbol.species]() { reads++; throw Error(secret); } }
  for (const value of [own, new CustomPromise(resolve => resolve(true))]) {
    const f = fixture(); f.config.verifyCurrent = () => value; const api = f.create(); await assert.rejects(api.initialize(), fixed("current-invalid")); await tick(); assert.equal(f.state.writes, 0);
  }
  assert.equal(reads, 0);
});
test("Promise refusal keeps closed writes and readonly recovery semantics unchanged", async () => {
  const f = fixture(); let current = true; f.config.verifyCurrent = () => current; const api = f.create(); await api.initialize(); const receipt = await api.submit(input());
  const writes = f.state.writes; current = Promise.resolve(true); await assert.rejects(api.submit(input({ requestId: "second" })), fixed("current-invalid")); current = true;
  await assert.rejects(api.submit(input({ requestId: "third" })), fixed("recovery-required")); await assert.rejects(api.initialize(), fixed("recovery-required"));
  assert.deepEqual(await api.lookup(input()), receipt); assert.equal(f.state.writes, writes); assert.equal(f.state.creates, 1);
});

test("original commit body executes despite own call forged callback receipt and fake task", async () => {
  const f = fixture(), api = f.create(); await api.initialize();
  const beforeCommits = f.state.commits, beforeWrites = f.state.writes; let spy = 0, getter = 0, fakeCreates = 0;
  Object.defineProperty(f.session.commit, "call", { get() { getter++; return async (receiver, callback, context) => {
    spy++; assert.equal(receiver, f.session); assert.equal(context, f.state.context);
    const draft = copy(f.state.document);
    const tx = { async doc(token) { assert.equal(this, tx); assert.equal(token, f.state.token); return draft; },
      async task() { assert.equal(this, tx); return undefined; },
      async createTask(token, original, options) { assert.equal(this, tx); assert.equal(token, f.rootTask); assert.equal(options.conversationId, 7); assert(original.request); fakeCreates++; return 777; } };
    return callback(tx);
  }; } });
  const receipt = await api.submit(input());
  assert.deepEqual({ getter, spy, fakeCreates, originalCommits: f.state.commits - beforeCommits, writes: f.state.writes - beforeWrites, originalCreates: f.state.creates, persisted: f.state.tasks.size },
    { getter: 0, spy: 0, fakeCreates: 0, originalCommits: 1, writes: 1, originalCreates: 1, persisted: 1 });
  assert.equal(receipt.nativeTaskId, 10); assert.equal(f.state.tasks.has(receipt.nativeTaskId), true);
});
