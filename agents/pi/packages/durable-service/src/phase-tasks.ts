// 原公开 handlers 的转发与短期 phase 关联；不提供发送、预算或 owner 权限。
import { types } from "node:util";

const invoke = Reflect.apply;
const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted").get;
const PromiseConstructor = Promise, promisePrototype = Promise.prototype;
const thenDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "then");
const constructorDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "constructor");
const prototypeDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, "prototype");
const speciesDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, Symbol.species);
const nativeThen = thenDescriptor.value;
const discard = () => undefined;
function sameDescriptor(a, b) {
  return !!a && !!b && Reflect.ownKeys(a).length === Reflect.ownKeys(b).length
    && Reflect.ownKeys(b).every(key => Object.hasOwn(a, key) && a[key] === b[key]);
}
function synchronousTrue(value) {
  if (value === true) return true;
  if (types.isPromise(value)) {
    try {
      const ownConstructor = Object.getOwnPropertyDescriptor(value, "constructor");
      if (Object.getPrototypeOf(value) === promisePrototype
          && (!ownConstructor || Object.hasOwn(ownConstructor, "value") && ownConstructor.value === PromiseConstructor)
          && sameDescriptor(Object.getOwnPropertyDescriptor(promisePrototype, "then"), thenDescriptor)
          && sameDescriptor(Object.getOwnPropertyDescriptor(promisePrototype, "constructor"), constructorDescriptor)
          && sameDescriptor(Object.getOwnPropertyDescriptor(PromiseConstructor, "prototype"), prototypeDescriptor)
          && sameDescriptor(Object.getOwnPropertyDescriptor(PromiseConstructor, Symbol.species), speciesDescriptor)) invoke(nativeThen, value, [discard, discard]);
    } catch { /* 特殊 Promise 不安全观察；任何 Promise 都不准入。 */ }
  }
  return false;
}
function failure(code = "phase-unavailable") {
  const value = new Error(code);
  Object.defineProperty(value, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  return value;
}
function require(value) { if (!value) throw failure(); }
function object(value) { require(value && typeof value === "object" && !types.isProxy(value)); return value; }
function descriptor(value, key) {
  object(value); const found = Object.getOwnPropertyDescriptor(value, key);
  require(found && Object.hasOwn(found, "value")); return found;
}
function own(value, key) { return descriptor(value, key).value; }
function fn(value) { require(typeof value === "function" && !types.isProxy(value)); return value; }
function shape(value, allowed, required = allowed) {
  object(value); require([Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const keys = Reflect.ownKeys(value);
  require(keys.every(key => typeof key === "string" && allowed.includes(key)) && required.every(key => keys.includes(key)));
  for (const key of keys) require(descriptor(value, key).enumerable);
  return value;
}
function fields(value, names) {
  object(value); const records = names.map(name => [name, descriptor(value, name)]);
  return () => { object(value); for (const [name, original] of records) require(sameDescriptor(Object.getOwnPropertyDescriptor(value, name), original)); };
}
function references(root) {
  const seen = new Set(), records = []; let bytes = 0;
  function visit(value, depth) {
    require(depth <= 64);
    if (typeof value === "function") { fn(value); return; }
    if (!value || typeof value !== "object") {
      if (typeof value === "string") { bytes += Buffer.byteLength(value); require(bytes <= 1024 * 1024); }
      return;
    }
    object(value); if (seen.has(value)) return; seen.add(value); require(seen.size <= 4096);
    const prototype = Object.getPrototypeOf(value);
    require(prototype === Object.prototype || prototype === null || Array.isArray(value) && prototype === Array.prototype);
    const keys = Reflect.ownKeys(value); require(keys.length <= 4096 && keys.every(key => typeof key === "string"));
    for (const key of keys) { bytes += Buffer.byteLength(key); require(bytes <= 1024 * 1024); }
    const descriptors = keys.map(key => descriptor(value, key)); records.push({ value, prototype, keys, descriptors });
    for (const item of descriptors) visit(item.value, depth + 1);
  }
  visit(root, 0);
  return () => {
    for (const row of records) {
      object(row.value); require(Object.getPrototypeOf(row.value) === row.prototype);
      const keys = Reflect.ownKeys(row.value); require(keys.length === row.keys.length && keys.every((key, index) => key === row.keys[index]));
      for (let index = 0; index < keys.length; index++) require(sameDescriptor(Object.getOwnPropertyDescriptor(row.value, keys[index]), row.descriptors[index]));
    }
  };
}
function publicSignal(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw failure("signal-invalid");
  try { const state = invoke(aborted, value, []); if (state === false || state === true) return state; } catch { /* 原生品牌不符。 */ }
  throw failure("signal-invalid");
}
function contextProperty(context) {
  object(context);
  for (let current = context; current && current !== Object.prototype; current = Object.getPrototypeOf(current)) {
    object(current); const found = Object.getOwnPropertyDescriptor(current, "abortSignal");
    if (found) {
      require(Object.hasOwn(found, "value") || typeof found.get === "function" && !types.isProxy(found.get) && found.set === undefined);
      return { owner: current, descriptor: found };
    }
  }
  throw failure();
}
const nativeId = value => Number.isSafeInteger(value) && value > 0;

export function createDurablePhaseTasks(input) {
  if (arguments.length !== 1) throw failure();
  let closed = false, ready = false, busy = false, records = new WeakMap();
  const cancelled = new WeakSet(), localErrors = new WeakSet(), guards = [], tokens = [];
  let durable, verify, defineTask;
  function close() { closed = true; records = new WeakMap(); }
  function local(code) { const error = failure(code); localErrors.add(error); throw error; }
  function sources() {
    require(!closed); for (const guard of guards) guard();
    for (const token of tokens) { shape(token.value, ["definition"]); require(own(token.value, "definition") === token.definition); token.guard(); }
    require(!closed);
  }
  function checked(action = () => true, prepare = () => undefined) {
    if (closed || !ready || busy) { close(); throw failure(); }
    busy = true;
    try {
      sources(); const prepared = prepare();
      require(synchronousTrue(invoke(verify, input, []))); sources();
      const result = action(prepared); sources(); return result;
    } catch (error) {
      if (localErrors.has(error)) throw error;
      close(); throw failure();
    } finally { busy = false; }
  }
  function signalAlive(signal, association = false) {
    let isAborted;
    try { isAborted = publicSignal(signal); }
    catch { if (association) throw failure(); local("signal-invalid"); }
    if (isAborted || cancelled.has(signal)) { cancelled.add(signal); local("signal-invalid"); }
  }
  function capture(task, runtime, context, definition, phase) {
    object(task); object(runtime); object(context);
    const state = own(task, "state"), checkpoint = own(state, "checkpoint");
    require(nativeId(own(task, "id")) && nativeId(own(task, "conversationId"))
      && own(task, "kind") === own(definition, "name") && own(task, "version") === 1
      && own(state, "status") === "running" && own(checkpoint, "phase") === phase
      && own(runtime, "taskId") === own(task, "id") && own(runtime, "conversationId") === own(task, "conversationId"));
    const signal = own(runtime, "signal");
    const pure = [fields(task, ["id", "conversationId", "kind", "version", "state"]), fields(state, ["status", "checkpoint"]), fields(checkpoint, ["phase"]), fields(runtime, ["taskId", "conversationId", "signal"])];
    const property = contextProperty(context);
    function binding() {
      for (const guard of pure) guard();
      const current = contextProperty(context); require(current.owner === property.owner && sameDescriptor(current.descriptor, property.descriptor));
      const actual = Object.hasOwn(property.descriptor, "value") ? property.descriptor.value : invoke(property.descriptor.get, context, []);
      require(actual === signal); for (const guard of pure) guard();
      const after = contextProperty(context); require(after.owner === property.owner && sameDescriptor(after.descriptor, property.descriptor));
      signalAlive(signal, true); require(!closed);
    }
    return { signal, binding, taskId: own(task, "id"), conversationId: own(task, "conversationId"), kind: own(task, "kind"), version: own(task, "version") };
  }
  function begin(task, runtime, context, definition, phase, kind) {
    return checked(current => {
      current.binding(); const previous = records.get(current.signal);
      if (previous) require(!previous.lease.active && previous.runtime === runtime && previous.context === context
        && previous.taskId === current.taskId && previous.conversationId === current.conversationId && previous.kind === current.kind && previous.version === current.version);
      const lease = { active: true, retired: false, consumed: false, binding: current.binding,
        identity: Object.freeze({ schema: 1, nativeTaskId: current.taskId, nativeConversationId: current.conversationId, call_kind: kind }) };
      records.set(current.signal, { ...current, runtime, context, lease }); return lease;
    }, () => capture(task, runtime, context, definition, phase));
  }
  function take(signal, operation) {
    return checked(() => {
      signalAlive(signal); const record = records.get(signal), lease = record?.lease;
      if (!lease?.active) local("identity-unmatched");
      if (lease.retired) local("identity-retired");
      lease.binding();
      if (operation !== (lease.identity.call_kind === "generation" ? "streamSimple" : "completeSimple")) { lease.retired = true; local("operation-invalid"); }
      if (lease.consumed) { lease.retired = true; local("identity-consumed"); }
      lease.consumed = true; return lease.identity;
    });
  }
  function checkIdentity(signal, operation, identity) {
    return checked(() => {
      signalAlive(signal); const lease = records.get(signal)?.lease;
      if (!lease?.active || lease.identity !== identity) local("identity-stale");
      if (lease.retired) local("identity-retired");
      lease.binding();
      if (operation !== (lease.identity.call_kind === "generation" ? "streamSimple" : "completeSimple")) { lease.retired = true; local("operation-invalid"); }
      if (!lease.consumed) local("identity-stale");
      return true;
    });
  }
  function wrap(original, kind, targetPhase) {
    shape(original, ["definition"]); const definition = own(original, "definition");
    shape(definition, ["name", "version", "initial", "phases", "abort", "migrate", "hooks"], ["name", "version", "initial", "phases", "abort"]);
    require(own(definition, "name") === "pi." + kind && own(definition, "version") === 1);
    const originalPhases = own(definition, "phases"); object(originalPhases);
    require([Object.prototype, null].includes(Object.getPrototypeOf(originalPhases)));
    const names = Reflect.ownKeys(originalPhases); require(names.length > 0 && names.length <= 64 && names.includes(targetPhase));
    const phases = Object.create(null);
    for (const name of names) {
      require(typeof name === "string" && name.length > 0 && name.length <= 200 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(name));
      const handler = fn(own(originalPhases, name));
      phases[name] = name === targetPhase ? async function(task, runtime, context) {
        const lease = begin(task, runtime, context, definition, name, kind);
        try { return await invoke(handler, originalPhases, [task, runtime, context]); }
        finally { lease.active = false; }
      } : function(task, runtime, context) {
        checked(current => current.binding(), () => capture(task, runtime, context, definition, name));
        return invoke(handler, originalPhases, [task, runtime, context]);
      };
    }
    const ownDefinition = Object.assign(Object.create(null), { name: own(definition, "name"), version: 1, phases: Object.freeze(phases) });
    for (const name of ["initial", "abort", "migrate"]) {
      if (!Object.hasOwn(definition, name)) continue;
      const originalFunction = fn(own(definition, name));
      ownDefinition[name] = function(...args) { checked(); return invoke(originalFunction, definition, args); };
    }
    if (Object.hasOwn(definition, "hooks")) ownDefinition.hooks = own(definition, "hooks");
    guards.push(references(original));
    Object.freeze(ownDefinition);
    const token = invoke(defineTask, durable, [ownDefinition]);
    shape(token, ["definition"]); require(own(token, "definition") === ownDefinition);
    tokens.push({ value: token, definition: ownDefinition, guard: references(token) }); sources(); return token;
  }
  try {
    shape(input, ["durable", "verifyCurrent"]); durable = own(input, "durable"); verify = fn(own(input, "verifyCurrent")); object(durable);
    defineTask = fn(own(durable, "defineTask")); const generation = own(durable, "GenerationTask"), compaction = own(durable, "CompactionTask");
    const sdkPrototype = Object.getPrototypeOf(durable);
    guards.push(() => shape(input, ["durable", "verifyCurrent"]), fields(input, ["durable", "verifyCurrent"]),
      () => require(Object.getPrototypeOf(durable) === sdkPrototype),
      fields(durable, ["defineTask", "GenerationTask", "CompactionTask"]), references(generation), references(compaction));
    busy = true; require(synchronousTrue(invoke(verify, input, []))); sources();
    const generationTask = wrap(generation, "generation", "request"), compactionTask = wrap(compaction, "compaction", "summarize");
    sources(); busy = false; ready = true;
    return Object.freeze({ generationTask, compactionTask, bridge: Object.freeze({ take, check: checkIdentity }), check() { return checked(); }, close });
  } catch { close(); throw failure(); }
}
