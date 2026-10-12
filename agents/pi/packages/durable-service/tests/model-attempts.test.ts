import assert from "node:assert/strict";
import { test } from "node:test";
import { createModelAttemptStore } from "../src/model-attempts.ts";
import { databaseFixture } from "./model-attempt-database.ts";

const deployment = "a".repeat(64), secret = "synthetic-key /private/account SQL request-body";
const canonical = value => value && typeof value === "object" ? Array.isArray(value) ? "[" + value.map(canonical).join(",") + "]"
  : "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}" : JSON.stringify(value);
const defer = () => { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; };
const input = (attemptId = "a1", taskId = "task", extra = {}) => ({ attemptId, taskId, phase: "generation", nativeTaskId: 4, nativeConversationId: 9,
  registryIdentity: "b".repeat(64), inputIdentity: "c".repeat(64), policyIdentity: "d".repeat(64), route: { provider: "fictional", model: "模型/model" },
  budget: { scopeId: "scope-" + taskId, maxCalls: 4, maxCostUnits: 100, reservationUnits: 20 }, ...extra });
const result = (extra = {}) => ({ resultRef: "e".repeat(64), outcome: "completed", observedRoute: input().route, ...extra });
const settlement = (estimatedCostUnits = 10) => ({ usage: { input: 3, output: 7, cacheRead: 0, cacheWrite: 2 }, estimatedCostUnits });
function code(expected) { return error => { assert.equal(error.message, expected); assert.equal(error.code, expected); assert.equal(error.cause, undefined); assert(!String(error.stack).includes(secret)); return true; }; }
async function fixture(t, mode = "create", existing) {
  const f = existing ?? databaseFixture(); if (!existing) t.after(() => f.cleanup());
  const configuration = { database: f.database, deploymentIdentity: deployment, mode };
  const init = createModelAttemptStore(configuration), api = await init();
  return { ...f, configuration, init, api };
}
async function completed(api, value = input(), cost = 10) {
  await api.prepare(value); assert.equal((await api.commitSending(value.attemptId)).committedNow, true);
  await api.recordResult(value.attemptId, result({ observedRoute: value.route })); return api.settle(value.attemptId, settlement(cost));
}
function rawDocument(f) { return f.raw.prepare("SELECT document FROM rotom_model_attempt_ledger WHERE singleton=1").get().document; }
function overwrite(f, raw) { f.raw.prepare("UPDATE rotom_model_attempt_ledger SET document=? WHERE singleton=1").run(raw); }

