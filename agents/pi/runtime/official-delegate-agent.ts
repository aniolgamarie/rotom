// 公开底层 Agent 的候选组合；只拥有进程内视图，不提供持久恢复或动作授权。
import { isDeepStrictEqual, types } from "node:util";
import { createPiDelegateStreamFn } from "./official-delegate-stream.ts";
import { captureOperationInput } from "./private-operation-input.ts";

const fail = code => { throw new Error(code); };
const identifier = value => typeof value === "string" && value.length > 0 && value.length <= 256
  && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
function data(value, seen = new Map()) {
  if (value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value)) return value;
  if (typeof value !== "object" || types.isProxy(value)) fail("pi-delegate-agent-data-unsupported");
  if (seen.has(value)) return seen.get(value);
  const array = Array.isArray(value);
  if (Object.getPrototypeOf(value) !== (array ? Array.prototype : Object.prototype)) fail("pi-delegate-agent-data-unsupported");
  const result = array ? [] : {}; seen.set(value, result);
  for (const key of Reflect.ownKeys(value)) {
    if (array && key === "length") continue;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) fail("pi-delegate-agent-data-unsupported");
    Object.defineProperty(result, key, { value: data(descriptor.value, seen), enumerable: true, configurable: true, writable: true });
  }
  if (array) result.length = value.length;
  return result;
}
// 候选 TypeBox 的非枚举 ~kind 等 metadata 属于公开 schema 数据，保留描述符。
function schemaData(value, seen = new Map()) {
  if (value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value)) return value;
  if (typeof value !== "object" || types.isProxy(value)) fail("pi-delegate-agent-tools-unsupported");
  if (seen.has(value)) return seen.get(value);
  const array = Array.isArray(value);
  if (Object.getPrototypeOf(value) !== (array ? Array.prototype : Object.prototype)) fail("pi-delegate-agent-tools-unsupported");
  const result = array ? [] : {}; seen.set(value, result);
  for (const key of Reflect.ownKeys(value)) {
    if (array && key === "length") continue;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !Object.hasOwn(descriptor, "value")) fail("pi-delegate-agent-tools-unsupported");
    Object.defineProperty(result, key, { ...descriptor, value: schemaData(descriptor.value, seen) });
  }
  if (array) Object.defineProperty(result, "length", Object.getOwnPropertyDescriptor(value, "length"));
  return result;
}
function sanitizeAssistant(message) {
  if (message?.role === "assistant" && message.errorMessage !== undefined) message.errorMessage = "pi-delegate-sdk-error";
  return message;
}
function sanitizeEvent(event) {
  // 只处理公开协议中的消息位置；工具 args/details 等字面业务数据保持原样。
  if (["message_start", "message_update", "message_end", "turn_end"].includes(event.type)) sanitizeAssistant(event.message);
  if (event.type === "agent_end" && Array.isArray(event.messages)) event.messages.forEach(sanitizeAssistant);
  if (event.type === "message_update" && event.assistantMessageEvent) {
    for (const key of ["partial", "message", "error"]) sanitizeAssistant(event.assistantMessageEvent[key]);
  }
  return event;
}
const literal = value => {
  if (typeof value !== "string" || !value.trim() || Buffer.byteLength(value, "utf8") > 65536) fail("pi-delegate-agent-text");
  return value;
};
function captureTools(definitions) {
  if (!Array.isArray(definitions) || types.isProxy(definitions)) fail("pi-delegate-agent-tools-unsupported");
  const names = new Set();
  return definitions.map(tool => {
    if (!tool || types.isProxy(tool) || Object.getPrototypeOf(tool) !== Object.prototype
        || Reflect.ownKeys(tool).some(key => typeof key !== "string" || !["name", "label", "description", "parameters", "execute"].includes(key))) fail("pi-delegate-agent-tools-unsupported");
    const fields = Object.getOwnPropertyDescriptors(tool);
    if (Object.keys(fields).length !== 5 || Object.values(fields).some(field => !field.enumerable || !Object.hasOwn(field, "value"))) fail("pi-delegate-agent-tools-unsupported");
    if (!identifier(tool.name) || names.has(tool.name) || typeof tool.label !== "string" || typeof tool.description !== "string"
        || typeof tool.execute !== "function") fail("pi-delegate-agent-tools-unsupported");
    names.add(tool.name);
    // 暂只接受数据 schema；符号及公开可选工具字段明确 unsupported。
    let parameters;
    try { parameters = schemaData(tool.parameters); } catch { fail("pi-delegate-agent-tools-unsupported"); }
    if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") fail("pi-delegate-agent-tools-unsupported");
    return { name: tool.name, label: tool.label, description: tool.description, parameters, execute: tool.execute };
  });
}

