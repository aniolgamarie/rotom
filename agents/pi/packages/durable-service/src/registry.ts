// 仅有限 registry/execute 准入；真实 owner、读取根与 backend 资格由独立控制面负责。
import { types } from "node:util";
import { createDurableCallIdentityBridge } from "./call-identity.ts";
import { createDurableModelDispatch, createDurableSdkSimpleModelDispatch } from "./provider.ts";
import { createDurablePhaseTasks } from "./phase-tasks.ts";
import { createDurablePhaseReader } from "./phase-reader.ts";

const applyOriginal = Reflect.apply;

const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted").get;
const HEX = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const BAD = /[\p{Cc}\p{Cf}\p{Cs}]/u;
const builtinNames = ["pi.generation", "pi.tool", "pi.compaction"];
// 仅当前模块实例内的原对象单次消费；不提供跨进程持久资格。
const consumed = new WeakSet();
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
function failure() {
  const value = new Error("readonly-unavailable");
  Object.defineProperty(value, "code", Object.assign(Object.create(null), { value: "readonly-unavailable", enumerable: true }));
  return value;
}
function require(value) { if (!value) throw failure(); }
function object(value) { require(value && typeof value === "object" && !types.isProxy(value)); return value; }
function own(value, key) {
  object(value);
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  require(descriptor && Object.hasOwn(descriptor, "value")); return descriptor.value;
}
function data(value, keys) {
  object(value); require([Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const names = Reflect.ownKeys(value);
  require(names.length === keys.length && names.every(key => typeof key === "string" && keys.includes(key)));
  const result = Object.create(null);
  for (const key of keys) { const descriptor = Object.getOwnPropertyDescriptor(value, key); require(descriptor?.enumerable && Object.hasOwn(descriptor, "value")); result[key] = descriptor.value; }
  return result;
}
function shape(value, allowed, required = []) {
  object(value); require([Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const names = Reflect.ownKeys(value); require(names.every(key => typeof key === "string" && allowed.includes(key)) && required.every(key => names.includes(key)));
  for (const key of names) { const descriptor = Object.getOwnPropertyDescriptor(value, key); require(descriptor?.enumerable && Object.hasOwn(descriptor, "value")); }
  return value;
}
function method(value, key) {
  require(value && ["object", "function"].includes(typeof value) && !types.isProxy(value));
  for (let current = value; current && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    require(!types.isProxy(current)); const descriptor = Object.getOwnPropertyDescriptor(current, key);
    if (descriptor) { require(Object.hasOwn(descriptor, "value") && typeof descriptor.value === "function" && !types.isProxy(descriptor.value)); return descriptor.value; }
  }
  throw failure();
}
function list(value, maximum = 65536) {
  require(Array.isArray(value) && !types.isProxy(value) && Object.getPrototypeOf(value) === Array.prototype && value.length <= maximum && Reflect.ownKeys(value).length === value.length + 1);
  return Array.from({ length: value.length }, (_, index) => own(value, String(index)));
}
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
const same = (left, right) => canonical(left) === canonical(right);
function frozen(value) { if (value && typeof value === "object") { for (const child of Object.values(value)) frozen(child); Object.freeze(value); } return value; }
function nativeId(value) { require(Number.isSafeInteger(value) && value > 0); return value; }
function signal(value) { object(value); require(applyOriginal(aborted, value, []) === false); return value; }
function text(value, limit, empty = false) { require(typeof value === "string" && (empty || value.length > 0) && !BAD.test(value) && Buffer.byteLength(value, "utf8") <= limit); return value; }
function parameters(value, operation) {
  const selected = data(value, operation === "rotom_read" ? ["rootRef", "path"] : ["rootRef", "path", "query"]);
  require(typeof selected.rootRef === "string" && ID.test(selected.rootRef));
  text(selected.path, 4096);
  require(!selected.path.startsWith("/") && !selected.path.includes("\\") && (operation === "rotom_search" && selected.path === "." || selected.path.split("/").every(part => part && part !== "." && part !== "..")));
  if (operation === "rotom_search") text(selected.query, 4096);
  return frozen(selected);
}
function references(root) {
  const seen = new Set(), records = [];
  function visit(value) {
    if (!value || typeof value !== "object") return;
    object(value); if (seen.has(value)) return; seen.add(value); require(seen.size <= 4096);
    const keys = Reflect.ownKeys(value), descriptors = keys.map(key => Object.getOwnPropertyDescriptor(value, key));
    require(descriptors.every(descriptor => Object.hasOwn(descriptor, "value")));
    records.push({ value, prototype: Object.getPrototypeOf(value), keys, descriptors });
    for (const descriptor of descriptors) visit(descriptor.value);
  }
  visit(root);
  return () => {
    for (const record of records) {
      object(record.value); require(Object.getPrototypeOf(record.value) === record.prototype);
      const keys = Reflect.ownKeys(record.value); require(keys.length === record.keys.length && keys.every((key, index) => key === record.keys[index]));
      for (let index = 0; index < keys.length; index++) {
        const current = Object.getOwnPropertyDescriptor(record.value, keys[index]), original = record.descriptors[index];
        require(current && Object.hasOwn(current, "value") && current.value === original.value && current.enumerable === original.enumerable && current.writable === original.writable && current.configurable === original.configurable);
      }
    }
  };
}
const unavailable = () => frozen({ isError: true, content: [{ type: "text", text: "readonly-unavailable" }] });
function schema(search) {
  const properties = { rootRef: { type: "string", minLength: 1, maxLength: 200, pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$" }, path: { type: "string", minLength: 1, maxLength: 4096 } };
  if (search) properties.query = { type: "string", minLength: 1, maxLength: 4096 };
  return frozen({ type: "object", properties, required: Object.keys(properties), additionalProperties: false });
}

export function createDurableReadonlyRegistry(input) { return createReadonlyRegistry(input); }

function createReadonlyRegistry(input, wiring = null) {
  let cfg, createRegistry, defineTool, defineExtension, assistantToken, controlMethods, registry, registryMethods, snapshot, snapshotMethods, builtin, rootGuard, tokenGuard, extension, tools;
  let closed = false, checkSnapshot, finalSourceCheck, executionSnapshot, projectedRegistry, executionGuard;
  try {
    cfg = data(input, ["durable", "rootTask", "control", "verifyCurrent", "sourceIdentity", "registryIdentity"]);
    require(typeof cfg.sourceIdentity === "string" && HEX.test(cfg.sourceIdentity) && typeof cfg.registryIdentity === "string" && HEX.test(cfg.registryIdentity));
    require(typeof cfg.verifyCurrent === "function" && !types.isProxy(cfg.verifyCurrent));
    createRegistry = method(cfg.durable, "createRegistry"); defineTool = method(cfg.durable, "defineTool"); defineExtension = method(cfg.durable, "defineExtension"); assistantToken = own(cfg.durable, "AssistantEntry");
    require(own(assistantToken, "kind") === "pi.assistant"); tokenGuard = references(assistantToken);
    const rootDefinition = own(cfg.rootTask, "definition"); require(own(rootDefinition, "name") === "rotom.durable.request" && own(rootDefinition, "version") === 1); rootGuard = references(cfg.rootTask);
    const control = data(cfg.control, ["prepare", "check", "execute"]); controlMethods = Object.keys(control).map(name => ({ name, fn: method(cfg.control, name) }));
    require(synchronousTrue(cfg.verifyCurrent()));
    registry = applyOriginal(createRegistry, cfg.durable, []);
    registryMethods = ["snapshot", "install", "uninstall", "subscribe"].map(name => ({ name, fn: method(registry, name) }));
    const initial = applyOriginal(registryMethods[0].fn, registry, []); builtin = list(applyOriginal(method(initial, "tasks"), initial, []), 3);
    require(builtin.length === 3 && list(applyOriginal(method(initial, "installed"), initial, []), 0).length === 0 && list(applyOriginal(method(initial, "tools"), initial, []), 0).length === 0);
    for (let index = 0; index < 3; index++) { const definition = own(builtin[index], "definition"); require(own(definition, "name") === builtinNames[index] && own(definition, "version") === 1); }
    const builtinGuard = references(builtin);
    tools = ["rotom_read", "rotom_search"].map(operation => {
      const tool = frozen({ name: operation, description: operation === "rotom_read" ? "Read through the qualified readonly control" : "Search through the qualified readonly control", parameters: schema(operation === "rotom_search"), replay: "unsafe", execute: (args, api, context) => execute(operation, args, api, context) });
      require(applyOriginal(defineTool, cfg.durable, [tool]) === tool); return tool;
    });
    const hooks = wiring ? wiring.hooks(builtin) : null;
    extension = Object.freeze({ name: "rotom.durable.readonly", tools: Object.freeze([...tools]), tasks: Object.freeze([cfg.rootTask]), ...(hooks ? { hooks } : {}) });
    // 只冻结自有extension容器；上面的 RootTask 不能递归冻结。
    require(applyOriginal(defineExtension, cfg.durable, [extension]) === extension);
    applyOriginal(registryMethods[1].fn, registry, [extension]); snapshot = applyOriginal(registryMethods[0].fn, registry, []);
    executionSnapshot = snapshot;
    snapshotMethods = ["installed", "tools", "tasks", "extension", "task", "sections"].map(name => ({ name, fn: method(snapshot, name) }));
    function snapshotCheck() {
      builtinGuard(); rootGuard(); tokenGuard();
      const installed = list(applyOriginal(snapshotMethods[0].fn, snapshot, []), 1); require(installed.length === 1 && installed[0] === extension);
      const available = list(applyOriginal(snapshotMethods[1].fn, snapshot, []), 2); require(available.length === 2);
      for (let index = 0; index < 2; index++) { const row = data(available[index], ["extension", "tool"]); require(row.extension === extension && row.tool === tools[index]); }
      const tasks = list(applyOriginal(snapshotMethods[2].fn, snapshot, []), 4); require(tasks.length === 4 && tasks.every((task, index) => task === [...builtin, cfg.rootTask][index]));
      require(applyOriginal(snapshotMethods[3].fn, snapshot, [extension.name]) === extension && list(applyOriginal(snapshotMethods[5].fn, snapshot, []), 0).length === 0);
      for (const task of tasks) require(applyOriginal(snapshotMethods[4].fn, snapshot, [own(own(task, "definition"), "name")]) === task);
    }
    checkSnapshot = snapshotCheck;
    if (wiring) finalSourceCheck = () => {
      // snapshot 的最后同步调用之后仅核 own 数据/原方法，不再进入外来 callback。
      const current = data(input, Object.keys(cfg)); require(Object.keys(cfg).every(key => current[key] === cfg[key]));
      require(method(cfg.durable, "createRegistry") === createRegistry && method(cfg.durable, "defineTool") === defineTool && method(cfg.durable, "defineExtension") === defineExtension && own(cfg.durable, "AssistantEntry") === assistantToken);
      data(cfg.control, controlMethods.map(item => item.name));
      for (const item of controlMethods) require(method(cfg.control, item.name) === item.fn);
      for (const item of registryMethods) require(method(registry, item.name) === item.fn);
      for (const item of snapshotMethods) require(method(snapshot, item.name) === item.fn);
      builtinGuard(); rootGuard(); tokenGuard(); if (executionGuard) executionGuard(); require(!closed);
    };
    if (wiring?.project) {
      const projected = data(wiring.project(registry, snapshot, finalSourceCheck), ["registry", "snapshot"]);
      projectedRegistry = projected.registry; executionSnapshot = projected.snapshot; executionGuard = references(executionSnapshot);
    }
    check();
  } catch { closed = true; if (wiring) wiring.fail(); throw failure(); }
  return Object.freeze({ registry: projectedRegistry ?? registry, check, close() { closed = true; } });
  function check() {
    return wiring?.qualify ? wiring.qualify(checkBase) : checkBase();
  }
  function checkBase() {
    try {
      if (wiring) wiring.origin();
      require(!closed && synchronousTrue(cfg.verifyCurrent()));
      const current = data(input, Object.keys(cfg)); require(Object.keys(cfg).every(key => current[key] === cfg[key]));
      require(method(cfg.durable, "createRegistry") === createRegistry && method(cfg.durable, "defineTool") === defineTool && method(cfg.durable, "defineExtension") === defineExtension && own(cfg.durable, "AssistantEntry") === assistantToken);
      data(cfg.control, controlMethods.map(item => item.name));
      for (const item of controlMethods) require(method(cfg.control, item.name) === item.fn);
      for (const item of registryMethods) require(method(registry, item.name) === item.fn);
      require(applyOriginal(registryMethods[0].fn, registry, []) === snapshot);
      for (const item of snapshotMethods) require(method(snapshot, item.name) === item.fn);
      checkSnapshot(); if (wiring) { wiring.origin(); finalSourceCheck(); } require(!closed); return true;
    } catch { closed = true; if (wiring) wiring.fail(); throw failure(); }
  }
  async function execute(operation, original, api, context) {
    try {
      if (wiring?.beforeExecute) wiring.beforeExecute();
      check(); object(api); object(context);
      const selected = parameters(original, operation), taskId = nativeId(own(api, "taskId")), conversationId = nativeId(own(api, "conversationId")), callId = text(own(api, "callId"), 200);
      const getTask = method(api, "getTask"), commit = method(api, "commit"), originalSignal = signal(wiring?.readContextSignal ? wiring.readContextSignal(context) : context.abortSignal);
      let toolRecord, generationRecord, entry, checkpoint, toolInput, ownerId, readFailed = false;
      function guard() {
        check(); require(own(api, "taskId") === taskId && own(api, "conversationId") === conversationId && own(api, "callId") === callId && own(api, "registry") === executionSnapshot);
        require(method(api, "getTask") === getTask && method(api, "commit") === commit && signal(wiring?.readContextSignal ? wiring.readContextSignal(context) : context.abortSignal) === originalSignal && same(parameters(original, operation), selected));
        if (toolRecord) require(same(tool(toolRecord), { ownerId, input: toolInput, checkpoint }));
        if (generationRecord) generation(generationRecord);
        if (entry) require(same(rawCall(entry), selected));
        // Context 公共 getter / verifyCurrent 等同步回调后再核入口；最后只读原生/own 数据。
        check(); require(!readFailed && !closed && signal(originalSignal) === originalSignal);
        require(own(api, "taskId") === taskId && own(api, "conversationId") === conversationId && own(api, "callId") === callId && own(api, "registry") === executionSnapshot);
        require(method(api, "getTask") === getTask && method(api, "commit") === commit && same(parameters(original, operation), selected));
        if (toolRecord) require(same(tool(toolRecord), { ownerId, input: toolInput, checkpoint }));
        if (generationRecord) generation(generationRecord);
        if (entry) require(same(rawCall(entry), selected));
      }
      async function awaited(invoke) {
        let value;
        try { value = await invoke(); } catch { guard(); throw failure(); }
        guard(); return value;
      }
      function tool(record) {
        shape(record, ["id", "conversationId", "kind", "version", "input", "owner", "background", "abortRequested", "state", "memos"]); require(own(record, "id") === taskId && own(record, "kind") === "pi.tool" && own(record, "version") === 1 && own(record, "conversationId") === conversationId && own(record, "background") === false && own(record, "abortRequested") === false);
        const ownerId = nativeId(own(record, "owner")), input = data(own(record, "input"), ["assistant", "callId"]); nativeId(input.assistant); require(input.callId === callId);
        const state = data(own(record, "state"), ["status", "checkpoint"]); require(state.status === "running");
        const checkpoint = data(state.checkpoint, ["phase", "arguments", "replay"]); require(checkpoint.phase === "execute" && checkpoint.replay === "unsafe"); checkpoint.arguments = parameters(checkpoint.arguments, operation);
        return { ownerId, input, checkpoint };
      }
      function generation(record) {
        shape(record, ["id", "conversationId", "kind", "version", "input", "owner", "background", "abortRequested", "state", "memos"]); require(own(record, "id") === ownerId && own(record, "kind") === "pi.generation" && own(record, "version") === 1 && own(record, "conversationId") === conversationId && own(record, "background") === false && own(record, "abortRequested") === false);
        require(["pending", "running", "waiting"].includes(own(own(record, "state"), "status")));
      }
      function rawCall(record) {
        shape(record, ["id", "conversationId", "kind", "model", "data", "head", "edits", "byTaskId"], ["id", "conversationId", "kind", "model", "byTaskId"]);
        require(own(record, "id") === toolInput.assistant && own(record, "conversationId") === conversationId && own(record, "kind") === "pi.assistant" && own(record, "byTaskId") === ownerId);
        const messages = list(own(record, "model"), 4096); require(messages.length > 0);
        const message = shape(messages[0], ["role", "content", "api", "provider", "model", "responseModel", "responseId", "providerThinkingLevel", "thinkingLevel", "diagnostics", "usage", "stopReason", "deferred", "errorMessage", "rawStopReason", "endTurn", "timestamp"], ["role", "content"]);
        require(own(message, "role") === "assistant");
        const calls = [];
        for (const content of list(own(message, "content"), 4096)) {
          object(content); const kind = own(content, "type");
          if (kind === "text") shape(content, ["type", "text", "textSignature"], ["type"]);
          else if (kind === "thinking") shape(content, ["type", "thinking", "thinkingSignature", "redacted"], ["type"]);
          else {
            require(kind === "toolCall"); shape(content, ["type", "id", "name", "arguments", "thoughtSignature", "namespace"], ["type", "id"]);
            if (own(content, "id") === callId) calls.push(content);
          }
        }
        require(calls.length === 1); const call = calls[0]; require(own(call, "name") === operation && !Object.hasOwn(call, "namespace"));
        if (Object.hasOwn(call, "thoughtSignature")) { const signature = own(call, "thoughtSignature"); require(typeof signature === "string" && Buffer.byteLength(signature, "utf8") <= 256 * 1024); }
        return parameters(own(call, "arguments"), operation);
      }
      guard(); toolRecord = await awaited(() => applyOriginal(getTask, api, [taskId, context])); const facts = tool(toolRecord); ownerId = facts.ownerId; toolInput = facts.input; checkpoint = facts.checkpoint; guard();
      require(same(checkpoint.arguments, selected)); generationRecord = await awaited(() => applyOriginal(getTask, api, [ownerId, context])); guard();
      let callbackResult, callbackCount = 0, callbackCompleted = false, readLive = true;
      try {
        const returned = await awaited(() => applyOriginal(commit, api, [tx => {
          callbackCount++;
          if (!readLive || callbackCount !== 1) readFailed = true;
          const pending = (async () => {
            require(readLive && !readFailed && callbackCount === 1); guard();
            const readEntry = method(tx, "entry");
            const raw = await awaited(() => applyOriginal(readEntry, tx, [assistantToken, toolInput.assistant]));
            require(readLive && !readFailed && callbackCount === 1); guard(); require(method(tx, "entry") === readEntry);
            entry = raw; const copied = rawCall(entry); require(same(copied, selected));
            callbackResult = frozen({ nativeAssistantEntryId: toolInput.assistant, nativeGenerationTaskId: ownerId, parameters: copied });
            callbackCompleted = true; return callbackResult;
          })();
          // 破坏契约的 SDK 若丢弃 pending，也不能留下未观察的迟到拒绝。
          pending.catch(() => { readFailed = true; }); return pending;
        }, context]));
        guard(); require(!readFailed && callbackCount === 1 && callbackCompleted && callbackResult && returned === callbackResult);
      } finally { readLive = false; }
      guard();
      toolRecord = await awaited(() => applyOriginal(getTask, api, [taskId, context])); guard(); generationRecord = await awaited(() => applyOriginal(getTask, api, [ownerId, context])); guard();
      const invocation = frozen({ schema: 1, operation, parameters: selected, sourceIdentity: cfg.sourceIdentity, registryIdentity: cfg.registryIdentity,
        nativeToolTaskId: taskId, nativeGenerationTaskId: ownerId, nativeConversationId: conversationId, nativeAssistantEntryId: toolInput.assistant, nativeCallId: callId });
      const ticket = await awaited(() => applyOriginal(controlMethods[0].fn, cfg.control, [invocation])); guard(); object(ticket);
      require(synchronousTrue(applyOriginal(controlMethods[1].fn, cfg.control, [ticket, invocation]))); guard(); require(!consumed.has(ticket)); consumed.add(ticket);
      const result = await awaited(() => applyOriginal(controlMethods[2].fn, cfg.control, [ticket, invocation, originalSignal])); guard();
      require(synchronousTrue(applyOriginal(controlMethods[1].fn, cfg.control, [ticket, invocation]))); guard();
      const value = data(result, ["text"]); require(typeof value.text === "string" && !/\p{Cs}/u.test(value.text) && !value.text.includes("\0") && Buffer.byteLength(value.text, "utf8") <= 256 * 1024);
      const reply = frozen({ content: [{ type: "text", text: value.text }] });
      guard(); return reply;
    } catch { return unavailable(); }
  }
}


// 显式组合工厂；旧六字段工厂不安装身份 hooks，也不能被热升级。
export function createDurableReadonlyModelRegistry(input) {
  const keys = ["durable", "rootTask", "control", "verifyCurrent", "sourceIdentity", "registryIdentity", "modelDispatch"];
  const modelKeys = ["models", "ai", "store", "model", "authorize", "resultFacts", "limits"];
  let cfg, dispatchInput, selected, bridge, bridgeMethods, bridgeGuard, readonly, dispatch, hookMethod, generationToken, compactionToken, hookGuards = [];
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    if (readonly) readonly.close();
    if (bridge) applyOriginal(bridgeMethods.close, bridge, []);
    if (dispatch) dispatch.close();
  }
  function descriptorBinding(target, names) {
    data(target, names);
    const prototype = Object.getPrototypeOf(target), original = names.map(name => Object.getOwnPropertyDescriptor(target, name));
    return () => {
      const current = data(target, names); require(Object.getPrototypeOf(target) === prototype);
      for (let index = 0; index < names.length; index++) {
        require(descriptorSame(Object.getOwnPropertyDescriptor(target, names[index]), original[index]));
        require(current[names[index]] === original[index].value);
      }
    };
  }
  let topBinding, modelBinding, modelDescriptor;
  let prepare, commitSending, recordResult, settle, authorize, collector, modelGuard, limitsGuard, streamSimple, completeSimple, createStream;
  function origin() {
    require(!closed); topBinding(); modelBinding(); bridgeGuard();
    require(method(cfg.durable, "hook") === hookMethod && own(cfg.durable, "GenerationTask") === generationToken && own(cfg.durable, "CompactionTask") === compactionToken);
    for (const name of ["take", "check", "close"]) require(method(bridge, name) === bridgeMethods[name]);
    require(method(selected.store, "prepare") === prepare && method(selected.store, "commitSending") === commitSending);
    require(method(selected.store, "recordResult") === recordResult && method(selected.store, "settle") === settle);
    for (const guard of hookGuards) guard();
    // 最后入口只读捕获的原数据/方法；不再调用外来 callback 或提前触发 provider.close。
    modelGuard(); limitsGuard();
    require(method(selected.models, "streamSimple") === streamSimple && method(selected.models, "completeSimple") === completeSimple && method(selected.ai, "createAssistantMessageEventStream") === createStream);
  }
  function check() {
    try { origin(); readonly.check(); origin(); return true; }
    catch { close(); throw failure(); }
  }
  function factsOrigin() {
    try {
      // 已关闭也能核已经发生的事实来源；不重新核桥活性或授予执行权。
      object(input); require(descriptorSame(Object.getOwnPropertyDescriptor(input, "modelDispatch"), modelDescriptor));
      modelBinding(); require(own(input, "modelDispatch") === dispatchInput);
      require(own(dispatchInput, "store") === selected.store && own(dispatchInput, "resultFacts") === collector);
      require(method(selected.store, "recordResult") === recordResult && method(selected.store, "settle") === settle);
    } catch { close(); throw failure(); }
  }
  try {
    cfg = data(input, keys); topBinding = descriptorBinding(input, keys);
    dispatchInput = cfg.modelDispatch; selected = data(dispatchInput, modelKeys); modelBinding = descriptorBinding(dispatchInput, modelKeys);
    modelDescriptor = Object.getOwnPropertyDescriptor(input, "modelDispatch");
    authorize = selected.authorize; collector = selected.resultFacts;
    modelGuard = references(selected.model); limitsGuard = references(selected.limits);
    streamSimple = method(selected.models, "streamSimple"); completeSimple = method(selected.models, "completeSimple"); createStream = method(selected.ai, "createAssistantMessageEventStream");
    require(typeof authorize === "function" && !types.isProxy(authorize) && typeof collector === "function" && !types.isProxy(collector));
    prepare = method(selected.store, "prepare"); commitSending = method(selected.store, "commitSending"); recordResult = method(selected.store, "recordResult"); settle = method(selected.store, "settle");
    hookMethod = method(cfg.durable, "hook"); generationToken = own(cfg.durable, "GenerationTask"); compactionToken = own(cfg.durable, "CompactionTask");
    bridge = createDurableCallIdentityBridge(); bridgeMethods = { take: method(bridge, "take"), check: method(bridge, "check"), close: method(bridge, "close") }; bridgeGuard = references(bridge);
    const readonlyInput = Object.create(null); for (const key of keys.slice(0, -1)) readonlyInput[key] = cfg[key];
    readonly = createReadonlyRegistry(readonlyInput, { origin, fail: close, hooks(builtin) {
      require(generationToken === builtin[0] && compactionToken === builtin[2]);
      const registrations = [[generationToken, bridge.generationHooks], [compactionToken, bridge.compactionHooks]].map(([task, handlers]) => {
        const registration = applyOriginal(hookMethod, cfg.durable, [task, handlers]), shape = data(registration, ["task", "handlers"]);
        require(shape.task === own(own(task, "definition"), "name") && shape.handlers === handlers);
        hookGuards.push(references(registration)); return registration;
      });
      return Object.freeze(registrations);
    } });
    const bridgeFacade = Object.freeze({
      take(signal, operation) { check(); return applyOriginal(bridgeMethods.take, bridge, [signal, operation]); },
      check(signal, operation, identity) { check(); return applyOriginal(bridgeMethods.check, bridge, [signal, operation, identity]); },
    });
    async function boundAwait(binding, invoke) {
      binding(); let value;
      try { value = await invoke(); } catch (error) { binding(); throw error; }
      binding(); return value;
    }
    const storeFacade = Object.freeze({
      prepare(...args) { return boundAwait(check, () => applyOriginal(prepare, selected.store, [...args])); },
      commitSending(...args) { return boundAwait(check, () => applyOriginal(commitSending, selected.store, [...args])); },
      recordResult(...args) { return boundAwait(factsOrigin, () => applyOriginal(recordResult, selected.store, [...args])); },
      settle(...args) { return boundAwait(factsOrigin, () => applyOriginal(settle, selected.store, [...args])); },
    });
    dispatch = createDurableModelDispatch({ models: selected.models, ai: selected.ai, bridge: bridgeFacade, store: storeFacade, model: selected.model, limits: selected.limits,
      authorize(...args) { return boundAwait(check, () => applyOriginal(authorize, dispatchInput, [...args])); },
      resultFacts(...args) { return boundAwait(factsOrigin, () => applyOriginal(collector, dispatchInput, [...args])); },
    });
    check();
    return Object.freeze({ registry: readonly.registry, models: dispatch.models, check, close });
  } catch { close(); throw failure(); }
}

// 独立 phase 路线；旧六字段与旧 hook 路线不使用以下构造/检查特许。
export function createDurableReadonlyPhaseModelRegistry(input) {
  const keys = ["durable", "rootTask", "control", "verifyCurrent", "sourceIdentity", "registryIdentity", "modelDispatch"];
  const modelKeys = ["models", "ai", "store", "model", "authorize", "resultFacts", "limits"];
  let cfg, selected, dispatchInput, phase, reader, readonly, dispatch, phaseMethods, innerFront, outerFront, outerRegistry;
  let ready = false, published = false, closed = false, checking = false, reading = false;
  let phaseConstruction = false, readerConstruction = false, readonlyConstruction = false, phaseCheckWindow = false;
  let readonlyPure, tokenGuard, frontGuard, registryGuard, phaseGuard, topGuard, modelBinding, modelDescriptor;
  let generationToken, compactionToken, toolToken, authorize, collector, prepare, commitSending, recordResult, settle;
  const sourceGuards = [];
  function close() {
    if (closed) return;
    closed = true; published = false;
    if (reader) reader.close();
    if (readonly) readonly.close();
    if (phase) phase.close();
    if (dispatch) dispatch.close();
  }
  function boundDescriptors(target, names) {
    data(target, names); const prototype = Object.getPrototypeOf(target), originals = names.map(name => Object.getOwnPropertyDescriptor(target, name));
    return () => { data(target, names); require(Object.getPrototypeOf(target) === prototype); for (let index = 0; index < names.length; index++) require(descriptorSame(Object.getOwnPropertyDescriptor(target, names[index]), originals[index])); };
  }
  function capturedMethod(target, name) {
    object(target); const chain = []; let fn;
    for (let current = target; current && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
      object(current); const prototype = Object.getPrototypeOf(current), original = Object.getOwnPropertyDescriptor(current, name); chain.push({ current, prototype, original });
      if (!fn && original) { require(Object.hasOwn(original, "value") && typeof original.value === "function" && !types.isProxy(original.value)); fn = original.value; }
    }
    require(fn);
    return { fn, guard() { for (const row of chain) { object(row.current); require(Object.getPrototypeOf(row.current) === row.prototype); const current = Object.getOwnPropertyDescriptor(row.current, name); require(row.original ? descriptorSame(current, row.original) : current === undefined); } } };
  }
  function captureMethod(target, name) { const captured = capturedMethod(target, name); sourceGuards.push(captured.guard); return captured.fn; }
  function originPure() {
    require(!closed); topGuard(); modelBinding(); for (const guard of sourceGuards) guard();
    if (phaseGuard) phaseGuard(); if (tokenGuard) tokenGuard(); if (frontGuard) frontGuard(); if (registryGuard) registryGuard(); require(!closed);
  }
  function lastPure() { originPure(); if (readonlyPure) readonlyPure(); originPure(); }
  function externalCurrent() { originPure(); require(synchronousTrue(applyOriginal(cfg.verifyCurrent, input, []))); lastPure(); return true; }
  function phaseVerify() {
    try {
      require(!closed && (phaseConstruction || ready && checking && phaseCheckWindow || published && !checking && !reading));
      return externalCurrent();
    } catch { close(); throw failure(); }
  }
  function qualify(checkBase) {
    if (closed || checking) { close(); throw failure(); }
    checking = true;
    try {
      originPure(); applyOriginal(checkBase, undefined, []);
      if (!ready) require(readonlyConstruction);
      else {
        phaseCheckWindow = true;
        try { require(applyOriginal(phaseMethods.check, phase, []) === true); }
        finally { phaseCheckWindow = false; }
      }
      lastPure(); return true;
    } catch { close(); throw failure(); }
    finally { phaseCheckWindow = false; checking = false; }
  }
  function internalCheck() {
    try { require(ready && !closed); readonly.check(); lastPure(); return true; }
    catch { close(); throw failure(); }
  }
  function readerVerify() {
    try { return readerConstruction ? externalCurrent() : internalCheck(); }
    catch { close(); throw failure(); }
  }
  function readCall(fn, receiver, args) {
    if (closed || reading || !ready && !readerConstruction) { close(); throw failure(); }
    reading = true;
    try { const value = applyOriginal(fn, receiver, args); lastPure(); return value; }
    catch { close(); throw failure(); }
    finally { reading = false; }
  }
  function publicCheck() {
    internalCheck(); readCall(method(reader, "check"), reader, []); lastPure(); return true;
  }
  function safeCode(error) {
    if (!error || typeof error !== "object" || types.isProxy(error)) return null;
    const descriptor = Object.getOwnPropertyDescriptor(error, "code"); return descriptor && Object.hasOwn(descriptor, "value") && typeof descriptor.value === "string" ? descriptor.value : null;
  }
  function bridgeCall(name, args) {
    internalCheck(); let value, caught;
    try { value = applyOriginal(phaseMethods[name], phase.bridge, args); } catch (error) { caught = error; }
    // 原 phase.check/take 的最后 Context getter 后只作跨源纯核，不再运行任意 callback。
    try { lastPure(); } catch { close(); throw failure(); }
    if (caught) { if (safeCode(caught) === "phase-unavailable") close(); throw caught; }
    return value;
  }
  function factsOrigin() {
    try {
      object(input); require(descriptorSame(Object.getOwnPropertyDescriptor(input, "modelDispatch"), modelDescriptor)); modelBinding();
      require(own(input, "modelDispatch") === dispatchInput && own(dispatchInput, "store") === selected.store && own(dispatchInput, "resultFacts") === collector);
      recordBinding.guard(); settleBinding.guard();
    } catch { close(); throw failure(); }
  }
  async function boundAwait(binding, operation) {
    binding(); let value;
    try { value = await operation(); } catch (error) { binding(); throw error; }
    binding(); return value;
  }
  let recordBinding, settleBinding;
  try {
    cfg = data(input, keys); topGuard = boundDescriptors(input, keys);
    dispatchInput = cfg.modelDispatch; selected = data(dispatchInput, modelKeys); modelBinding = boundDescriptors(dispatchInput, modelKeys); modelDescriptor = Object.getOwnPropertyDescriptor(input, "modelDispatch");
    require(typeof cfg.verifyCurrent === "function" && !types.isProxy(cfg.verifyCurrent));
    authorize = selected.authorize; collector = selected.resultFacts;
    require(typeof authorize === "function" && !types.isProxy(authorize) && typeof collector === "function" && !types.isProxy(collector));
    require(typeof cfg.sourceIdentity === "string" && HEX.test(cfg.sourceIdentity) && typeof cfg.registryIdentity === "string" && HEX.test(cfg.registryIdentity));
    data(cfg.control, ["prepare", "check", "execute"]); data(selected.limits, ["timeoutMs", "maxEvents"]);
    require(own(own(cfg.rootTask, "definition"), "name") === "rotom.durable.request" && own(own(cfg.rootTask, "definition"), "version") === 1);
    const sdkFields = ["GenerationTask", "CompactionTask", "ToolTask", "AssistantEntry"], sdkPrototype = Object.getPrototypeOf(object(cfg.durable));
    const sdkDescriptors = sdkFields.map(name => Object.getOwnPropertyDescriptor(cfg.durable, name));
    for (const descriptor of sdkDescriptors) require(descriptor && Object.hasOwn(descriptor, "value"));
    sourceGuards.push(() => { object(cfg.durable); require(Object.getPrototypeOf(cfg.durable) === sdkPrototype); for (let index = 0; index < sdkFields.length; index++) require(descriptorSame(Object.getOwnPropertyDescriptor(cfg.durable, sdkFields[index]), sdkDescriptors[index])); });
    [generationToken, compactionToken, toolToken] = sdkDescriptors.slice(0, 3).map(descriptor => descriptor.value);
    sourceGuards.push(references(cfg.rootTask), references(cfg.control), references(selected.model), references(selected.limits), references(generationToken), references(compactionToken), references(toolToken), references(sdkDescriptors[3].value));
    for (const name of ["createRegistry", "defineTool", "defineExtension", "defineTask"]) captureMethod(cfg.durable, name);
    for (const name of ["prepare", "check", "execute"]) captureMethod(cfg.control, name);
    for (const name of ["streamSimple", "completeSimple"]) captureMethod(selected.models, name);
    captureMethod(selected.ai, "createAssistantMessageEventStream"); prepare = captureMethod(selected.store, "prepare"); commitSending = captureMethod(selected.store, "commitSending");
    recordBinding = capturedMethod(selected.store, "recordResult"); settleBinding = capturedMethod(selected.store, "settle"); recordResult = recordBinding.fn; settle = settleBinding.fn;
    sourceGuards.push(recordBinding.guard, settleBinding.guard);
    phaseConstruction = true;
    try { phase = createDurablePhaseTasks({ durable: cfg.durable, verifyCurrent: phaseVerify }); }
    finally { phaseConstruction = false; }
    phaseMethods = { check: method(phase, "check"), take: method(phase.bridge, "take"), checkIdentity: method(phase.bridge, "check") };
    phaseGuard = references(phase);
    tokenGuard = references([phase.generationTask, phase.compactionTask]);
    const readonlyInput = Object.create(null); for (const key of keys.slice(0, -1)) readonlyInput[key] = cfg[key]; readonlyInput.verifyCurrent = externalCurrent;
    readonlyConstruction = true;
    try {
      readonly = createReadonlyRegistry(readonlyInput, { origin: originPure, fail: close, hooks(builtin) { require(builtin[0] === generationToken && builtin[1] === toolToken && builtin[2] === compactionToken); return null; }, qualify,
        beforeExecute() { if (!published || checking || reading || closed) { close(); throw failure(); } },
        readContextSignal(context) {
          if (!ready || !published || checking || reading || closed) { close(); throw failure(); }
          reading = true;
          try { const value = context.abortSignal; lastPure(); return value; }
          catch { close(); throw failure(); }
          finally { reading = false; }
        },
        project(base, baseSnapshot, pure) {
          readonlyPure = pure; readerConstruction = true;
          try {
            reader = createDurablePhaseReader({ base, generationTask: phase.generationTask, compactionTask: phase.compactionTask, verifyCurrent: readerVerify });
            const innerRegistry = reader.registry, innerSnapshot = method(innerRegistry, "snapshot"), innerSubscribe = method(innerRegistry, "subscribe");
            innerFront = applyOriginal(innerSnapshot, innerRegistry, []);
            const functions = Object.create(null); for (const name of ["installed", "extension", "tools", "sections", "tasks", "task"]) functions[name] = method(innerFront, name);
            outerFront = Object.freeze(Object.fromEntries(Object.keys(functions).map(name => [name, function(...args) { return readCall(functions[name], innerFront, args); }])));
            outerRegistry = Object.freeze({ snapshot() { const actual = readCall(innerSnapshot, innerRegistry, []); if (actual !== innerFront) { close(); throw failure(); } return outerFront; },
              subscribe(listener) {
                if (closed || reading) { close(); throw failure(); }
                reading = true; let disposer;
                try { disposer = applyOriginal(innerSubscribe, innerRegistry, [listener]); lastPure(); return disposer; }
                catch { close(); if (typeof disposer === "function" && !types.isProxy(disposer)) { try { applyOriginal(disposer, undefined, []); } catch {} } throw failure(); }
                finally { reading = false; }
              } });
            frontGuard = references(outerFront); registryGuard = references(outerRegistry); lastPure(); return Object.freeze({ registry: outerRegistry, snapshot: outerFront });
          } finally { readerConstruction = false; }
        } });
    } finally { readonlyConstruction = false; }
    const bridgeFacade = Object.freeze({ take(signal, operation) { return bridgeCall("take", [signal, operation]); }, check(signal, operation, identity) { return bridgeCall("checkIdentity", [signal, operation, identity]); } });
    const storeFacade = Object.freeze({ prepare(...args) { return boundAwait(internalCheck, () => applyOriginal(prepare, selected.store, args)); }, commitSending(...args) { return boundAwait(internalCheck, () => applyOriginal(commitSending, selected.store, args)); },
      recordResult(...args) { return boundAwait(factsOrigin, () => applyOriginal(recordResult, selected.store, args)); }, settle(...args) { return boundAwait(factsOrigin, () => applyOriginal(settle, selected.store, args)); } });
    dispatch = createDurableSdkSimpleModelDispatch({ models: selected.models, ai: selected.ai, bridge: bridgeFacade, store: storeFacade, model: selected.model, limits: selected.limits,
      authorize(...args) { return boundAwait(internalCheck, () => applyOriginal(authorize, dispatchInput, args)); }, resultFacts(...args) { return boundAwait(factsOrigin, () => applyOriginal(collector, dispatchInput, args)); } });
    ready = true; publicCheck(); lastPure(); published = true;
    return Object.freeze({ registry: outerRegistry, models: dispatch.models, check: publicCheck, close });
  } catch { close(); throw failure(); }
}
