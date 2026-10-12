// 仅受理关联：不执行 RootTask，不获取 owner，不证明模型发送资格。
import { types } from "node:util";
import { createHash } from "node:crypto";

const applyOriginal = Reflect.apply;

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const HEX = /^[0-9a-f]{64}$/;
const GRANTS = ["sourceIdentity", "authorizationIdentity", "registryIdentity", "policyIdentity", "readCapabilityIdentity", "inputSnapshotIdentity", "artifactIdentity"];
const semantic = new WeakSet();
const PromiseConstructor = Promise;
const promisePrototype = Promise.prototype;
const promiseThenDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "then");
const promiseConstructorDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "constructor");
const promisePrototypeDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, "prototype");
const promiseSpeciesDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, Symbol.species);
const nativeThen = promiseThenDescriptor.value;
const discardPromiseOutcome = () => undefined;
function descriptorSame(left, right) {
  if (!left || !right) return false;
  const keys = Reflect.ownKeys(right);
  return Reflect.ownKeys(left).length === keys.length && keys.every(key => Object.hasOwn(left, key) && left[key] === right[key]);
}
function synchronousTrue(value) {
  if (value === true) return true;
  if (types.isPromise(value)) {
    try {
      // 只观察同一捕获 realm 的普通 Promise；不触发未知 constructor/species getter。
      const ownConstructor = Object.getOwnPropertyDescriptor(value, "constructor");
      if (Object.getPrototypeOf(value) === promisePrototype
          && (!ownConstructor || Object.hasOwn(ownConstructor, "value") && ownConstructor.value === PromiseConstructor)
          && descriptorSame(Object.getOwnPropertyDescriptor(promisePrototype, "then"), promiseThenDescriptor)
          && descriptorSame(Object.getOwnPropertyDescriptor(promisePrototype, "constructor"), promiseConstructorDescriptor)
          && descriptorSame(Object.getOwnPropertyDescriptor(PromiseConstructor, "prototype"), promisePrototypeDescriptor)
          && descriptorSame(Object.getOwnPropertyDescriptor(PromiseConstructor, Symbol.species), promiseSpeciesDescriptor)) {
        applyOriginal(nativeThen, value, [discardPromiseOutcome, discardPromiseOutcome]);
      }
    } catch { /* 非标准 Promise 的观察未知；同步准入始终拒绝，不输出原错误。 */ }
  }
  // 不查看未知 thenable 的 then，也不等待任何 Promise 来授予权限。
  return false;
}

