// 首批仅公开 simple 派发；受信注入本身不证明 owner、严格输入或真实网络资格。
import { types } from "node:util";

const applyOriginal = Reflect.apply;

const MAX_BYTES = 8 * 1024 * 1024;
const OPTIONS = ["signal", "maxTokens", "reasoning", "temperature", "transport", "cacheRetention", "sessionId", "maxRetries", "timeoutMs", "maxRetryDelayMs"];
const CONFIG = ["models", "ai", "bridge", "store", "model", "authorize", "resultFacts", "limits"];
const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted").get;
const addListener = EventTarget.prototype.addEventListener, removeListener = EventTarget.prototype.removeEventListener;
function error(code) {
  const value = new Error(code);
  Object.defineProperty(value, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  return value;
}
function data(value, allowed, required = allowed) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw error("input-invalid");
  if (![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw error("input-invalid");
  const keys = Reflect.ownKeys(value);
  if (keys.some(key => typeof key !== "string" || !allowed.includes(key)) || required.some(key => !keys.includes(key))) throw error("input-invalid");
  return shallow(value);
}
function shallow(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw error("dispatch-unknown");
  const result = Object.create(null);
  for (const key of Reflect.ownKeys(value)) {
    if (typeof key !== "string") throw error("dispatch-unknown");
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) throw error("dispatch-unknown");
    Object.defineProperty(result, key, Object.assign(Object.create(null), { value: descriptor.value, enumerable: true, writable: true, configurable: true }));
  }
  return result;
}
function own(value, key) {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  if (!descriptor || !Object.hasOwn(descriptor, "value")) throw error("dispatch-unknown");
  return descriptor.value;
}
function pure(value, seen = new Set()) {
  if (value === null || ["string", "boolean"].includes(typeof value)) return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (!value || typeof value !== "object" || types.isProxy(value) || seen.has(value)) throw error("input-invalid");
  seen.add(value);
  let result;
  if (Array.isArray(value)) {
    const keys = Reflect.ownKeys(value);
    if (keys.length !== value.length + 1 || keys.some(key => key !== "length" && (typeof key !== "string" || !/^(0|[1-9][0-9]*)$/.test(key)))) throw error("input-invalid");
    result = [];
    for (let index = 0; index < value.length; index++) {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) throw error("input-invalid");
      result.push(pure(descriptor.value, seen));
    }
  } else {
    if (![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw error("input-invalid");
    result = shallow(value);
    for (const key of Object.keys(result)) result[key] = pure(result[key], seen);
  }
  seen.delete(value);
  return result;
}
function bounded(value) {
  const copy = pure(value);
  if (Buffer.byteLength(canonical(copy), "utf8") > MAX_BYTES) throw error("input-invalid");
  return copy;
}
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
function freeze(value) { if (value && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); } return value; }
function method(value, name) {
  if (!value || !["object", "function"].includes(typeof value) || types.isProxy(value)) throw error("input-invalid");
  for (let current = value; current !== null && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    if (types.isProxy(current)) throw error("input-invalid");
    const descriptor = Object.getOwnPropertyDescriptor(current, name);
    if (descriptor) {
      if (!Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "function" || types.isProxy(descriptor.value)) throw error("input-invalid");
      return descriptor.value;
    }
  }
  throw error("input-invalid");
}
function nativeSignal(signal) {
  if (!signal || typeof signal !== "object" || types.isProxy(signal) || applyOriginal(aborted, signal, []) !== false) throw error("dispatch-unknown");
  return signal;
}
function safeCode(value) {
  try {
    if (!value || typeof value !== "object" || types.isProxy(value)) return null;
    const descriptor = Object.getOwnPropertyDescriptor(value, "code");
    return descriptor && Object.hasOwn(descriptor, "value") && typeof descriptor.value === "string" ? descriptor.value : null;
  } catch { return null; }
}
function integer(value, maximum, positive = true) {
  if (!Number.isSafeInteger(value) || value < (positive ? 1 : 0) || value > maximum) throw error("input-invalid");
}
function text(value, maximum = 256) {
  if (typeof value !== "string" || !value.trim() || value.length > maximum || Buffer.byteLength(value, "utf8") > 1024 || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(value)) throw error("input-invalid");
}
function options(input, defaultCap) {
  const value = data(input, OPTIONS, defaultCap === undefined ? ["signal", "maxTokens", "maxRetries", "transport"] : ["signal", "maxRetries", "transport"]);
  if (defaultCap !== undefined && !Object.hasOwn(value, "maxTokens")) value.maxTokens = defaultCap;
  nativeSignal(value.signal); integer(value.maxTokens, Number.MAX_SAFE_INTEGER);
  if (value.maxRetries !== 0 || value.transport !== "sse") throw error("input-invalid");
  if (Object.hasOwn(value, "reasoning") && !["minimal", "low", "medium", "high", "xhigh", "max"].includes(value.reasoning)) throw error("input-invalid");
  if (Object.hasOwn(value, "temperature") && (typeof value.temperature !== "number" || !Number.isFinite(value.temperature))) throw error("input-invalid");
  if (Object.hasOwn(value, "cacheRetention") && !["none", "short", "long"].includes(value.cacheRetention)) throw error("input-invalid");
  if (Object.hasOwn(value, "sessionId")) text(value.sessionId);
  if (Object.hasOwn(value, "timeoutMs")) integer(value.timeoutMs, Number.MAX_SAFE_INTEGER);
  if (Object.hasOwn(value, "maxRetryDelayMs")) integer(value.maxRetryDelayMs, Number.MAX_SAFE_INTEGER, false);
  const signal = value.signal; delete value.signal;
  return { signal, pure: bounded(value) };
}
function prepare(value, identity, model) {
  const input = data(value, ["attemptId", "taskId", "phase", "nativeTaskId", "nativeConversationId", "registryIdentity", "inputIdentity", "policyIdentity", "route", "budget"]);
  const copy = bounded(input);
  data(copy.route, ["provider", "model"]); data(copy.budget, ["scopeId", "maxCalls", "maxCostUnits", "reservationUnits"]);
  for (const key of ["attemptId", "taskId"]) if (typeof copy[key] !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(copy[key])) throw error("dispatch-unknown");
  if (typeof copy.budget.scopeId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(copy.budget.scopeId)) throw error("dispatch-unknown");
  for (const key of ["registryIdentity", "inputIdentity", "policyIdentity"]) if (typeof copy[key] !== "string" || !/^[0-9a-f]{64}$/.test(copy[key])) throw error("dispatch-unknown");
  integer(copy.budget.maxCalls, 4096); integer(copy.budget.maxCostUnits, Number.MAX_SAFE_INTEGER, false); integer(copy.budget.reservationUnits, Number.MAX_SAFE_INTEGER);
  if (copy.nativeTaskId !== identity.nativeTaskId || copy.nativeConversationId !== identity.nativeConversationId || copy.phase !== identity.call_kind
      || copy.route.provider !== model.provider || copy.route.model !== model.id) throw error("dispatch-unknown");
  return freeze(copy);
}
function cleanMessage(message) {
  const fields = shallow(message);
  if (Object.hasOwn(fields, "errorMessage") && fields.errorMessage !== undefined) {
    if (typeof fields.errorMessage !== "string") throw error("dispatch-unknown");
    return { ...fields, errorMessage: "dispatch-unknown" };
  }
  return message;
}
function cleanEvent(event) {
  const fields = shallow(event);
  if (Object.hasOwn(fields, "partial") && fields.partial) {
    const partial = cleanMessage(fields.partial);
    if (partial !== fields.partial) return { ...fields, partial };
  }
  return event;
}

export function createDurableModelDispatch(input) { return createDispatch(input, false); }
export function createDurableSdkSimpleModelDispatch(input) { return createDispatch(input, true); }
function createDispatch(input, sdkSimple) {
  let cfg, fixedModel, fixedLimits, captured, defaultCap;
  try {
    cfg = data(input, CONFIG); fixedModel = bounded(cfg.model); text(fixedModel.provider); text(fixedModel.id); text(fixedModel.api);
    if (sdkSimple) { integer(fixedModel.maxTokens, Number.MAX_SAFE_INTEGER); defaultCap = fixedModel.maxTokens; }
    fixedLimits = data(cfg.limits, ["timeoutMs", "maxEvents"]); integer(fixedLimits.timeoutMs, 120000); integer(fixedLimits.maxEvents, 65536);
    if ([cfg.authorize, cfg.resultFacts].some(fn => typeof fn !== "function" || types.isProxy(fn))) throw error("input-invalid");
    captured = { streamSimple: method(cfg.models, "streamSimple"), completeSimple: method(cfg.models, "completeSimple"),
      create: method(cfg.ai, "createAssistantMessageEventStream"), take: method(cfg.bridge, "take"), check: method(cfg.bridge, "check"),
      prepare: method(cfg.store, "prepare"), commitSending: method(cfg.store, "commitSending"), recordResult: method(cfg.store, "recordResult"), settle: method(cfg.store, "settle") };
  } catch { throw error("input-invalid"); }
  const modelKey = canonical(fixedModel), limitsKey = canonical(fixedLimits), pending = new Set();
  let closed = false;
  function synthetic(code) {
    return { role: "assistant", content: [], api: fixedModel.api, provider: fixedModel.provider, model: fixedModel.id,
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      stopReason: "error", timestamp: Date.now(), errorMessage: code };
  }
  function close() { closed = true; for (const call of [...pending]) call.fail("dispatch-unknown"); }
  function factsBinding() {
    try {
      if (types.isProxy(input)) throw error("dispatch-unknown");
      const store = Object.getOwnPropertyDescriptor(input, "store"), collector = Object.getOwnPropertyDescriptor(input, "resultFacts");
      if (!store || !collector || !Object.hasOwn(store, "value") || !Object.hasOwn(collector, "value")
          || store.value !== cfg.store || collector.value !== cfg.resultFacts
          || method(cfg.store, "recordResult") !== captured.recordResult || method(cfg.store, "settle") !== captured.settle) throw error("dispatch-unknown");
    } catch { close(); throw error("dispatch-unknown"); }
  }
  function configuration() {
    try {
      const current = data(input, CONFIG);
      if (CONFIG.some(key => current[key] !== cfg[key]) || canonical(bounded(cfg.model)) !== modelKey || canonical(data(cfg.limits, ["timeoutMs", "maxEvents"])) !== limitsKey
          || method(cfg.models, "streamSimple") !== captured.streamSimple || method(cfg.models, "completeSimple") !== captured.completeSimple
          || method(cfg.ai, "createAssistantMessageEventStream") !== captured.create || method(cfg.bridge, "take") !== captured.take || method(cfg.bridge, "check") !== captured.check
          || method(cfg.store, "prepare") !== captured.prepare || method(cfg.store, "commitSending") !== captured.commitSending) throw error("dispatch-unknown");
      factsBinding();
    } catch { close(); throw error("dispatch-unknown"); }
  }
  function alive(call) {
    if (closed || call.done || Date.now() >= call.deadline) throw error("dispatch-unknown");
    nativeSignal(call.signal); configuration();
    if (applyOriginal(captured.check, cfg.bridge, [call.signal, call.snapshot.operation, call.identityOriginal]) !== true) throw error("dispatch-unknown");
    try {
      if (call.rawOptions) call.rawOptions();
      const currentOptions = options(call.original.options, defaultCap);
      if (currentOptions.signal !== call.signal || canonical(bounded({ model: call.original.model, context: call.original.context, options: currentOptions.pure })) !== call.requestKey) throw error("dispatch-unknown");
    } catch { close(); throw error("dispatch-unknown"); }
    if (Date.now() >= call.deadline || call.done || closed) throw error("dispatch-unknown");
  }
  async function gate(call, invoke) {
    alive(call);
    let value;
    try { value = await invoke(); } catch (caught) { if (safeCode(caught) === "persistence-unknown") close(); throw error("dispatch-unknown"); }
    alive(call); return value;
  }
  function control(stream) {
    const outer = stream ? applyOriginal(captured.create, cfg.ai, []) : null;
    const push = stream ? method(outer, "push") : null, end = stream ? method(outer, "end") : null;
    let resolve, reject;
    const promise = stream ? null : new Promise((yes, no) => { resolve = yes; reject = no; });
    if (promise) void promise.catch(() => {});
    const call = { outer, promise, done: false, timer: null, signal: null, deadline: Date.now() + fixedLimits.timeoutMs,
      finish(event, message) {
        if (call.done) return;
        call.done = true; clearTimeout(call.timer);
        if (call.signal) applyOriginal(removeListener, call.signal, ["abort", call.onAbort]);
        pending.delete(call);
        if (stream) { applyOriginal(push, outer, [event]); applyOriginal(end, outer, [message]); }
        else resolve(message);
      },
      fail(code) {
        if (call.done) return;
        if (stream) { const message = synthetic(code); call.finish({ type: "error", reason: "error", error: message }, message); }
        else { call.done = true; clearTimeout(call.timer); if (call.signal) applyOriginal(removeListener, call.signal, ["abort", call.onAbort]); pending.delete(call); reject(error(code)); }
      },
      publish(event) { if (!call.done) applyOriginal(push, outer, [cleanEvent(event)]); },
    };
    call.onAbort = () => call.fail("dispatch-unknown");
    pending.add(call); call.timer = setTimeout(() => call.fail("dispatch-unknown"), fixedLimits.timeoutMs);
    return call;
  }
  function capture(call, operation, model, context, inputOptions) {
    if (closed) throw error("dispatch-unknown"); configuration();
    const selected = options(inputOptions, defaultCap);
    const request = bounded({ model, context, options: selected.pure });
    if (canonical(request.model) !== modelKey) throw error("dispatch-unknown");
    const originalIdentity = applyOriginal(captured.take, cfg.bridge, [selected.signal, operation]);
    if (call.rawOptions) call.rawOptions();
    const identity = bounded(data(originalIdentity, ["schema", "nativeTaskId", "nativeConversationId", "call_kind"]));
    if (identity.schema !== 1 || !Number.isSafeInteger(identity.nativeTaskId) || identity.nativeTaskId < 1 || !Number.isSafeInteger(identity.nativeConversationId) || identity.nativeConversationId < 1
        || identity.call_kind !== (operation === "streamSimple" ? "generation" : "compaction")) throw error("dispatch-unknown");
    call.identityOriginal = originalIdentity;
    call.original = { model, context, options: inputOptions }; call.signal = selected.signal; call.requestKey = canonical(request);
    call.snapshot = freeze({ operation, identity, ...bounded(request) });
    call.args = { model: request.model, context: request.context, options: { ...request.options, signal: call.signal } };
    applyOriginal(addListener, call.signal, ["abort", call.onAbort, { once: true }]);
  }
  async function authorize(call) {
    return prepare(await gate(call, () => cfg.authorize(call.snapshot, call.signal)), call.snapshot.identity, fixedModel);
  }
  async function admission(call) {
    const first = await authorize(call);
    await gate(call, () => applyOriginal(captured.prepare, cfg.store, [first]));
    const second = await authorize(call); if (canonical(second) !== canonical(first)) throw error("dispatch-unknown");
    const committed = await gate(call, () => applyOriginal(captured.commitSending, cfg.store, [first.attemptId]));
    if (data(committed, ["attempt", "committedNow"]).committedNow !== true) throw error("dispatch-unknown");
    const third = await authorize(call); if (canonical(third) !== canonical(first)) throw error("dispatch-unknown");
    call.attemptId = first.attemptId;
  }
  async function persist(call, message) {
    factsBinding();
    let facts;
    try { facts = data(await cfg.resultFacts(call.snapshot, message, call.signal), ["result", "settlement"]); } catch (caught) { if (safeCode(caught) === "persistence-unknown") close(); throw error("dispatch-unknown"); }
    factsBinding(); const capturedFacts = bounded(facts);
    try {
      await applyOriginal(captured.recordResult, cfg.store, [call.attemptId, capturedFacts.result]); factsBinding();
      const observedRoute = capturedFacts.result.observedRoute;
      if (observedRoute === null || observedRoute.provider !== call.snapshot.model.provider || observedRoute.model !== call.snapshot.model.id) throw error("dispatch-unknown");
      if (capturedFacts.settlement !== null) { await applyOriginal(captured.settle, cfg.store, [call.attemptId, capturedFacts.settlement]); factsBinding(); }
    } catch (caught) { if (safeCode(caught) === "persistence-unknown") close(); throw error("dispatch-unknown"); }
  }
  function message(value) {
    const fields = shallow(value);
    if (own(fields, "role") !== "assistant" || !["stop", "length", "toolUse", "aborted", "error"].includes(own(fields, "stopReason")) || Object.hasOwn(fields, "deferred")) throw error("dispatch-unknown");
    return value;
  }
  async function consume(call, inner) {
    const iterate = method(inner, Symbol.asyncIterator), result = method(inner, "result"), iterator = applyOriginal(iterate, inner, []), next = method(iterator, "next");
    const completed = Promise.resolve(applyOriginal(result, inner, []));
    void completed.catch(() => call.fail("dispatch-unknown"));
    let terminal = null, count = 0, protocolFailed = false;
    for (;;) {
      const item = shallow(await applyOriginal(next, iterator, []));
      if (typeof own(item, "done") !== "boolean") throw error("dispatch-unknown");
      if (!call.done) { try { alive(call); } catch { call.fail("dispatch-unknown"); } }
      if (method(inner, Symbol.asyncIterator) !== iterate || method(inner, "result") !== result || method(iterator, "next") !== next) throw error("dispatch-unknown");
      if (item.done === true) break;
      const event = shallow(own(item, "value")); count++;
      own(event, "type");
      if (count > fixedLimits.maxEvents) { protocolFailed = true; call.fail("dispatch-unknown"); }
      if (terminal) { protocolFailed = true; call.fail("dispatch-unknown"); }
      if (event.type === "done" || event.type === "error") {
        const reason = own(event, "reason"), actual = message(own(event, event.type === "done" ? "message" : "error"));
        if (terminal || !(event.type === "done" ? ["stop", "length", "toolUse"] : ["aborted", "error"]).includes(reason)
            || reason !== own(shallow(actual), "stopReason")) protocolFailed = true;
        terminal = { event, message: actual };
      } else {
        if (typeof event.type !== "string") protocolFailed = true;
        if (!call.done && !protocolFailed) { alive(call); call.publish(item.value); }
      }
    }
    const actual = await completed;
    if (!call.done) { try { alive(call); } catch { call.fail("dispatch-unknown"); } }
    if (!terminal || protocolFailed || actual !== terminal.message || own(terminal.event, "reason") !== own(shallow(actual), "stopReason") || method(inner, "result") !== result) throw error("dispatch-unknown");
    await persist(call, actual);
    if (call.done) return;
    alive(call);
    message(actual);
    if (own(terminal.event, "reason") !== own(shallow(actual), "stopReason")) throw error("dispatch-unknown");
    const clean = cleanMessage(actual), event = { ...terminal.event, [terminal.event.type === "done" ? "message" : "error"]: clean };
    call.finish(event, clean);
  }
  async function run(call, operation) {
    try {
      await admission(call);
      // 最后同步检查与捕获原入口相邻；中间没有外来 await/hook。
      alive(call);
      const value = applyOriginal(captured[operation], cfg.models, [call.args.model, call.args.context, call.args.options]);
      if (operation === "streamSimple") await consume(call, value);
      else {
        const actual = message(await value);
        if (!call.done) { try { alive(call); } catch { call.fail("dispatch-unknown"); } }
        await persist(call, actual);
        if (!call.done) { alive(call); message(actual); call.finish(null, cleanMessage(actual)); }
      }
    } catch (caught) { if (safeCode(caught) === "persistence-unknown") close(); call.fail("dispatch-unknown"); }
  }
  function rawOptions(inputOptions) {
    data(inputOptions, OPTIONS, ["signal", "maxRetries", "transport"]);
    const prototype = Object.getPrototypeOf(inputOptions), keys = Reflect.ownKeys(inputOptions);
    const descriptors = keys.map(key => Object.getOwnPropertyDescriptor(inputOptions, key));
    return () => {
      if (types.isProxy(inputOptions) || Object.getPrototypeOf(inputOptions) !== prototype) throw error("dispatch-unknown");
      const current = Reflect.ownKeys(inputOptions);
      if (current.length !== keys.length || current.some((key, index) => key !== keys[index])) throw error("dispatch-unknown");
      for (let index = 0; index < keys.length; index++) {
        const actual = Object.getOwnPropertyDescriptor(inputOptions, keys[index]), original = descriptors[index];
        if (!actual || !Object.hasOwn(actual, "value") || actual.value !== original.value || actual.enumerable !== original.enumerable
            || actual.writable !== original.writable || actual.configurable !== original.configurable) throw error("dispatch-unknown");
      }
    };
  }
  function entry(operation, model, context, inputOptions) {
    let call, allocationAttempted = false;
    try {
      let binding, initialRequestKey;
      if (sdkSimple) {
        binding = rawOptions(inputOptions);
        const selected = options(inputOptions, defaultCap), request = bounded({ model, context, options: selected.pure });
        if (canonical(request.model) !== modelKey) throw error("dispatch-unknown");
        initialRequestKey = canonical(request);
      }
      allocationAttempted = true; call = control(operation === "streamSimple");
      if (binding) {
        call.rawOptions = binding; binding();
        const selected = options(inputOptions, defaultCap);
        if (canonical(bounded({ model, context, options: selected.pure })) !== initialRequestKey) throw error("dispatch-unknown");
      }
      capture(call, operation, model, context, inputOptions);
      // 自有 worker 的所有拒绝由自身处理，不把后台失败交给 unhandled rejection。
      void run(call, operation).catch(() => call.fail("dispatch-unknown"));
    } catch {
      if (!call && sdkSimple && !allocationAttempted) {
        allocationAttempted = true;
        try { call = control(operation === "streamSimple"); } catch { throw error("dispatch-unknown"); }
      }
      if (call) call.fail("dispatch-unknown"); else throw error("dispatch-unknown");
    }
    return operation === "streamSimple" ? call.outer : call.promise;
  }
  function unsupportedStream() { const call = control(true); call.fail("unsupported"); return call.outer; }
  function rejected() { const value = Promise.reject(error("unsupported")); void value.catch(() => {}); return value; }
  const limited = Object.freeze({
    getModel(provider, id) { if (closed) return undefined; configuration(); return provider === fixedModel.provider && id === fixedModel.id ? bounded(fixedModel) : undefined; },
    streamSimple(model, context, options) { return entry("streamSimple", model, context, options); },
    completeSimple(model, context, options) { return entry("completeSimple", model, context, options); },
    stream: unsupportedStream, streamDeferred: unsupportedStream,
    complete() { return rejected(); },
    fetchDeferred() { return rejected(); },
    cancelDeferred() { return rejected(); },
  });
  return Object.freeze({ models: limited, close });
}
