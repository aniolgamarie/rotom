// 控制端注入send；本模块只描述本地一次发送边界，不证明远端计费或代理重试。
import { types } from "node:util";
const codes = { invalid: "PI_RISK_FETCH_INVALID", limit: "PI_RISK_FETCH_LIMIT",
  failed: "PI_RISK_FETCH_FAILED", canceled: "PI_RISK_FETCH_CANCELED", commit: "PI_RISK_FETCH_COMMIT_FAILED" };
function error(code) { const value = new Error(code); value.code = code; return value; }
// 清理不得等待不合作的底层实现，也不得传播其异常文本。
function discard(value) {
  try { Promise.resolve(value()).catch(() => {}); } catch {}
}
function isSignal(value) { return value instanceof AbortSignal; }
function observeRejection(value) {
  try {
    if (!types.isProxy(value) && types.isPromise(value) && Object.getPrototypeOf(value) === Promise.prototype
        && !Object.hasOwn(value, "constructor")) Promise.prototype.then.call(value, undefined, () => {});
  } catch {}
}

function dataFields(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw error(codes.invalid);
  const copy = Object.create(null);
  for (const key of Reflect.ownKeys(value)) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !descriptor.enumerable || !Object.hasOwn(descriptor, "value")) throw error(codes.invalid);
    copy[key] = descriptor.value;
  }
  return copy;
}
// gate期间只持有自有不可变wire副本，不把正文/认证及其hash交给gate或snapshot。
function captureRequest(input, init) {
  const request = dataFields(init);
  if (typeof input !== "string" || !input.length || input.length > 2048
      || request.method !== "POST" || typeof request.body !== "string" || request.body.length > 131072
      || Buffer.byteLength(request.body, "utf8") > 131072
      || !Object.hasOwn(request, "headers") || Object.keys(request).some(key => !["method", "headers", "body", "signal"].includes(key))
      || Object.hasOwn(request, "signal") && (types.isProxy(request.signal) || !isSignal(request.signal))) throw error(codes.invalid);
  if (types.isProxy(request.headers)) throw error(codes.invalid);
  const entries = request.headers instanceof Headers ? [...Headers.prototype.entries.call(request.headers)] : Object.entries(dataFields(request.headers));
  const headers = Object.create(null);
  let bytes = 0;
  for (const [name, value] of entries) {
    const lower = name.toLowerCase();
    if (!/^[a-z0-9-]+$/.test(lower) || Object.hasOwn(headers, lower) || typeof value !== "string"
        || !value.length || value.length > 8199 || !/^[\x20-\x7e]+$/.test(value)) throw error(codes.invalid);
    bytes += name.length + value.length;
    if (bytes > 16384) throw error(codes.invalid);
    headers[lower] = value;
  }
  return Object.freeze({ input, init: Object.freeze({ ...request, headers: Object.freeze(headers) }) });
}