test("lazy initializer shares one Promise, one canonical singleton, and does not own shared database close", async t => {
  const f = databaseFixture(); t.after(() => f.cleanup());
  const init = createModelAttemptStore({ database: f.database, deploymentIdentity: deployment, mode: "create" });
  assert.equal(f.counters.transactions, 0); const first = init(); assert.equal(init(), first);
  const api = await first; assert.equal(await init(), api); assert(Object.isFrozen(api)); assert.equal(f.counters.transactions, 1);
  const master = f.raw.prepare("SELECT sql FROM sqlite_master WHERE name='rotom_model_attempt_ledger'").get(); assert(master.sql.includes("singleton INTEGER PRIMARY KEY"));
  assert.equal(rawDocument(f), canonical({ schema: 1, deploymentIdentity: deployment, tasks: [], attempts: [] }));
  api.close(); assert.equal(await init(), api); assert.equal(f.counters.dbCloses, 0);
  await assert.rejects(api.prepare(input()), code("persistence-unknown"));
  assert.equal(f.raw.prepare("SELECT 1 AS alive").get().alive, 1);
});
test("normal immutable transitions, replay markers, reservation and precise decimal projections", async t => {
  const { api } = await fixture(t);
  const prepared = await api.prepare(input()); assert.equal(prepared.state, "prepared"); assert(Object.isFrozen(prepared)); assert(Object.isFrozen(prepared.input.route));
  assert.equal((await api.prepare(input())).state, "prepared");
  assert.equal((await api.snapshot("task")).chargedCostUnits, "20");
  const sent = await api.commitSending("a1"); assert.equal(sent.committedNow, true); assert.equal(sent.attempt.sendOutcome, "unknown"); assert(Object.isFrozen(sent));
  assert.equal((await api.commitSending("a1")).committedNow, false);
  await api.recordResult("a1", result()); assert.equal((await api.snapshot("task")).reservedCostUnits, "20");
  assert.equal((await api.recordResult("a1", result())).state, "result-recorded");
  await api.settle("a1", settlement());
  assert.equal((await api.settle("a1", settlement())).state, "settled");
  assert.equal((await api.recordResult("a1", result())).state, "settled");
  assert.equal((await api.commitSending("a1")).committedNow, false);
  const snapshot = await api.snapshot("task"); assert.equal(snapshot.calls, 1); assert.equal(snapshot.chargedCostUnits, "10"); assert.equal(snapshot.reservedCostUnits, "0"); assert.equal(snapshot.overBudget, false);
  assert.equal(snapshot.outstandingAttemptId, null); assert.equal(snapshot.attempts[0].sendOutcome, null); assert(Object.isFrozen(snapshot));
  await assert.rejects(api.notSent("a1"), code("transition-invalid"));
});
test("not-sent tombstone frees only ledger reservation and cannot restore sending or change task budget/scope", async t => {
  const { api } = await fixture(t); await api.prepare(input()); await api.notSent("a1");
  assert.equal((await api.notSent("a1")).state, "not-sent");
  const snapshot = await api.snapshot("task"); assert.equal(snapshot.calls, 0); assert.equal(snapshot.chargedCostUnits, "0"); assert.equal(snapshot.attempts.length, 1);
  assert.equal((await api.prepare(input())).state, "not-sent");
  await assert.rejects(api.commitSending("a1"), code("transition-invalid"));
  await assert.rejects(api.prepare(input("a2", "task", { budget: { ...input().budget, maxCalls: 9 } })), code("budget-conflict"));
  await assert.rejects(api.prepare(input("a2", "task", { budget: { ...input().budget, maxCostUnits: 200 } })), code("budget-conflict"));
  await assert.rejects(api.prepare(input("a2", "task", { budget: { ...input().budget, scopeId: "new-scope" } })), code("budget-conflict"));
  await assert.rejects(api.prepare(input("a2", "other", { budget: input().budget })), code("scope-conflict"));
  await assert.rejects(api.prepare(input("a1", "other")), code("attempt-conflict"));
  assert.equal((await api.prepare(input("a2"))).state, "prepared");
});
for (const state of ["prepared", "sending", "result-recorded"]) test(`${state} keeps full reservation and blocks next attempt`, async t => {
  const { api } = await fixture(t); await api.prepare(input());
  if (state !== "prepared") await api.commitSending("a1");
  if (state === "result-recorded") await api.recordResult("a1", result());
  assert.equal((await api.snapshot("task")).chargedCostUnits, "20");
  await assert.rejects(api.prepare(input("a2")), code("attempt-outstanding"));
  if (state !== "prepared") await assert.rejects(api.notSent("a1"), code("transition-invalid"));
});
test("queued concurrent preparation cannot oversubscribe task and same attempt is idempotent", async t => {
  const { api } = await fixture(t);
  const outcomes = await Promise.allSettled([api.prepare(input("a1")), api.prepare(input("a2"))]);
  assert.equal(outcomes.filter(item => item.status === "fulfilled").length, 1);
  code("attempt-outstanding")(outcomes.find(item => item.status === "rejected").reason);
  const sameAttempt = await Promise.all([api.prepare(input("a1")), api.prepare(input("a1"))]); assert.equal(sameAttempt[0].state, sameAttempt[1].state);
  const sends = await Promise.all([api.commitSending("a1"), api.commitSending("a1")]); assert.deepEqual(sends.map(item => item.committedNow), [true, false]);
});
test("same facade serializes independent stores and returns exactly one first commit marker", async t => {
  const f = await fixture(t), second = await fixture(t, "active", f);
  await f.api.prepare(input());
  const sent = await Promise.all([f.api.commitSending("a1"), second.api.commitSending("a1")]);
  assert.deepEqual(sent.map(item => item.committedNow), [true, false]);
  await second.api.recordResult("a1", result()); await f.api.settle("a1", settlement());
  const next = await Promise.allSettled([f.api.prepare(input("a2")), second.api.prepare(input("a3"))]);
  assert.equal(next.filter(item => item.status === "fulfilled").length, 1);
});
test("call and charged-cost limits remain cumulative across settled calls", async t => {
  const { api } = await fixture(t); const budget = { ...input().budget, maxCalls: 1, maxCostUnits: 50 };
  await completed(api, input("a1", "task", { budget }), 15);
  await assert.rejects(api.prepare(input("a2", "task", { budget })), code("budget-exceeded"));
  const small = { ...input("b1", "other").budget, maxCostUnits: 25 };
  await completed(api, input("b1", "other", { budget: small }), 10);
  await assert.rejects(api.prepare(input("b2", "other", { budget: small })), code("budget-exceeded"));
});
for (const observedRoute of [null, { provider: "different", model: "模型/model" }]) test(`unknown/drifted route stays reserved and never implicitly settles`, async t => {
  const { api } = await fixture(t); await api.prepare(input()); await api.commitSending("a1"); await api.recordResult("a1", result({ observedRoute }));
  await assert.rejects(api.settle("a1", settlement()), code("route-unresolved"));
  await assert.rejects(api.prepare(input("a2")), code("attempt-outstanding"));
  assert.equal((await api.snapshot("task")).chargedCostUnits, "20"); assert.equal((await api.observe("a1")).state, "result-recorded");
});
for (const cost of [21, 101, Number.MAX_SAFE_INTEGER]) test(`over-budget cost ${cost} is retained as old fact then blocks future calls`, async t => {
  const { api } = await fixture(t); await completed(api, input(), cost);
  const snapshot = await api.snapshot("task"); assert.equal(snapshot.chargedCostUnits, String(cost)); assert.equal(snapshot.overBudget, true);
  await assert.rejects(api.prepare(input("a2")), code("budget-exceeded")); assert.equal((await api.observe("a1")).settlement.estimatedCostUnits, cost);
});
test("BigInt aggregate costs exceed native safe range through genuine sequential SQL facts", async t => {
  const f = await fixture(t);
  const budget = { ...input().budget, maxCalls: 4, maxCostUnits: Number.MAX_SAFE_INTEGER, reservationUnits: Number.MAX_SAFE_INTEGER };
  await completed(f.api, input("a1", "task", { budget }), Number.MAX_SAFE_INTEGER - 1);
  await completed(f.api, input("a2", "task", { budget: { ...budget, reservationUnits: 1 } }), Number.MAX_SAFE_INTEGER);
  const snapshot = await f.api.snapshot("task");
  assert.equal(snapshot.chargedCostUnits, (2n * BigInt(Number.MAX_SAFE_INTEGER) - 1n).toString()); assert.equal(snapshot.overBudget, true);
  assert.equal(JSON.parse(rawDocument(f)).attempts.length, 2);
});
test("settlement zero comes from explicit facts and conflicting result/usage never overwrite them", async t => {
  const { api } = await fixture(t); await completed(api, input(), 0);
  assert.equal((await api.snapshot("task")).chargedCostUnits, "0");
  await assert.rejects(api.recordResult("a1", result({ outcome: "failed" })), code("result-conflict"));
  await assert.rejects(api.settle("a1", settlement(1)), code("settlement-conflict"));
  assert.equal((await api.observe("a1")).settlement.estimatedCostUnits, 0);
});
test("persistent reopen reads sending unknown without resend, settlement mode cannot reserve or commit", async t => {
  const f = await fixture(t); await f.api.prepare(input()); await f.api.commitSending("a1"); f.api.close();
  const reopened = databaseFixture({ path: f.path }); t.after(() => reopened.cleanup());
  const { api } = await fixture(t, "settlement", reopened);
  assert.equal((await api.observe("a1")).state, "sending"); assert.equal((await api.observe("a1")).sendOutcome, "unknown"); assert.equal((await api.snapshot("task")).attempts[0].sendOutcome, "unknown"); assert.equal((await api.snapshot("task")).reservedCostUnits, "20");
  await assert.rejects(api.prepare(input("a2")), code("settlement-only")); await assert.rejects(api.commitSending("a1"), code("settlement-only"));
  await api.recordResult("a1", result()); await api.settle("a1", settlement());
  assert.equal((await api.snapshot("task")).settledCostUnits, "10");
  const active = await fixture(t, "active", reopened); assert.equal((await active.api.commitSending("a1")).committedNow, false);
});
test("create-existing is known rollback and one initializer never implicitly retries", async t => {
  const f = await fixture(t); const count = f.counters.transactions;
  const init = createModelAttemptStore({ database: f.database, deploymentIdentity: deployment, mode: "create" });
  const first = init(); await assert.rejects(first, code("store-exists")); assert.equal(init(), first); await assert.rejects(init(), code("store-exists"));
  assert.equal(f.counters.transactions, count + 1); await f.api.prepare(input());
});
for (const mode of ["active", "settlement"]) for (const missing of ["table", "row"]) test(`${mode} missing ${missing} cannot create or repair`, async t => {
  const f = databaseFixture(); t.after(() => f.cleanup());
  if (missing === "row") { const api = await createModelAttemptStore({ database: f.database, deploymentIdentity: deployment, mode: "create" })(); api.close(); f.raw.exec("DELETE FROM rotom_model_attempt_ledger"); }
  const before = f.counters.writes, init = createModelAttemptStore({ database: f.database, deploymentIdentity: deployment, mode });
  const first = init(); await assert.rejects(first, code("persistence-unknown")); assert.equal(init(), first); assert.equal(f.counters.writes, before);
  if (missing === "table") assert.equal(f.raw.prepare("SELECT count(*) AS count FROM sqlite_master WHERE name='rotom_model_attempt_ledger'").get().count, 0);
});
for (const fault of ["duplicate-key", "unknown-key", "deployment", "schema", "duplicate-scope", "bad-state", "budget-ref", "amount", "missing-row", "extra-row", "table-schema", "trigger", "oversized"]) test(`existing ${fault} is permanent persistence-unknown, never repaired`, async t => {
  const f = await fixture(t); await f.api.prepare(input()); const document = JSON.parse(rawDocument(f));
  if (fault === "duplicate-key") overwrite(f, rawDocument(f).replace('"schema":1', '"schema":1,"schema":1'));
  if (fault === "unknown-key") { document.authorization = "synthetic"; overwrite(f, canonical(document)); }
  if (fault === "deployment") { document.deploymentIdentity = "f".repeat(64); overwrite(f, canonical(document)); }
  if (fault === "schema") { document.schema = 2; overwrite(f, canonical(document)); }
  if (fault === "duplicate-scope") { document.tasks.push({ ...document.tasks[0], taskId: "zz-other" }); overwrite(f, canonical(document)); }
  if (fault === "bad-state") { document.attempts[0].state = "retrying"; overwrite(f, canonical(document)); }
  if (fault === "budget-ref") { document.attempts[0].input.budget.scopeId = "wrong"; overwrite(f, canonical(document)); }
  if (fault === "amount") { document.attempts[0].input.budget.reservationUnits = true; overwrite(f, canonical(document)); }
  if (fault === "missing-row") f.raw.exec("DELETE FROM rotom_model_attempt_ledger");
  if (fault === "extra-row") { f.raw.exec("PRAGMA ignore_check_constraints=ON"); f.raw.prepare("INSERT INTO rotom_model_attempt_ledger VALUES (?,?)").run(2, rawDocument(f)); }
  if (fault === "table-schema") f.raw.exec("ALTER TABLE rotom_model_attempt_ledger ADD COLUMN extra TEXT");
  if (fault === "trigger") f.raw.exec("CREATE TRIGGER unexpected AFTER UPDATE ON rotom_model_attempt_ledger BEGIN SELECT 1; END");
  if (fault === "oversized") overwrite(f, " ".repeat(8 * 1024 * 1024 + 1));
  const before = f.counters.writes; await assert.rejects(f.api.observe("a1"), code("persistence-unknown"));
  await assert.rejects(f.api.prepare(input("a2")), code("persistence-unknown")); assert.equal(f.counters.writes, before);
});
test("snapshot/observe are get-only including read-only connection and never initialize missing content", async t => {
  const f = await fixture(t); await f.api.prepare(input());
  const readonly = databaseFixture({ path: f.path, readOnly: true }); t.after(() => readonly.cleanup());
  const observed = await fixture(t, "active", readonly); const before = { ...readonly.counters };
  await observed.api.observe("a1"); await observed.api.snapshot("task");
  assert.equal(readonly.counters.writes, before.writes); assert.equal(readonly.counters.transactions, before.transactions);
  await assert.rejects(observed.api.commitSending("a1"), code("persistence-unknown"));
  assert.equal((await f.api.observe("a1")).state, "prepared");
});
for (const fault of ["lostAck", "commitFailure", "writeFailure"]) test(`${fault} retires facade, reopen never automatically resends`, async t => {
  const f = await fixture(t); await f.api.prepare(input()); f.faults[fault] = new Error(secret);
  await assert.rejects(f.api.commitSending("a1"), code("persistence-unknown"));
  delete f.faults[fault]; await assert.rejects(f.api.commitSending("a1"), code("persistence-unknown"));
  const active = await fixture(t, "active", f);
  const observed = await active.api.observe("a1"); assert.equal(observed.state, fault === "lostAck" ? "sending" : "prepared");
  if (fault === "lostAck") { assert.equal((await active.api.commitSending("a1")).committedNow, false); await assert.rejects(active.api.notSent("a1"), code("transition-invalid")); }
});
for (const fault of ["rollbackFailure", "replaceSemantic"]) test(`${fault} prevents forged semantic rollback acknowledgement and retires`, async t => {
  const f = await fixture(t); await f.api.prepare(input());
  f.faults[fault] = Object.assign(new Error(secret), { code: "attempt-conflict" });
  await assert.rejects(f.api.prepare(input("a1", "other")), code("persistence-unknown"));
  delete f.faults[fault]; await assert.rejects(f.api.observe("a1"), code("persistence-unknown"));
});
test("SQL error carrying semantic-looking code is never treated as safe rollback", async t => {
  const f = await fixture(t); f.faults.getFailure = Object.assign(new Error(secret), { code: "budget-exceeded" });
  await assert.rejects(f.api.prepare(input()), code("persistence-unknown"));
  delete f.faults.getFailure; await assert.rejects(f.api.prepare(input()), code("persistence-unknown"));
});
test("real SQLite full-page write failure is unknown and permanently retired", async t => {
  const f = await fixture(t); f.raw.exec("PRAGMA max_page_count=2");
  let failed = false;
  for (let index = 0; index < 20; index++) {
    try { await f.api.prepare(input("a" + index, "task", { route: { provider: "fictional", model: "中".repeat(256) } })); await f.api.notSent("a" + index); }
    catch (error) { code("persistence-unknown")(error); failed = true; break; }
  }
  assert.equal(failed, true); await assert.rejects(f.api.observe("a0"), code("persistence-unknown"));
});
for (const fault of ["executor", "facade", "configuration"]) test(`${fault} method/identity drift is persistence-unknown`, async t => {
  const f = await fixture(t); await f.api.prepare(input());
  if (fault === "executor") f.faults.methodDrift = true;
  if (fault === "facade") f.database.get = async () => ({});
  if (fault === "configuration") f.configuration.deploymentIdentity = "f".repeat(64);
  await assert.rejects(fault === "executor" ? f.api.commitSending("a1") : f.api.snapshot("task"), code("persistence-unknown"));
  await assert.rejects(f.api.prepare(input("a2")), code("persistence-unknown"));
});
test("close during after-commit acknowledgement preserves sending and never returns committedNow true", async t => {
  const f = await fixture(t); await f.api.prepare(input()); const gate = defer(); f.faults.afterCommitGate = gate;
  const committed = f.api.commitSending("a1");
  await new Promise(resolve => setImmediate(resolve)); assert.equal(JSON.parse(rawDocument(f)).attempts[0].state, "sending");
  f.api.close(); gate.resolve(); await assert.rejects(committed, code("persistence-unknown"));
  delete f.faults.afterCommitGate; const active = await fixture(t, "active", f);
  assert.equal((await active.api.commitSending("a1")).committedNow, false); assert.equal(f.counters.dbCloses, 0);
});
test("close during in-flight preparation/query retires result without clearing existing facts", async t => {
  const f = await fixture(t); await f.api.prepare(input()); const gate = defer(); f.faults.getGate = gate;
  const query = f.api.observe("a1"); await new Promise(resolve => setImmediate(resolve)); f.api.close(); gate.resolve();
  await assert.rejects(query, code("persistence-unknown")); delete f.faults.getGate;
  assert.equal(JSON.parse(rawDocument(f)).attempts[0].state, "prepared"); assert.equal(f.counters.dbCloses, 0);
});
for (const fault of ["unknown", "getter", "proxy", "revoked", "native-id", "budget-bool", "usage-bool", "route-control", "route-surrogate", "identity-uppercase"]) test(`closed input ${fault} fails without external getter or SQL`, async t => {
  const f = await fixture(t); let value = input(), reads = 0;
  if (fault === "unknown") value.prompt = secret;
  if (fault === "getter") Object.defineProperty(value, "taskId", { enumerable: true, get() { reads++; throw new Error(secret); } });
  if (fault === "proxy") value = new Proxy(value, {});
  if (fault === "revoked") { const p = Proxy.revocable(value, {}); p.revoke(); value = p.proxy; }
  if (fault === "native-id") value.nativeTaskId = "4";
  if (fault === "budget-bool") value.budget.reservationUnits = true;
  if (fault === "route-control") value.route.model = "bad\nmodel";
  if (fault === "route-surrogate") value.route.model = "\ud800";
  if (fault === "identity-uppercase") value.registryIdentity = "A".repeat(64);
  const before = f.counters.transactions;
  if (fault === "usage-bool") { const usage = settlement(); usage.usage.input = true; await assert.rejects(f.api.settle("missing", usage), code("input-invalid")); }
  else await assert.rejects(f.api.prepare(value), code("input-invalid"));
  assert.equal(f.counters.transactions, before); assert.equal(reads, 0);
});
test("IDs support fixed ASCII200 limit and Unicode model route is not restricted to ASCII", async t => {
  const { api } = await fixture(t); const value = input("a".repeat(200), "t".repeat(200), { route: { provider: "提供者", model: "模型/精确版本" }, budget: { ...input().budget, scopeId: "scope" } });
  await api.prepare(value); assert.equal((await api.observe(value.attemptId)).input.route.provider, "提供者");
  await assert.rejects(api.prepare({ ...value, attemptId: "b".repeat(201) }), code("input-invalid"));
});