export function createPiDelegateAgentInitializer({ core, ai, runtimeHandle, binding, beforeDispatch, systemPrompt,
  toolDefinitions = [], authorizeTool, thinkingLevel = "off", maxTokens, cacheSessionId, initialMessages = [] }) {
  if (typeof core?.Agent !== "function" || typeof systemPrompt !== "string" || Buffer.byteLength(systemPrompt, "utf8") > 65536
      || !["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(thinkingLevel)) fail("pi-delegate-agent-input");
  const selected = data(binding), tools = captureTools(toolDefinitions), Agent = core.Agent;
  let restored;
  try {
    restored = captureOperationInput(initialMessages, { allowFiniteNumbers: true }).value;
    if (!Array.isArray(restored) || restored.length > 512
        || restored.some(message => !message || Array.isArray(message)
          || !["user", "assistant", "toolResult"].includes(message.role))) fail("pi-delegate-agent-messages");
  } catch { fail("pi-delegate-agent-messages"); }
  if (tools.length && typeof authorizeTool !== "function") fail("pi-delegate-agent-tool-authorizer");
  let retired = false, observerFailure, agent, prompting = false, fixedModel;
  let observationTail = Promise.resolve();
  const runtime = runtimeHandle?.modelRuntime, check = runtimeHandle?.check;
  const getModel = runtime?.getModel, getError = runtime?.getError;
  const alive = signal => { if (retired || signal?.aborted) fail("pi-delegate-agent-retired"); };
  const verifyModel = () => {
    if (runtimeHandle.modelRuntime !== runtime || runtimeHandle.check !== check || runtime.getModel !== getModel || runtime.getError !== getError) fail("pi-delegate-agent-runtime");
    const model = data(getModel.call(runtime, selected.provider, selected.model));
    if (getError.call(runtime) !== undefined || model?.provider !== selected.provider || model?.id !== selected.model || !identifier(model?.api)
        || fixedModel !== undefined && !isDeepStrictEqual(model, fixedModel)) fail("pi-delegate-agent-runtime");
    return model;
  };
  const recheck = async signal => {
    alive(signal); await check.call(runtimeHandle); alive(signal); verifyModel();
  };
  const streamFn = createPiDelegateStreamFn({ ai, runtimeHandle, binding: selected, maxTokens,
    reasoning: thinkingLevel === "off" ? undefined : thinkingLevel, sessionId: cacheSessionId,
    beforeDispatch: async (snapshot, signal) => {
      await observationTail; observed(); alive(signal);
      const result = await beforeDispatch(snapshot, signal); alive(signal); return result;
    } });
  if (typeof beforeDispatch !== "function") fail("pi-delegate-agent-input");
  const deny = () => ({ block: true, reason: "pi-delegate-tool-denied", terminate: true });
  const beforeToolCall = async (context, signal) => {
    try {
      await recheck(signal);
      await observationTail; observed(); alive(signal);
      const snapshot = data({ toolCall: context.toolCall, args: context.args, assistantMessage: context.assistantMessage });
      const allowed = await authorizeTool(snapshot, signal);
      alive(signal);
      if (allowed !== true) return deny();
      await recheck(signal);
      return undefined;
    } catch { return deny(); }
  };
  const retire = () => {
    if (retired) return;
    retired = true;
    try { agent?.abort(); } catch { fail("pi-delegate-agent-sdk-error"); }
  };
  const observed = () => { if (observerFailure) fail(observerFailure); };
  const guard = async action => {
    try { return await action(); } catch {
      const wasRetired = retired;
      try { retire(); } catch { /* SDK 异常不释放资源，也不把 abort 异常泄露给调用者。 */ }
      observed();
      fail(wasRetired ? "pi-delegate-agent-retired" : "pi-delegate-agent-sdk-error");
    }
  };
  let pending;
  return () => pending ??= (async () => {
    try {
      await check.call(runtimeHandle);
      fixedModel = verifyModel();
      await recheck();
      agent = new Agent({ initialState: { model: data(fixedModel), thinkingLevel, systemPrompt,
        tools: tools.map(tool => ({ ...tool, parameters: schemaData(tool.parameters) })), messages: data(restored) }, streamFn,
        beforeToolCall, sessionId: cacheSessionId, transport: "sse", toolExecution: "sequential", steeringMode: "one-at-a-time", followUpMode: "one-at-a-time" });
      const busy = () => prompting || agent.state.isStreaming;
      const queue = (method, value) => { literal(value); alive(); if (!busy()) fail("pi-delegate-agent-idle");
        return (async () => {
          await guard(() => recheck(agent.signal));
          // 等待期间自然 idle 是已知未排队；验证在执行异常退役 guard 之外。
          if (!busy()) fail("pi-delegate-agent-idle");
          return guard(() => agent[method]({ role: "user", content: value, timestamp: Date.now() }));
        })(); };
      return Object.freeze({
        async prompt(value) {
          literal(value); alive(); if (busy()) fail("pi-delegate-agent-busy"); prompting = true;
          try { return await guard(async () => {
            await recheck(); await agent.prompt(value); await observationTail; observed();
            if (agent.state.errorMessage) fail("pi-delegate-agent-sdk-error");
            alive();
          }); } finally { prompting = false; }
        },
        steer: value => queue("steer", value), followUp: value => queue("followUp", value),
        subscribe(listener) {
          alive(); if (typeof listener !== "function") fail("pi-delegate-agent-listener");
          try { const unsubscribe = agent.subscribe((event, signal) => {
            if (observerFailure) return;
            let captured;
            try { captured = sanitizeEvent(data(event)); }
            catch { observerFailure = "pi-delegate-agent-observer-failed"; try { retire(); } catch {} return; }
            // 公开 Agent 不等待监听 Promise；自有持久回调按事件顺序结清再确认完成。
            observationTail = observationTail.then(async () => {
              if (!observerFailure) await listener(captured, signal);
            }).catch(() => {
              observerFailure = "pi-delegate-agent-observer-failed";
              try { retire(); } catch { /* 原监听异常与 abort 异常不进入 SDK 事件。 */ }
            });
            return observationTail;
          });
            return () => { try { unsubscribe(); } catch { retire(); fail("pi-delegate-agent-sdk-error"); } };
          } catch { retire(); fail("pi-delegate-agent-sdk-error"); }
        },
        abort() { retire(); },
        waitForIdle: () => guard(async () => { await agent.waitForIdle(); await observationTail; observed(); }),
        snapshot() {
          try { return { binding: data(selected), thinkingLevel, isStreaming: Boolean(agent.state.isStreaming), hasQueuedMessages: Boolean(agent.hasQueuedMessages()),
            messages: data(agent.state.messages).map(sanitizeAssistant), retired, observerFailure }; }
          catch { fail("pi-delegate-agent-sdk-error"); }
        },
      });
    } catch { fail("pi-delegate-agent-initialize-failed"); }
  })();
}