function error(code, known = false) {
  const value = new Error(code);
  Object.defineProperty(value, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  if (known) semantic.add(value);
  return value;
}
function fail(code = "input-invalid") { throw error(code, true); }
function own(value, key) {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  if (!descriptor || !descriptor.enumerable || !Object.hasOwn(descriptor, "value")) fail();
  return descriptor.value;
}
function data(value, keys) {
  if (!value || typeof value !== "object" || types.isProxy(value)) fail();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) fail();
  const names = Reflect.ownKeys(value);
  if (names.length !== keys.length || names.some(key => typeof key !== "string" || !keys.includes(key))) fail();
  const result = Object.create(null);
  for (const key of keys) result[key] = own(value, key);
  return result;
}
function method(value, key) {
  if (!value || !["object", "function"].includes(typeof value) || types.isProxy(value)) throw error("recovery-required");
  for (let current = value; current && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    if (types.isProxy(current)) throw error("recovery-required");
    const descriptor = Object.getOwnPropertyDescriptor(current, key);
    if (descriptor) {
      if (!Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "function" || types.isProxy(descriptor.value)) throw error("recovery-required");
      return descriptor.value;
    }
  }
  throw error("recovery-required");
}
function integer(value, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) { if (!Number.isSafeInteger(value) || value < minimum || value > maximum) fail(); return value; }
function hash(value) { if (typeof value !== "string" || !HEX.test(value)) fail(); return value; }
function id(value) { if (typeof value !== "string" || !ID.test(value)) fail(); return value; }
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
const digest = value => createHash("sha256").update(canonical(value)).digest("hex");
const same = (left, right) => canonical(left) === canonical(right);
function freeze(value) { if (value && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); } return value; }
function request(input, registryIdentity) {
  const result = data(input, ["requestId", "input", "grant", "route", "budget"]);
  id(result.requestId);
  result.input = data(result.input, ["text"]);
  if (typeof result.input.text !== "string" || /\p{Cs}/u.test(result.input.text) || Buffer.byteLength(result.input.text, "utf8") > 65536) fail();
  result.grant = data(result.grant, GRANTS);
  for (const key of GRANTS) hash(result.grant[key]);
  if (result.grant.registryIdentity !== registryIdentity) fail();
  result.route = data(result.route, ["provider", "model"]);
  for (const text of Object.values(result.route)) if (typeof text !== "string" || !text.trim() || text.length > 256 || Buffer.byteLength(text, "utf8") > 1024 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(text)) fail();
  result.budget = data(result.budget, ["scopeId", "maxCalls", "maxCostUnits"]);
  id(result.budget.scopeId); integer(result.budget.maxCalls, 1, 4096); integer(result.budget.maxCostUnits);
  if (Buffer.byteLength(canonical(result), "utf8") > 256 * 1024) fail();
  return result;
}
function array(value) {
  if (!Array.isArray(value) || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length > 4096) fail();
  if (Reflect.ownKeys(value).length !== value.length + 1) fail();
  return Array.from({ length: value.length }, (_, index) => own(value, String(index)));
}

