// 非发送账本：只记录受信控制面提供的事实，不签 owner、模型资格或物理终止。
import { types } from "node:util";

const applyOriginal = Reflect.apply;

const TABLE = "rotom_model_attempt_ledger";
const DDL = "CREATE TABLE rotom_model_attempt_ledger (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), document TEXT NOT NULL)";
const MASTER = "SELECT count(*) AS count, min(type) AS type, min(name) AS name, min(tbl_name) AS tableName, min(sql) AS sql FROM sqlite_master WHERE name = ? OR tbl_name = ?";
const READ = "SELECT count(*) AS count, min(singleton) AS singleton, min(document) AS document FROM rotom_model_attempt_ledger";
const MAX_ROWS = 4096, MAX_BYTES = 8 * 1024 * 1024;
const HASH = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const STATES = ["prepared", "sending", "result-recorded", "settled", "not-sent"];
const semanticErrors = new WeakSet();
function error(code, semantic = false) {
  const value = new Error(code);
  Object.defineProperty(value, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  if (semantic) semanticErrors.add(value);
  return value;
}
const fail = code => { throw error(code, true); };
function data(value, keys) {
  if (!value || typeof value !== "object" || types.isProxy(value)) fail("input-invalid");
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) fail("input-invalid");
  const names = Reflect.ownKeys(value);
  if (names.length !== keys.length || names.some(key => typeof key !== "string" || !keys.includes(key))) fail("input-invalid");
  const result = Object.create(null);
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) fail("input-invalid");
    result[key] = descriptor.value;
  }
  return result;
}
function method(value, name) {
  if (!value || !["object", "function"].includes(typeof value) || types.isProxy(value)) throw error("persistence-unknown");
  for (let current = value; current !== null && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    if (types.isProxy(current)) throw error("persistence-unknown");
    const descriptor = Object.getOwnPropertyDescriptor(current, name);
    if (descriptor) {
      if (!Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "function" || types.isProxy(descriptor.value)) throw error("persistence-unknown");
      return descriptor.value;
    }
  }
  throw error("persistence-unknown");
}
function identifier(value) { if (typeof value !== "string" || !ID.test(value)) fail("input-invalid"); return value; }
function hash(value) { if (typeof value !== "string" || !HASH.test(value)) fail("input-invalid"); return value; }
function integer(value, positive = false, maximum = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < (positive ? 1 : 0) || value > maximum) fail("input-invalid");
  return value;
}
function route(input) {
  const value = data(input, ["provider", "model"]);
  for (const key of ["provider", "model"]) {
    const text = value[key];
    if (typeof text !== "string" || !text.trim() || text.length > 256 || Buffer.byteLength(text, "utf8") > 1024 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(text)) fail("input-invalid");
  }
  return value;
}
function prepareInput(input) {
  const value = data(input, ["attemptId", "taskId", "phase", "nativeTaskId", "nativeConversationId", "registryIdentity", "inputIdentity", "policyIdentity", "route", "budget"]);
  identifier(value.attemptId); identifier(value.taskId);
  if (!["generation", "compaction"].includes(value.phase)) fail("input-invalid");
  integer(value.nativeTaskId, true); integer(value.nativeConversationId, true);
  hash(value.registryIdentity); hash(value.inputIdentity); hash(value.policyIdentity);
  value.route = route(value.route);
  value.budget = data(value.budget, ["scopeId", "maxCalls", "maxCostUnits", "reservationUnits"]);
  identifier(value.budget.scopeId); integer(value.budget.maxCalls, true, MAX_ROWS); integer(value.budget.maxCostUnits); integer(value.budget.reservationUnits, true);
  return value;
}
function resultInput(input) {
  const value = data(input, ["resultRef", "outcome", "observedRoute"]);
  hash(value.resultRef);
  if (!["completed", "failed", "canceled"].includes(value.outcome)) fail("input-invalid");
  if (value.observedRoute !== null) value.observedRoute = route(value.observedRoute);
  return value;
}
function settlementInput(input) {
  const value = data(input, ["usage", "estimatedCostUnits"]);
  value.usage = data(value.usage, ["input", "output", "cacheRead", "cacheWrite"]);
  for (const count of Object.values(value.usage)) integer(count);
  integer(value.estimatedCostUnits);
  return value;
}
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
const same = (left, right) => canonical(left) === canonical(right);
function frozen(value) {
  if (value && typeof value === "object") { for (const child of Object.values(value)) frozen(child); Object.freeze(value); }
  return value;
}
function attemptView(row) { return { ...row, sendOutcome: row.state === "sending" ? "unknown" : null }; }
function projection(document, task) {
  const attempts = document.attempts.filter(row => row.input.taskId === task.taskId);
  let calls = 0, reserved = 0n, settled = 0n, overBudget = false;
  const outstanding = [];
  for (const row of attempts) {
    if (row.state === "not-sent") continue;
    calls++;
    if (row.state === "settled") {
      settled += BigInt(row.settlement.estimatedCostUnits);
      if (row.settlement.estimatedCostUnits > row.input.budget.reservationUnits) overBudget = true;
    } else { reserved += BigInt(row.input.budget.reservationUnits); outstanding.push(row.input.attemptId); }
  }
  const charged = reserved + settled;
  overBudget ||= calls > task.maxCalls || charged > BigInt(task.maxCostUnits);
  return { taskId: task.taskId, scopeId: task.scopeId, maxCalls: task.maxCalls, maxCostUnits: task.maxCostUnits, calls,
    chargedCostUnits: charged.toString(), reservedCostUnits: reserved.toString(), settledCostUnits: settled.toString(),
    outstandingAttemptId: outstanding[0] ?? null, overBudget, attempts: attempts.map(attemptView) };
}
function decode(raw, deploymentIdentity) {
  try {
    if (typeof raw !== "string" || Buffer.byteLength(raw, "utf8") > MAX_BYTES) throw error("persistence-unknown");
    const document = data(JSON.parse(raw), ["schema", "deploymentIdentity", "tasks", "attempts"]);
    if (document.schema !== 1 || typeof document.schema !== "number" || document.deploymentIdentity !== deploymentIdentity
        || !Array.isArray(document.tasks) || !Array.isArray(document.attempts)
        || document.tasks.length > MAX_ROWS || document.attempts.length > MAX_ROWS || canonical(document) !== raw) throw error("persistence-unknown");
    const tasks = new Map(), scopes = new Set(); let previous = null;
    document.tasks = document.tasks.map(input => {
      const task = data(input, ["taskId", "scopeId", "maxCalls", "maxCostUnits"]);
      identifier(task.taskId); identifier(task.scopeId); integer(task.maxCalls, true, MAX_ROWS); integer(task.maxCostUnits);
      if (previous !== null && task.taskId <= previous || scopes.has(task.scopeId)) throw error("persistence-unknown");
      previous = task.taskId; tasks.set(task.taskId, task); scopes.add(task.scopeId); return task;
    });
    previous = null;
    const counts = new Map(), outstanding = new Set();
    document.attempts = document.attempts.map(input => {
      const row = data(input, ["input", "state", "result", "settlement"]);
      row.input = prepareInput(row.input);
      if (previous !== null && row.input.attemptId <= previous || !STATES.includes(row.state)) throw error("persistence-unknown");
      previous = row.input.attemptId;
      const task = tasks.get(row.input.taskId), budget = row.input.budget;
      if (!task || task.scopeId !== budget.scopeId || task.maxCalls !== budget.maxCalls || task.maxCostUnits !== budget.maxCostUnits) throw error("persistence-unknown");
      counts.set(task.taskId, (counts.get(task.taskId) ?? 0) + 1);
      if (["prepared", "sending", "result-recorded"].includes(row.state)) {
        if (outstanding.has(task.taskId)) throw error("persistence-unknown");
        outstanding.add(task.taskId);
      }
      if (["result-recorded", "settled"].includes(row.state)) row.result = resultInput(row.result);
      else if (row.result !== null) throw error("persistence-unknown");
      if (row.state === "settled") {
        row.settlement = settlementInput(row.settlement);
        if (!same(row.result.observedRoute, row.input.route)) throw error("persistence-unknown");
      } else if (row.settlement !== null) throw error("persistence-unknown");
      return row;
    });
    if (document.tasks.some(task => !counts.has(task.taskId))) throw error("persistence-unknown");
    return document;
  } catch { throw error("persistence-unknown"); }
}

