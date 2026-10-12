// 固定公开 Reader 投影；原 token 和通知不是授权或物理停止证明。
import { types } from "node:util";

const invoke = Reflect.apply;
const PromiseConstructor = Promise, promisePrototype = Promise.prototype;
const thenDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "then");
const constructorDescriptor = Object.getOwnPropertyDescriptor(promisePrototype, "constructor");
const prototypeDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, "prototype");
const speciesDescriptor = Object.getOwnPropertyDescriptor(PromiseConstructor, Symbol.species);
const nativeThen = thenDescriptor.value, discard = () => undefined;
const names = ["pi.generation", "pi.tool", "pi.compaction", "rotom.durable.request"];
const methods = ["installed", "extension", "tools", "sections", "tasks", "task"];
function failure() {
  const error = new Error("phase-reader-unavailable");
  Object.defineProperty(error, "code", Object.assign(Object.create(null), { value: "phase-reader-unavailable", enumerable: true }));
  return error;
}
function require(value) { if (!value) throw failure(); }
function object(value) { require(value && typeof value === "object" && !types.isProxy(value)); return value; }
function fn(value) { require(typeof value === "function" && !types.isProxy(value)); return value; }
function sameDescriptor(a, b) {
  return !!a && !!b && Reflect.ownKeys(a).length === Reflect.ownKeys(b).length
    && Reflect.ownKeys(b).every(key => Object.hasOwn(a, key) && a[key] === b[key]);
}
function own(value, key) {
  object(value); const descriptor = Object.getOwnPropertyDescriptor(value, key);
  require(descriptor && Object.hasOwn(descriptor, "value")); return descriptor.value;
}
function shape(value, keys) {
  object(value); require([Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const actual = Reflect.ownKeys(value); require(actual.length === keys.length && actual.every(key => typeof key === "string" && keys.includes(key)));
  for (const key of actual) require(Object.getOwnPropertyDescriptor(value, key)?.enumerable && Object.hasOwn(Object.getOwnPropertyDescriptor(value, key), "value"));
}
function list(value, length) {
  object(value); require(Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype && value.length === length
    && Reflect.ownKeys(value).length === length + 1);
  const items = []; for (let index = 0; index < length; index++) items.push(own(value, String(index))); return items;
}
function references(root) {
  const seen = new Set(), records = []; let bytes = 0;
  function visit(value, depth) {
    require(depth <= 64);
    if (typeof value === "function") { fn(value); return; }
    if (typeof value === "string") { bytes += Buffer.byteLength(value); require(bytes <= 1024 * 1024); return; }
    if (!value || typeof value !== "object") return;
    object(value); if (seen.has(value)) return; seen.add(value); require(seen.size <= 4096);
    const prototype = Object.getPrototypeOf(value); require(prototype === Object.prototype || prototype === null || Array.isArray(value) && prototype === Array.prototype);
    const keys = Reflect.ownKeys(value); require(keys.every(key => typeof key === "string"));
    for (const key of keys) { bytes += Buffer.byteLength(key); require(bytes <= 1024 * 1024); }
    const descriptors = keys.map(key => Object.getOwnPropertyDescriptor(value, key)); require(descriptors.every(item => item && Object.hasOwn(item, "value")));
    records.push({ value, prototype, keys, descriptors }); for (const item of descriptors) visit(item.value, depth + 1);
  }
  visit(root, 0);
  return () => {
    for (const record of records) {
      object(record.value); require(Object.getPrototypeOf(record.value) === record.prototype);
      const current = Reflect.ownKeys(record.value); require(current.length === record.keys.length && current.every((key, index) => key === record.keys[index]));
      for (let index = 0; index < current.length; index++) require(sameDescriptor(Object.getOwnPropertyDescriptor(record.value, current[index]), record.descriptors[index]));
    }
  };
}
function method(value, name) {
  object(value); const chain = []; let original;
  for (let current = value; current && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    object(current); const prototype = Object.getPrototypeOf(current), descriptor = Object.getOwnPropertyDescriptor(current, name);
    chain.push({ current, prototype, descriptor });
    if (!original && descriptor) { require(Object.hasOwn(descriptor, "value")); original = fn(descriptor.value); }
  }
  require(original);
  return { original, guard() {
    for (const row of chain) {
      object(row.current); require(Object.getPrototypeOf(row.current) === row.prototype);
      const actual = Object.getOwnPropertyDescriptor(row.current, name);
      require(row.descriptor ? sameDescriptor(actual, row.descriptor) : actual === undefined);
    }
  } };
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
    } catch { /* 特殊 Promise 拒绝，不读未知 getter。 */ }
  }
  return false;
}
function task(value, name, provided = false) {
  shape(value, ["definition"]); const definition = own(value, "definition"); object(definition);
  require(own(definition, "name") === name && own(definition, "version") === 1);
  if (provided) {
    require([Object.prototype, null].includes(Object.getPrototypeOf(definition)));
    const keys = Reflect.ownKeys(definition), required = ["name", "version", "initial", "phases", "abort"];
    require(keys.every(key => typeof key === "string" && [...required, "migrate", "hooks"].includes(key)) && required.every(key => keys.includes(key)));
    for (const key of keys) { own(definition, key); require(Object.getOwnPropertyDescriptor(definition, key).enumerable); }
    fn(own(definition, "initial")); fn(own(definition, "abort")); if (keys.includes("migrate")) fn(own(definition, "migrate"));
    const phases = own(definition, "phases"); object(phases); require([Object.prototype, null].includes(Object.getPrototypeOf(phases)));
    const phaseNames = Reflect.ownKeys(phases); require(phaseNames.length > 0 && phaseNames.length <= 64 && phaseNames.includes(name === names[0] ? "request" : "summarize"));
    for (const key of phaseNames) { require(typeof key === "string" && key.length > 0 && key.length <= 200 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(key)); fn(own(phases, key)); }
  }
}