export function createSingleRequestFetch(options) {
  let send, validate, signal, expired, responseLimit, beforeSend;
  try {
    const config = dataFields(options);
    if (Object.keys(config).some(key => !["send", "validate", "signal", "expired", "responseLimit", "beforeSend"].includes(key))) throw error(codes.invalid);
    ({ send, validate, signal, expired, responseLimit = 65536, beforeSend } = config);
  }
  catch { throw error(codes.invalid); }
  if (typeof send !== "function" || typeof validate !== "function" || typeof expired !== "function"
    || beforeSend !== undefined && (typeof beforeSend !== "function" || types.isProxy(beforeSend) || types.isGeneratorFunction(beforeSend))
    || !isSignal(signal) || !Number.isInteger(responseLimit) || responseLimit < 1 || responseLimit > 262144)
    throw error(codes.invalid);
  // response_bytes仅计核额度后交给SDK流的字节，不是远端总字节或费用。
  const facts = { invocations: 0, requests: 0, response_bytes: 0, body_complete: false,
    redirect_blocked: false, second_request_blocked: false, failure_code: null };
  if (beforeSend !== undefined) Object.assign(facts, { gate_attempted: false, gate_acknowledged: false });
  const sticky = code => { if (facts.failure_code === null) facts.failure_code = code; };
  const snapshot = () => Object.freeze({ ...facts });
  const validateRequest = (input, init) => {
    let valid;
    try { valid = validate(input, init); } catch { throw error(codes.invalid); }
    if (valid !== true) { observeRejection(valid); throw error(codes.invalid); }
  };
  async function singleFetch(input, init) {
    facts.invocations++;
    if (facts.invocations !== 1) {
      facts.second_request_blocked = true; sticky(codes.invalid); throw error(codes.invalid);
    }
    let stopped = false, completed = false, reader, streamController, timer;
    let sdkSignal, response, rejectStop;
    const merged = new AbortController();
    const stopPromise = new Promise((_, reject) => { rejectStop = reject; });
    // 取消可以发生在尚未开始race的同步validator内。
    stopPromise.catch(() => {});
    const cleanup = () => {
      if (timer !== undefined) clearInterval(timer);
      signal.removeEventListener("abort", onAbort);
      sdkSignal?.removeEventListener("abort", onAbort);
    };
    const stop = code => {
      if (stopped || completed) return;
      stopped = true; sticky(code); cleanup(); merged.abort();
      const failure = error(code);
      rejectStop(failure);
      if (reader) discard(() => reader.cancel());
      else if (response?.body) discard(() => response.body.cancel());
      try { streamController?.error(failure); } catch {}
    };
    const onAbort = () => stop(codes.canceled);
    const check = () => {
      if (stopped) throw error(facts.failure_code ?? codes.canceled);
      if (signal.aborted || sdkSignal?.aborted) { stop(codes.canceled); throw error(codes.canceled); }
      let current;
      try { current = expired(); } catch { stop(codes.invalid); throw error(codes.invalid); }
      if (typeof current !== "boolean") {
        observeRejection(current);
        stop(codes.invalid); throw error(codes.invalid);
      }
      if (current) { stop(codes.canceled); throw error(codes.canceled); }
    };
    const finish = () => {
      completed = true; facts.body_complete = true; cleanup();
      if (reader) discard(() => reader.releaseLock());
    };
    try {
      // 保留传入参数供validator核验；不复制、修改或持久化请求正文。
      const captured = beforeSend === undefined ? null : captureRequest(input, init);
      sdkSignal = captured ? captured.init.signal : init?.signal;
      if (sdkSignal != null && !isSignal(sdkSignal)) throw error(codes.invalid);
      signal.addEventListener("abort", onAbort, { once: true });
      sdkSignal?.addEventListener("abort", onAbort, { once: true });
      check();
      validateRequest(input, init);
      check();
      // 中央控制器也有watchdog；低频检查补齐忽略signal的send/body stall。
      // 必须在gate/send之前注册，使不合作的提交也能及时取消本组件等待。
      timer = setInterval(() => { try { check(); } catch {} }, 100);
      if (captured) {
        // 规范化header副本先复核，gate只有原ticket闭包，不取得请求参数。
        validateRequest(captured.input, captured.init);
        check(); facts.gate_attempted = true;
        let committed;
        try { committed = beforeSend(); } catch { throw error(codes.commit); }
        let confirming;
        if (committed === true) {
          facts.gate_acknowledged = true; confirming = Promise.resolve(true);
        } else if (!types.isProxy(committed) && types.isPromise(committed)
            && Object.getPrototypeOf(committed) === Promise.prototype && !Object.hasOwn(committed, "constructor")) {
          confirming = new Promise((resolve, reject) => {
            Promise.prototype.then.call(committed, answer => {
              if (answer === true) { facts.gate_acknowledged = true; resolve(true); }
              else reject(error(codes.commit));
            }, () => reject(error(codes.commit)));
          });
        } else throw error(codes.commit);
        // 原生Promise迟到回执只更新事实，不恢复已退役能力或重新发送。
        confirming.catch(() => {});
        try { await Promise.race([confirming, stopPromise]); }
        catch { if (stopped) throw error(facts.failure_code ?? codes.canceled); throw error(codes.commit); }
        check();
        validateRequest(captured.input, captured.init);
        check();
      }
      // 严格validator核验原形状后才增加wrapper拥有的redirect/signal。
      const sentInit = { ...(captured ? captured.init : init), redirect: "manual", signal: merged.signal };
      check();
      facts.requests++;
      // 用微任务包装同步抛错；计数对应实际进入send的本地边界。
      let sending;
      try { sending = Promise.resolve(send(captured ? captured.input : input, sentInit)); }
      catch { throw error(codes.failed); }
      sending.then(late => {
        if (stopped && late instanceof Response && late.body) discard(() => late.body.cancel());
      }, () => {});
      try { response = await Promise.race([sending, stopPromise]); }
      catch (caught) { if (stopped) throw error(facts.failure_code ?? codes.canceled); throw error(codes.failed); }
      check();
      if (!(response instanceof Response)) throw error(codes.failed);
      if (response.redirected === true || (response.status >= 300 && response.status < 400))
        facts.redirect_blocked = true;
      if (facts.redirect_blocked || response.status < 200 || response.status >= 300) throw error(codes.failed);
      const length = response.headers.get("content-length");
      if (length !== null && /^\d+$/.test(length.trim()) && BigInt(length.trim()) > BigInt(responseLimit))
        throw error(codes.limit);
      if (response.body === null) { finish(); return response; }
      reader = response.body.getReader();
      const body = new ReadableStream({
        start(controller) { streamController = controller; },
        async pull(controller) {
          try {
            check();
            let chunk;
            try { chunk = await Promise.race([reader.read(), stopPromise]); }
            catch { if (stopped) return; throw error(codes.failed); }
            check();
            if (chunk.done) { finish(); controller.close(); return; }
            if (!(chunk.value instanceof Uint8Array)) throw error(codes.failed);
            if (chunk.value.byteLength > responseLimit - facts.response_bytes) throw error(codes.limit);
            facts.response_bytes += chunk.value.byteLength;
            controller.enqueue(chunk.value);
          } catch (caught) {
            stop(Object.values(codes).includes(caught?.code) ? caught.code : codes.failed);
          }
        },
        cancel() { stop(codes.canceled); },
      }, { highWaterMark: 0 });
      const bounded = new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
      // 保持Response公开元数据语义，不输出/记录这些潜在敏感值。
      Object.defineProperties(bounded, { url: { value: response.url }, redirected: { value: response.redirected }, type: { value: response.type } });
      return bounded;
    } catch (caught) {
      const code = Object.values(codes).includes(caught?.code) ? caught.code : codes.failed;
      stop(code); throw error(code);
    }
  }
  return Object.freeze({ fetch: singleFetch, snapshot });
}