for (const setting of ["journal_mode=DELETE", "synchronous=NORMAL"]) test(`every transaction revalidates ${setting} and refuses writes`, async t => {
  const f = await fixture(t); await f.api.prepare(input()); f.raw.exec("PRAGMA " + setting);
  const before = f.counters.writes;
  await assert.rejects(f.api.commitSending("a1"), code("persistence-unknown"));
  assert.equal(f.counters.writes, before); assert.equal(JSON.parse(rawDocument(f)).attempts[0].state, "prepared");
});
test("every transaction uses callback executor and checks settings before any table work", async t => {
  const f = await fixture(t); await f.api.prepare(input()); await f.api.notSent("a1");
  for (let at = 0; at < f.events.length; at++) if (f.events[at][0] === "begin") {
    assert.deepEqual(f.events[at + 1].slice(0, 2), ["get", "PRAGMA journal_mode"]);
    assert.deepEqual(f.events[at + 2].slice(0, 2), ["get", "PRAGMA synchronous"]);
  }
  assert.equal(f.counters.transactions, 3);
  for (const event of f.events) if (["run"].includes(event[0])) {
    assert(event[1].includes("?")); assert(event[2].length > 0);
  }
});
test("adapter swallowing own semantic error is not an acknowledged rollback", async t => {
  const f = await fixture(t); await f.api.prepare(input()); f.faults.swallowSemantic = true;
  await assert.rejects(f.api.prepare(input("a1", "other")), code("persistence-unknown"));
  delete f.faults.swallowSemantic; await assert.rejects(f.api.observe("a1"), code("persistence-unknown"));
});
test("failed initializer after create commit keeps its Promise, table and unknown without implicitly reopening", async t => {
  const f = databaseFixture(); t.after(() => f.cleanup()); f.faults.lostAck = new Error(secret);
  const init = createModelAttemptStore({ database: f.database, deploymentIdentity: deployment, mode: "create" });
  const first = init(); await assert.rejects(first, code("persistence-unknown")); const count = f.counters.transactions;
  delete f.faults.lostAck; assert.equal(init(), first); await assert.rejects(init(), code("persistence-unknown")); assert.equal(f.counters.transactions, count);
  const active = await fixture(t, "active", f); await active.api.prepare(input());
});
test("close while preparation awaits first read aborts its transaction and does not clear previous tombstones", async t => {
  const f = await fixture(t); await f.api.prepare(input()); await f.api.notSent("a1");
  const gate = defer(); f.faults.getGate = gate;
  const prepared = f.api.prepare(input("a2")); await new Promise(resolve => setImmediate(resolve)); f.api.close(); gate.resolve();
  await assert.rejects(prepared, code("persistence-unknown")); delete f.faults.getGate;
  const document = JSON.parse(rawDocument(f)); assert.equal(document.attempts.length, 1); assert.equal(document.attempts[0].state, "not-sent");
});
test("4096 tombstones consume capacity permanently instead of being recycled", async t => {
  const f = await fixture(t), document = JSON.parse(rawDocument(f));
  document.tasks = [{ taskId: "task", scopeId: "scope-task", maxCalls: 4, maxCostUnits: 100 }];
  document.attempts = Array.from({ length: 4096 }, (_, index) => ({ input: input("a" + String(index).padStart(5, "0")), state: "not-sent", result: null, settlement: null }));
  overwrite(f, canonical(document));
  await assert.rejects(f.api.prepare(input("zz-new")), code("capacity-full"));
  assert.equal((await f.api.snapshot("task")).calls, 0); assert.equal((await f.api.snapshot("task")).attempts.length, 4096);
  assert.equal((await f.api.observe("a00000")).state, "not-sent");
});
test("8MiB canonical write limit is a known rolled-back capacity rejection retaining prior rows", async t => {
  const f = await fixture(t), document = JSON.parse(rawDocument(f));
  const taskId = "t".repeat(200), scopeId = "s".repeat(200);
  const value = input("a".repeat(200), taskId, { route: { provider: "中".repeat(256), model: "文".repeat(256) }, budget: { scopeId, maxCalls: 4096, maxCostUnits: 100, reservationUnits: 1 } });
  document.tasks = [{ taskId, scopeId, maxCalls: 4096, maxCostUnits: 100 }];
  const row = { input: value, state: "not-sent", result: null, settlement: null };
  const bytes = Buffer.byteLength(canonical(row), "utf8") + 1;
  const count = Math.floor((8 * 1024 * 1024 - Buffer.byteLength(canonical(document), "utf8") - 500) / bytes);
  assert(count < 4096);
  document.attempts = Array.from({ length: count }, (_, index) => ({ ...row, input: { ...value, attemptId: "a" + String(index).padStart(8, "0") + "x".repeat(191) } }));
  const raw = canonical(document); assert(Buffer.byteLength(raw) <= 8 * 1024 * 1024); overwrite(f, raw);
  await assert.rejects(f.api.prepare({ ...value, attemptId: "z".repeat(200) }), code("capacity-full"));
  assert.equal(rawDocument(f), raw); assert.equal((await f.api.observe(document.attempts[0].input.attemptId)).state, "not-sent");
});
for (const field of ["attempts", "tasks"]) test(`more than4096 ${field} is corrupt persistence, not empty state`, async t => {
  const f = await fixture(t), document = JSON.parse(rawDocument(f));
  if (field === "tasks") document.tasks = Array.from({ length: 4097 }, (_, index) => ({ taskId: "task" + index, scopeId: "scope" + index, maxCalls: 1, maxCostUnits: 1 }));
  else document.attempts = Array.from({ length: 4097 }, (_, index) => ({ input: input("a" + index), state: "not-sent", result: null, settlement: null }));
  overwrite(f, canonical(document)); await assert.rejects(f.api.snapshot("task"), code("persistence-unknown"));
});
for (const shape of ["mode-missing", "mode-unknown", "proxy", "getter", "database-proxy", "method-getter"]) test(`factory ${shape} fails before SQL/private-field read`, t => {
  const f = databaseFixture(); t.after(() => f.cleanup()); let reads = 0;
  let configuration = { database: f.database, deploymentIdentity: deployment, mode: "create" };
  Object.defineProperty(f.database, "db", { get() { reads++; throw new Error(secret); } });
  if (shape === "mode-missing") delete configuration.mode;
  if (shape === "mode-unknown") configuration.mode = "repair";
  if (shape === "proxy") configuration = new Proxy(configuration, {});
  if (shape === "getter") Object.defineProperty(configuration, "deploymentIdentity", { enumerable: true, get() { reads++; throw new Error(secret); } });
  if (shape === "database-proxy") configuration.database = new Proxy(f.database, {});
  if (shape === "method-getter") Object.defineProperty(f.database, "get", { get() { reads++; throw new Error(secret); } });
  assert.throws(() => createModelAttemptStore(configuration), code("input-invalid")); assert.equal(f.counters.transactions, 0); assert.equal(reads, 0);
});
test("different logical task budgets remain explicit and repeated native labels never project authority", async t => {
  const { api } = await fixture(t);
  const a = await api.prepare(input("a1", "logical-a")), b = await api.prepare(input("b1", "logical-b"));
  assert.equal(a.input.nativeTaskId, b.input.nativeTaskId); assert.equal(a.input.nativeConversationId, b.input.nativeConversationId);
  assert.equal((await api.snapshot("logical-a")).chargedCostUnits, "20"); assert.equal((await api.snapshot("logical-b")).chargedCostUnits, "20");
  assert.equal(Object.hasOwn(a, "approved"), false); assert.equal(Object.hasOwn(a, "owner"), false);
});