export function createDurablePhaseReader(input) {
  if (arguments.length !== 1) throw failure();
  let closed = false, busy = false, snapshot, expected, front;
  const guards = [];
  let base, generationTask, compactionTask, verify, snapshotMethod, subscribeMethod, snapshotMethods;
  function close() { closed = true; }
  function pure() { require(!closed); for (const guard of guards) guard(); require(!closed); }
  function call(record, receiver, args = []) {
    pure(); const result = invoke(record.original, receiver, args); pure(); return result;
  }
  function tables(first = false) {
    const containers = [], fresh = [];
    function read(name, args, count) {
      const value = call(snapshotMethods[name], snapshot, args);
      // 尚未返回的容器不能伪装原值；返回后立即捕获，在任何下一外来调用前复核。
      const guard = references(value); fresh.push(guard);
      for (const previous of fresh) previous(); pure();
      if (count !== undefined) { const selected = list(value, count); containers.push(guard); return selected; }
      return value;
    }
    const installed = read("installed", [], 1), tools = read("tools", [], 2), sections = read("sections", [], 0), tasks = read("tasks", [], 4);
    const extension = installed[0]; object(extension); require(own(extension, "name") === "rotom.durable.readonly");
    for (let index = 0; index < tools.length; index++) {
      shape(tools[index], ["extension", "tool"]); require(own(tools[index], "extension") === extension);
      require(own(own(tools[index], "tool"), "name") === ["rotom_read", "rotom_search"][index]);
    }
    for (let index = 0; index < tasks.length; index++) task(tasks[index], names[index]);
    require(generationTask !== tasks[0] && compactionTask !== tasks[2]);
    const selectedExtension = read("extension", ["rotom.durable.readonly"]); require(selectedExtension === extension);
    for (let index = 0; index < tasks.length; index++) require(read("task", [names[index]]) === tasks[index]);
    if (first) {
      expected = { installed, tools, sections, tasks, extension };
      guards.push(...containers);
    } else {
      require(installed[0] === expected.extension);
      for (let index = 0; index < tools.length; index++) require(own(tools[index], "extension") === own(expected.tools[index], "extension") && own(tools[index], "tool") === own(expected.tools[index], "tool"));
      for (let index = 0; index < tasks.length; index++) require(tasks[index] === expected.tasks[index]);
    }
    for (const guard of fresh) guard(); pure();
  }
  function validate() {
    pure(); require(synchronousTrue(invoke(verify, input, []))); pure();
    require(call(snapshotMethod, base) === snapshot); tables(); pure();
  }
  function guarded(action) {
    if (closed || busy) { close(); throw failure(); }
    busy = true;
    try { validate(); const result = action(); pure(); return result; }
    catch { close(); throw failure(); }
    finally { busy = false; }
  }
  function subscribe(listener) {
    return guarded(() => {
      fn(listener); let disposer;
      try {
        pure(); disposer = invoke(subscribeMethod.original, base, [listener]); fn(disposer); pure();
        validate(); return disposer;
      } catch {
        close();
        if (typeof disposer === "function" && !types.isProxy(disposer)) {
          try { invoke(disposer, undefined, []); } catch { /* 原清理回执未知，不重试。 */ }
        }
        throw failure();
      }
    });
  }
  try {
    shape(input, ["base", "generationTask", "compactionTask", "verifyCurrent"]);
    base = own(input, "base"); generationTask = own(input, "generationTask"); compactionTask = own(input, "compactionTask"); verify = fn(own(input, "verifyCurrent"));
    const prototype = Object.getPrototypeOf(input), keys = Reflect.ownKeys(input), descriptors = keys.map(key => Object.getOwnPropertyDescriptor(input, key));
    guards.push(() => { shape(input, keys); require(Object.getPrototypeOf(input) === prototype); for (let index = 0; index < keys.length; index++) require(sameDescriptor(Object.getOwnPropertyDescriptor(input, keys[index]), descriptors[index])); });
    task(generationTask, names[0], true); task(compactionTask, names[2], true); guards.push(references(generationTask), references(compactionTask));
    snapshotMethod = method(base, "snapshot"); subscribeMethod = method(base, "subscribe"); guards.push(snapshotMethod.guard, subscribeMethod.guard);
    busy = true; pure(); require(synchronousTrue(invoke(verify, input, []))); pure();
    snapshot = call(snapshotMethod, base); object(snapshot);
    snapshotMethods = Object.create(null);
    for (const name of methods) { snapshotMethods[name] = method(snapshot, name); guards.push(snapshotMethods[name].guard); }
    tables(true); pure();
    const selectedTasks = Object.freeze([generationTask, expected.tasks[1], compactionTask, expected.tasks[3]]);
    const installed = Object.freeze([...expected.installed]), tools = Object.freeze(expected.tools.map(row => Object.freeze({ extension: own(row, "extension"), tool: own(row, "tool") }))), sections = Object.freeze([]);
    front = Object.freeze({ installed() { return guarded(() => installed); }, extension(name) { return guarded(() => name === "rotom.durable.readonly" ? expected.extension : undefined); },
      tools() { return guarded(() => tools); }, sections() { return guarded(() => sections); }, tasks() { return guarded(() => selectedTasks); },
      task(name) { return guarded(() => { const index = names.indexOf(name); return index < 0 ? undefined : selectedTasks[index]; }); } });
    const registry = Object.freeze({ snapshot() { return guarded(() => front); }, subscribe });
    busy = false; return Object.freeze({ registry, check() { return guarded(() => true); }, close });
  } catch { close(); throw failure(); }
}
