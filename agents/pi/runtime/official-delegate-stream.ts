// 自有 Agent 的公开 streamFn 接缝；不安装宿主钩子，不拥有许可、账单或 Writer。
import { isDeepStrictEqual, types } from "node:util";

const identifier = value => typeof value === "string" && value.length > 0 && value.length <= 256
  && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const invalid = () => { throw new Error("pi-delegate-stream-input"); };

// 仅捕获数据，不执行 getter，也不散列或序列化可能含 headers 的模型描述。
function copyData(value, seen = new Map()) {
  if (value === null || value === undefined || ["string", "boolean", "number"].includes(typeof value)) return value;
  if (typeof value !== "object" || types.isProxy(value)) invalid();
  if (seen.has(value)) return seen.get(value);
  const array = Array.isArray(value);
  if (Object.getPrototypeOf(value) !== (array ? Array.prototype : Object.prototype)) invalid();
  const result = array ? [] : {};
  seen.set(value, result);
  for (const key of Reflect.ownKeys(value)) {
    if (array && key === "length") continue;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
    Object.defineProperty(result, key, { value: copyData(descriptor.value, seen), enumerable: true, writable: true, configurable: true });
  }
  if (array) result.length = value.length;
  return result;
}

export function createPiDelegateStreamFn({ ai, runtimeHandle, binding, beforeDispatch, maxTokens, reasoning, sessionId }) {
  let selected;
  try { selected = copyData(binding); } catch { invalid(); }
  if (!selected || Array.isArray(selected) || Object.keys(selected).sort().join(",") !== "model,provider"
      || !identifier(selected.provider) || !identifier(selected.model)
      || typeof ai?.createAssistantMessageEventStream !== "function" || typeof runtimeHandle?.check !== "function"
      || typeof runtimeHandle?.modelRuntime?.getModel !== "function" || typeof runtimeHandle?.modelRuntime?.getError !== "function"
      || typeof runtimeHandle?.modelRuntime?.streamSimple !== "function" || typeof beforeDispatch !== "function"
      || maxTokens !== undefined && (!Number.isSafeInteger(maxTokens) || maxTokens < 1)
      || reasoning !== undefined && !["minimal", "low", "medium", "high", "xhigh", "max"].includes(reasoning)
      || sessionId !== undefined && !identifier(sessionId)) invalid();
  const runtime = runtimeHandle.modelRuntime, check = runtimeHandle.check;
  const getModel = runtime.getModel, getError = runtime.getError, streamSimple = runtime.streamSimple;
  const createStream = ai.createAssistantMessageEventStream;
  const options = { maxTokens, reasoning, sessionId, transport: "sse", maxRetries: 0 };
  let fixed;
  const matches = model => model?.provider === selected.provider && model?.id === selected.model && identifier(model.api);
  const verify = model => {
    if (!matches(model) || runtimeHandle.modelRuntime !== runtime || runtimeHandle.check !== check
        || runtime.getModel !== getModel || runtime.getError !== getError || runtime.streamSimple !== streamSimple) invalid();
    const current = copyData(getModel.call(runtime, selected.provider, selected.model));
    if (getError.call(runtime) !== undefined || !matches(current) || !isDeepStrictEqual(current, model)
        || fixed !== undefined && !isDeepStrictEqual(current, fixed)) invalid();
    // 首次不匹配的 caller 不能污染固定描述；只从已核验的 runtime 数据固定。
    if (fixed === undefined) fixed = copyData(current);
  };
  const failure = (code, aborted, api) => {
    const stream = createStream.call(ai);
    // 零 usage 仅满足公开事件结构；不能据此释放全 run 预算或判定账单为零。
    const message = { role: "assistant", content: [], api, provider: selected.provider, model: selected.model,
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      stopReason: aborted ? "aborted" : "error", errorMessage: code, timestamp: Date.now() };
    stream.push({ type: "error", reason: message.stopReason, error: message });
    stream.end(message);
    return stream;
  };
  return async (model, context, incoming = {}) => {
    let signal, target, transcript, submitted = false, api = fixed?.api ?? "openai-completions";
    try {
      signal = incoming?.signal;
      const canceled = () => { if (signal?.aborted) invalid(); };
      canceled();
      target = copyData(model); transcript = copyData(context);
      verify(target);
      api = fixed.api;
      await check.call(runtimeHandle); canceled(); verify(target);
      const allowed = await beforeDispatch({ binding: copyData(selected), model: copyData(fixed), context: copyData(transcript), options: copyData(options) }, signal);
      canceled();
      if (allowed !== true) invalid();
      verify(target);
      await check.call(runtimeHandle); canceled(); verify(target);
      // SSE/零重试是公开请求选项，不证明每个 provider 的物理尝试受控。
      submitted = true;
      return await streamSimple.call(runtime, copyData(fixed), copyData(transcript), { ...options, signal });
    } catch {
      let aborted = false;
      try { aborted = signal?.aborted === true; } catch { /* 非法 signal 不能把拒绝变成 Promise rejection。 */ }
      return failure(submitted ? "pi-delegate-runtime-submit-unknown" : "pi-delegate-dispatch-denied", aborted, api);
    }
  };
}