test("original transaction body cannot be bypassed by own call executing callback on fake handle", async () => {
  let getter = 0, spy = 0, original = 0, fakeWrites = 0;
  const database = { async transaction(callback) { original++; assert.equal(this, database); assert.equal(typeof callback, "function"); throw Error(secret); }, async get() { throw Error(secret); } };
  Object.defineProperty(database.transaction, "call", { get() { getter++; return async (receiver, callback) => {
    spy++; assert.equal(receiver, database);
    const handle = { async exec(sql) { assert.equal(this, handle); assert(sql.startsWith("CREATE TABLE")); fakeWrites++; },
      async run(sql, ...params) { assert.equal(this, handle); assert(sql.startsWith("INSERT INTO")); assert.equal(params[0], 1); fakeWrites++; },
      async get(sql) { assert.equal(this, handle); if (sql === "PRAGMA journal_mode") return { journal_mode: "wal" }; if (sql === "PRAGMA synchronous") return { synchronous: 2 };
        assert(sql.includes("sqlite_master")); return { count: 0, type: null, name: null, tableName: null, sql: null }; } };
    return callback(handle);
  }; } });
  const initialize = createModelAttemptStore({ database, deploymentIdentity: deployment, mode: "create" }); let caught;
  try { await initialize(); } catch (error) { caught = error; }
  assert.deepEqual({ getter, spy, original, fakeWrites }, { getter: 0, spy: 0, original: 1, fakeWrites: 0 });
  assert(code("persistence-unknown")(caught));
});