export function createModelAttemptStore(input) {
  let selected, database, deploymentIdentity, mode, transaction, get;
  try {
    selected = data(input, ["database", "deploymentIdentity", "mode"]);
    ({ database, deploymentIdentity, mode } = selected); hash(deploymentIdentity);
    if (!["create", "active", "settlement"].includes(mode)) fail("input-invalid");
    transaction = method(database, "transaction"); get = method(database, "get");
  } catch { fail("input-invalid"); }
  let initialization, retired = false;
  function unknown() { retired = true; throw error("persistence-unknown"); }
  function binding() {
    if (retired) throw error("persistence-unknown");
    try {
      const current = data(input, ["database", "deploymentIdentity", "mode"]);
      if (current.database !== database || current.deploymentIdentity !== deploymentIdentity || current.mode !== mode
          || method(database, "transaction") !== transaction || method(database, "get") !== get) unknown();
    } catch { unknown(); }
  }
  function executor(handle) {
    const functions = { exec: method(handle, "exec"), run: method(handle, "run"), get: method(handle, "get") };
    return async function call(name, sql, ...params) {
      binding();
      try {
        for (const key of Object.keys(functions)) if (method(handle, key) !== functions[key]) unknown();
        const result = await applyOriginal(functions[name], handle, [sql, ...params]);
        binding();
        for (const key of Object.keys(functions)) if (method(handle, key) !== functions[key]) unknown();
        return result;
      } catch { unknown(); }
    };
  }
  async function checks(read) {
    try {
      if (data(await read("PRAGMA journal_mode"), ["journal_mode"]).journal_mode !== "wal"
          || data(await read("PRAGMA synchronous"), ["synchronous"]).synchronous !== 2) unknown();
    } catch { unknown(); }
  }
  async function load(read, creating = false) {
    let master;
    try {
      master = data(await read(MASTER, TABLE, TABLE), ["count", "type", "name", "tableName", "sql"]);
    } catch { unknown(); }
    if (!Number.isSafeInteger(master.count) || master.count < 0) unknown();
    if (creating) {
      if (master.count === 0 && [master.type, master.name, master.tableName, master.sql].some(value => value !== null)) unknown();
      if (master.count !== 0) fail("store-exists");
      return;
    }
    if (master.count !== 1 || master.type !== "table" || master.name !== TABLE || master.tableName !== TABLE || master.sql !== DDL) unknown();
    try {
      const row = data(await read(READ), ["count", "singleton", "document"]);
      if (row.count !== 1 || row.singleton !== 1) unknown();
      return decode(row.document, deploymentIdentity);
    } catch { unknown(); }
  }
  async function transact(action) {
    binding();
    let callbackError;
    try {
      const value = await applyOriginal(transaction, database, [async handle => {
        try {
          const call = executor(handle);
          const read = (sql, ...params) => call("get", sql, ...params);
          await checks(read);
          return await action(call, read);
        } catch (caught) {
          if (semanticErrors.has(caught) && !retired) callbackError = caught;
          throw caught;
        }
      }]);
      binding();
      // adapter 若吞掉 callback 异常并报告 commit 成功，不能把它当已回滚。
      if (callbackError) unknown();
      return value;
    } catch (caught) {
      if (callbackError && caught === callbackError && !retired) {
        binding();
        throw caught;
      }
      unknown();
    }
  }
  async function query(sql, ...params) {
    binding();
    try { const value = await applyOriginal(get, database, [sql, ...params]); binding(); return value; } catch { unknown(); }
  }
  async function write(call, document) {
    document.tasks.sort((a, b) => a.taskId < b.taskId ? -1 : a.taskId > b.taskId ? 1 : 0);
    document.attempts.sort((a, b) => a.input.attemptId < b.input.attemptId ? -1 : a.input.attemptId > b.input.attemptId ? 1 : 0);
    const raw = canonical(document);
    if (Buffer.byteLength(raw, "utf8") > MAX_BYTES) fail("capacity-full");
    decode(raw, deploymentIdentity);
    await call("run", "UPDATE rotom_model_attempt_ledger SET document = ? WHERE singleton = ?", raw, 1);
  }
  async function change(action) {
    return transact(async (call, read) => {
      const document = await load(read);
      const { value, changed } = action(document);
      if (changed) await write(call, document);
      return frozen(Object.hasOwn(value, "attempt") ? { ...value, attempt: attemptView(value.attempt) } : attemptView(value));
    });
  }
  function row(document, attemptId) {
    const value = document.attempts.find(entry => entry.input.attemptId === attemptId);
    if (!value) fail("attempt-missing");
    return value;
  }
  function writable() { binding(); if (mode === "settlement") fail("settlement-only"); }
  const api = Object.freeze({
    async prepare(input) {
      writable(); const captured = prepareInput(input);
      return change(document => {
        const old = document.attempts.find(row => row.input.attemptId === captured.attemptId);
        if (old) { if (!same(old.input, captured)) fail("attempt-conflict"); return { value: old, changed: false }; }
        if (document.attempts.length >= MAX_ROWS) fail("capacity-full");
        let task = document.tasks.find(row => row.taskId === captured.taskId);
        if (task) {
          if (task.scopeId !== captured.budget.scopeId || task.maxCalls !== captured.budget.maxCalls || task.maxCostUnits !== captured.budget.maxCostUnits) fail("budget-conflict");
        } else {
          if (document.tasks.length >= MAX_ROWS) fail("capacity-full");
          if (document.tasks.some(row => row.scopeId === captured.budget.scopeId)) fail("scope-conflict");
          task = { taskId: captured.taskId, scopeId: captured.budget.scopeId, maxCalls: captured.budget.maxCalls, maxCostUnits: captured.budget.maxCostUnits };
        }
        const usage = projection(document, task);
        if (usage.overBudget) fail("budget-exceeded");
        if (usage.outstandingAttemptId !== null) fail("attempt-outstanding");
        if (usage.calls + 1 > task.maxCalls || BigInt(usage.chargedCostUnits) + BigInt(captured.budget.reservationUnits) > BigInt(task.maxCostUnits)) fail("budget-exceeded");
        if (!document.tasks.includes(task)) document.tasks.push(task);
        const value = { input: captured, state: "prepared", result: null, settlement: null };
        document.attempts.push(value); return { value, changed: true };
      });
    },
    async commitSending(attemptId) {
      writable(); identifier(attemptId);
      return change(document => {
        const attempt = row(document, attemptId);
        if (attempt.state === "not-sent") fail("transition-invalid");
        const committedNow = attempt.state === "prepared";
        if (committedNow) attempt.state = "sending";
        return { value: { attempt, committedNow }, changed: committedNow };
      });
    },
    async notSent(attemptId) {
      binding(); identifier(attemptId);
      return change(document => {
        const value = row(document, attemptId);
        if (value.state === "not-sent") return { value, changed: false };
        if (value.state !== "prepared") fail("transition-invalid");
        value.state = "not-sent"; return { value, changed: true };
      });
    },
    async recordResult(attemptId, input) {
      binding(); identifier(attemptId); const captured = resultInput(input);
      return change(document => {
        const value = row(document, attemptId);
        if (value.result !== null) { if (!same(value.result, captured)) fail("result-conflict"); return { value, changed: false }; }
        if (value.state !== "sending") fail("transition-invalid");
        value.state = "result-recorded"; value.result = captured; return { value, changed: true };
      });
    },
    async settle(attemptId, input) {
      binding(); identifier(attemptId); const captured = settlementInput(input);
      return change(document => {
        const value = row(document, attemptId);
        if (value.settlement !== null) { if (!same(value.settlement, captured)) fail("settlement-conflict"); return { value, changed: false }; }
        if (value.state !== "result-recorded") fail("transition-invalid");
        if (value.result.observedRoute === null || !same(value.result.observedRoute, value.input.route)) fail("route-unresolved");
        value.state = "settled"; value.settlement = captured; return { value, changed: true };
      });
    },
    async observe(attemptId) { binding(); identifier(attemptId); const document = await load(query); binding(); return frozen(attemptView(row(document, attemptId))); },
    async snapshot(taskId) {
      binding(); identifier(taskId); const document = await load(query); binding(); const task = document.tasks.find(row => row.taskId === taskId);
      if (!task) fail("task-missing"); return frozen(projection(document, task));
    },
    close() { retired = true; },
  });
  async function initialize() {
    await transact(async (call, read) => {
      if (mode === "create") {
        await load(read, true);
        await call("exec", DDL);
        const raw = canonical({ schema: 1, deploymentIdentity, tasks: [], attempts: [] });
        await call("run", "INSERT INTO rotom_model_attempt_ledger (singleton, document) VALUES (?, ?)", 1, raw);
      } else await load(read);
    });
    return api;
  }
  return function initializeOnce() {
    if (initialization === undefined) initialization = Promise.resolve().then(initialize);
    return initialization;
  };
}