export function createDurableRequestAdmission(config) {
  const cfg = data(config, ["session", "durable", "chord", "rootTask", "context", "mode", "verifyCurrent", "deploymentIdentity", "registryIdentity", "conversationId"]);
  hash(cfg.deploymentIdentity); hash(cfg.registryIdentity); integer(cfg.conversationId, 1);
  if (!cfg.context || typeof cfg.context !== "object" || types.isProxy(cfg.context)) fail();
  if (!["create", "active"].includes(cfg.mode) || typeof cfg.verifyCurrent !== "function" || types.isProxy(cfg.verifyCurrent)) fail();
  const definition = data(cfg.rootTask, ["definition"]).definition;
  // token 的定义只读公开身份；不检查或执行 RootTask 正文。
  if (!definition || types.isProxy(definition) || own(definition, "name") !== "rotom.durable.request" || own(definition, "version") !== 1) fail();
  const captures = [[cfg.session, "commit"], [cfg.session, "snapshot"], [cfg.session, "getTask"], [cfg.durable, "defineDoc"], [cfg.chord, "copyJson"]].map(([target, name]) => ({ target, name, fn: method(target, name) }));
  const [commit, snapshot, getTask, defineDoc, copyJson] = captures.map(item => item.fn);
  let closed = false, initialized = false, initializing, creationAttempt = null;
  const sentinel = () => ({ schema: 1, deploymentIdentity: null, registryIdentity: null, conversationId: null, rows: [] });
  const docDefinition = { kind: "rotom.durable.requests", version: 1, scope: "session", initial() {
    if (creationAttempt) creationAttempt.called = true;
    return sentinel();
  } };
  let token;
  try { token = applyOriginal(defineDoc, cfg.durable, [docDefinition]); } catch { throw error("recovery-required"); }
  const initial = method(docDefinition, "initial");
  function check(readOnly = false) {
    try {
      if (!readOnly && closed) throw error("recovery-required");
      if (!synchronousTrue(cfg.verifyCurrent())) { closed = true; throw error("current-invalid", true); }
      if (own(token, "definition") !== docDefinition || own(docDefinition, "kind") !== "rotom.durable.requests" || own(docDefinition, "version") !== 1 || own(docDefinition, "scope") !== "session" || method(docDefinition, "initial") !== initial) throw error("recovery-required");
      for (const item of captures) if (method(item.target, item.name) !== item.fn) throw error("recovery-required");
      if (own(cfg.rootTask, "definition") !== definition || own(definition, "name") !== "rotom.durable.request" || own(definition, "version") !== 1) throw error("recovery-required");
    } catch (failure) { closed = true; if (semantic.has(failure) && failure.code === "current-invalid") throw failure; throw error("recovery-required"); }
  }
  const identity = input => "rotom-durable:" + digest([cfg.deploymentIdentity, input.grant.sourceIdentity, input.requestId]);
  function document(input) {
    try {
      const value = data(input, ["schema", "deploymentIdentity", "registryIdentity", "conversationId", "rows"]);
      if (value.schema !== 1 || value.deploymentIdentity !== cfg.deploymentIdentity || value.registryIdentity !== cfg.registryIdentity || value.conversationId !== cfg.conversationId) fail();
      const native = new Set(); let previous = "";
      value.rows = array(value.rows).map(inputRow => {
        const row = data(inputRow, ["request", "taskId", "inputIdentity", "nativeTaskId"]);
        row.request = request(row.request, cfg.registryIdentity); integer(row.nativeTaskId, 1);
        if (row.taskId !== identity(row.request) || row.inputIdentity !== digest(row.request) || row.taskId <= previous || native.has(row.nativeTaskId)) fail();
        previous = row.taskId; native.add(row.nativeTaskId); return row;
      });
      if (Buffer.byteLength(canonical(value), "utf8") > 8 * 1024 * 1024) fail();
      return value;
    } catch { throw error("recovery-required"); }
  }
  const taskInput = row => ({ schema: 1, deploymentIdentity: cfg.deploymentIdentity, taskId: row.taskId, inputIdentity: row.inputIdentity, request: row.request });
  function task(value, row) {
    try {
      if (!value || typeof value !== "object" || types.isProxy(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail();
      if (own(value, "id") !== row.nativeTaskId || own(value, "kind") !== "rotom.durable.request" || own(value, "version") !== 1 || own(value, "conversationId") !== cfg.conversationId || own(value, "background") !== false || Object.hasOwn(value, "owner")) fail();
      const original = data(own(value, "input"), ["schema", "deploymentIdentity", "taskId", "inputIdentity", "request"]);
      original.request = request(original.request, cfg.registryIdentity);
      if (!same(original, taskInput(row))) fail();
    } catch { throw error("recovery-required"); }
  }
  const receipt = row => freeze({ schema: 1, taskId: row.taskId, inputIdentity: row.inputIdentity, nativeTaskId: row.nativeTaskId, nativeConversationId: cfg.conversationId });
  function rowFor(value, input) {
    const row = value.rows.find(row => row.taskId === identity(input));
    if (row && !same(row.request, input)) fail("request-conflict");
    return row;
  }
  async function sdkCall(fn, target, args) { try { return await applyOriginal(fn, target, [...args]); } catch { throw error("recovery-required"); } }
  const sdkRead = (fn, args) => sdkCall(fn, cfg.session, args);
  function extract(draft) { try { return applyOriginal(copyJson, cfg.chord, [draft]); } catch { throw error("recovery-required"); } }
  async function read() { check(true); const raw = await sdkRead(snapshot, [token, cfg.context]); check(true); return document(raw); }
  function initialize() {
    try { check(); } catch (failure) { return Promise.reject(failure); }
    if (initializing) return initializing;
    initializing = (async () => {
      let expected, callbackFailure, known = false;
      try {
        check();
        const existing = await sdkRead(snapshot, [token, cfg.context]); check();
        if (cfg.mode === "active") { document(existing); initialized = true; return; }
        if (existing !== undefined) { known = true; fail("store-exists"); }
        const observed = await applyOriginal(commit, cfg.session, [async tx => {
          try {
          check();
          const doc = method(tx, "doc");
          const marker = { called: false }; creationAttempt = marker;
          let draft;
          try { draft = await sdkCall(doc, tx, [token]); check(); }
          finally { creationAttempt = null; }
          if (method(tx, "doc") !== doc) throw error("recovery-required");
          const extracted = extract(draft);
          const candidate = data(extracted, ["schema", "deploymentIdentity", "registryIdentity", "conversationId", "rows"]);
          candidate.rows = array(candidate.rows);
          if (!marker.called || !same(candidate, sentinel())) fail("store-exists");
          check();
          draft.deploymentIdentity = cfg.deploymentIdentity; draft.registryIdentity = cfg.registryIdentity; draft.conversationId = cfg.conversationId;
          expected = Object.freeze(Object.create(null)); return expected;
          } catch (failure) { callbackFailure = failure; throw failure; }
        }, cfg.context]);
        check(); if (!expected || observed !== expected) throw error("recovery-required");
        initialized = true;
      } catch (failure) {
        const allowed = semantic.has(failure) && (known || failure === callbackFailure);
        if (!allowed || failure.code === "current-invalid") closed = true;
        throw allowed ? failure : error("recovery-required");
      }
    })();
    return initializing;
  }
  async function submit(original) {
    check(); const input = request(original, cfg.registryIdentity);
    if (!initialized) throw error("recovery-required");
    let staged = false, expected, callbackFailure, known = false;
    try {
      const before = await read(); check(); known = true; rowFor(before, input); known = false;
      const observed = await applyOriginal(commit, cfg.session, [async tx => {
        try {
        check();
        const methods = ["doc", "task", "createTask"].map(name => ({ name, fn: method(tx, name) }));
        const txCheck = () => { check(); for (const item of methods) if (method(tx, item.name) !== item.fn) throw error("recovery-required"); };
        const draft = await sdkCall(methods[0].fn, tx, [token]); txCheck();
        const value = document(extract(draft)); txCheck();
        let row = rowFor(value, input);
        if (row) {
          const existing = await sdkCall(methods[1].fn, tx, [row.nativeTaskId]); txCheck(); task(existing, row);
        } else {
          if (value.rows.length >= 4096) fail("capacity-exceeded");
          row = { request: input, taskId: identity(input), inputIdentity: digest(input), nativeTaskId: 1 };
          // 在第一个 task table write 前验证包括最终文档字节上界。
          const projected = { ...value, rows: [...value.rows, row].sort((a, b) => a.taskId.localeCompare(b.taskId)) };
          if (Buffer.byteLength(canonical(projected), "utf8") + 16 > 8 * 1024 * 1024) fail("capacity-exceeded");
          txCheck(); staged = true;
          row.nativeTaskId = await sdkCall(methods[2].fn, tx, [cfg.rootTask, taskInput(row), { ownership: { kind: "conversation" }, conversationId: cfg.conversationId, background: false }]);
          txCheck(); integer(row.nativeTaskId, 1);
          if (value.rows.some(old => old.nativeTaskId === row.nativeTaskId)) throw error("recovery-required");
          value.rows.push(row); value.rows.sort((a, b) => a.taskId < b.taskId ? -1 : 1); document(value); txCheck(); draft.rows = value.rows;
        }
        txCheck(); expected = receipt(row); return expected;
        } catch (failure) { callbackFailure = failure; throw failure; }
      }, cfg.context]);
      check(); if (!expected || observed !== expected) throw error("recovery-required"); return expected;
    } catch (failure) {
      const allowed = !staged && semantic.has(failure) && (known || failure === callbackFailure);
      if (!allowed || failure.code === "current-invalid") closed = true;
      if (allowed) throw failure;
      throw error("recovery-required");
    }
  }
  async function lookup(original) {
    const input = request(original, cfg.registryIdentity);
    try {
      const value = await read(), row = rowFor(value, input);
      if (!row) return null;
      const existing = await sdkRead(getTask, [row.nativeTaskId, cfg.context]); check(true); task(existing, row); return receipt(row);
    } catch (failure) { if (!semantic.has(failure)) closed = true; throw semantic.has(failure) ? failure : error("recovery-required"); }
  }
  return Object.freeze({ initialize, submit, lookup, close() { closed = true; } });
}
