// 单个受信准备对象的审批attempt；不发许可，不执行工具，不持有执行回调。
import { types } from "node:util";
import { parseReviewResponse } from "./protocol.ts";
import { createSingleRequestFetch } from "./wire-fetch.ts";
import { createReviewRequestValidator } from "./request-wire.ts";
import { compileSharedReviewSdkContract } from "./shared-sdk-contract.ts";
import { createSharedReviewRequestValidator } from "./shared-request-wire.ts";

const code = "PI_RISK_REVIEW_TRANSPORT_INVALID";
const bindingKeys = ["request_id", "operation_digest", "context_digest", "reviewer_identity"];
const routeKeys = ["identity", "pricing_identity", "currency", "provider", "model", "base_url", "context_window", "max_output_tokens", "cost"];
const qualificationKeys = ["profile", "enabled", "hard_policy_allowed", "role_allows", "requires_human", "automatic_risk_allowed"];
const headerKeys = ["authorization", "accept", "content-type", "user-agent", "x-stainless-lang", "x-stainless-package-version",
  "x-stainless-os", "x-stainless-arch", "x-stainless-runtime", "x-stainless-runtime-version", "x-stainless-retry-count", "x-stainless-timeout"];
function invalid() { const error = new Error(code); error.code = code; throw error; }
function closed(value, keys, required = keys) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) invalid();
  const names = Reflect.ownKeys(value);
  if (names.some(key => !keys.includes(key)) || required.some(key => !names.includes(key))) invalid();
  const copy = {};
  for (const key of names) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
    copy[key] = descriptor.value;
  }
  return copy;
}
const integer = (value, min, max) => Number.isSafeInteger(value) && value >= min && value <= max;
const hex = (value, size = 64) => typeof value === "string" && new RegExp("^[0-9a-f]{" + size + "}$").test(value);
const text = (value, limit) => typeof value === "string" && value.length <= limit && !/[\p{Cs}]/u.test(value) && Buffer.byteLength(value, "utf8") <= limit;
function read(value, key) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) return undefined;
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor && Object.hasOwn(descriptor, "value") ? descriptor.value : undefined;
}
function arrayData(value, limit) {
  if (!Array.isArray(value) || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length > limit) return null;
  if (Reflect.ownKeys(value).length !== value.length + 1) return null;
  const copy = [];
  for (let index = 0; index < value.length; index++) {
    const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) return null;
    copy.push(descriptor.value);
  }
  return copy;
}
function reportedUsage(event, route) {
  const value = read(event, "usage");
  if (value === undefined || value === null) return null;
  const input = read(value, "prompt_tokens"), output = read(value, "completion_tokens"), total = read(value, "total_tokens");
  if (!integer(input, 0, route.context_window) || !integer(output, 0, route.max_output_tokens)
      || !integer(total, 0, route.context_window + route.max_output_tokens) || input + output !== total) return null;
  const details = read(value, "prompt_tokens_details");
  const cache = read(details, "cached_tokens");
  return Object.freeze({ status: "reported", input_tokens: input, output_tokens: output, total_tokens: total,
    cache_read_tokens: integer(cache, 0, input) ? cache : null, cache_write_tokens: null });
}

export function createReviewAttempt(options) {
  const required = ["binding", "route", "input", "qualification", "apiKey", "expectedHeaders", "sdk", "send", "isCurrent", "deadlineMs"];
  const cfg = closed(options, [...required, "signal", "clocks", "maxDurationMs", "responseLimit", "sharedModel", "inputQualification", "beforeSend"], required);
  if (cfg.beforeSend !== undefined && (typeof cfg.beforeSend !== "function" || types.isProxy(cfg.beforeSend)
      || types.isGeneratorFunction(cfg.beforeSend))) invalid();
  const binding = Object.freeze(closed(cfg.binding, bindingKeys));
  for (const key of bindingKeys) if (!hex(binding[key], key === "request_id" ? 32 : 64)) invalid();
  const route = closed(cfg.route, routeKeys);
  if (!hex(route.identity) || route.identity !== binding.reviewer_identity || !hex(route.pricing_identity)
      || typeof route.currency !== "string" || !/^[A-Z]{3}$/.test(route.currency)
      || !text(route.provider, 128) || !/^[a-zA-Z0-9_.:/-]+$/.test(route.provider)
      || !text(route.model, 128) || !/^[a-zA-Z0-9_.:/-]+$/.test(route.model)
      || !text(route.base_url, 2048) || !integer(route.context_window, 4097, 10000000)
      || !integer(route.max_output_tokens, 1, 4096)) invalid();
  const cost = closed(route.cost, ["input", "output", "cacheRead", "cacheWrite"]);
  if (Object.values(cost).some(value => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1000000)) invalid();
  route.cost = Object.freeze(cost); Object.freeze(route);
  let sharedModel, compiled;
  if (cfg.sharedModel !== undefined) {
    try {
      compiled = compileSharedReviewSdkContract(cfg.sharedModel);
      if (compiled.model_identity !== route.identity || compiled.model_identity !== binding.reviewer_identity
          || compiled.sdk_model.provider !== route.provider || compiled.sdk_model.id !== route.model
          || compiled.sdk_model.baseUrl !== route.base_url || compiled.sdk_model.contextWindow !== route.context_window
          || compiled.wire_contract.output_tokens !== route.max_output_tokens) invalid();
      // 验证在clone之前同步完成，caller graph不能执行getter/proxy或改变下一次绑定。
      sharedModel = structuredClone(cfg.sharedModel);
      const freeze = value => { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } };
      freeze(sharedModel);
    } catch { invalid(); }
  }
  if (Object.hasOwn(cfg, "inputQualification") && (!compiled || cfg.inputQualification !== undefined
      && (typeof cfg.inputQualification !== "function" || types.isProxy(cfg.inputQualification) || types.isAsyncFunction(cfg.inputQualification)))) invalid();
  const input = Object.freeze(closed(cfg.input, ["system_prompt", "user_prompt"]));
  if (!text(input.system_prompt, 32768) || !text(input.user_prompt, 32768)) invalid();
  const qualification = Object.freeze(closed(cfg.qualification, qualificationKeys));
  if (!["pi-base", "pi-full"].includes(qualification.profile)
      || qualificationKeys.slice(1).some(key => typeof qualification[key] !== "boolean")) invalid();
  const sdk = closed(cfg.sdk, ["streamSimple", "normalizeContext"]);
  if ([sdk.streamSimple, sdk.normalizeContext, cfg.send, cfg.isCurrent].some(value => typeof value !== "function" || types.isProxy(value))) invalid();
  const clocks = cfg.clocks === undefined ? { wall: () => Date.now(), monotonic: () => performance.now() } : closed(cfg.clocks, ["wall", "monotonic"]);
  if (Object.values(clocks).some(value => typeof value !== "function" || types.isProxy(value))) invalid();
  const maxDuration = cfg.maxDurationMs ?? 30000, responseLimit = cfg.responseLimit ?? 65536;
  if (!integer(maxDuration, 1, 300000) || !integer(responseLimit, 1, 262144) || !integer(cfg.deadlineMs, 0, Number.MAX_SAFE_INTEGER)
      || !text(cfg.apiKey, 8192) || !cfg.apiKey.length
      || cfg.signal !== undefined && (!cfg.signal || typeof cfg.signal !== "object" || types.isProxy(cfg.signal)
        || Object.getPrototypeOf(cfg.signal) !== AbortSignal.prototype)) invalid();
  const apiKey = cfg.apiKey;
  const headers = closed(cfg.expectedHeaders, headerKeys, ["authorization", "accept", "content-type"]);
  if (headers.authorization !== "Bearer " + apiKey) invalid();
  let endpoint;
  try { endpoint = new URL(route.base_url.replace(/\/$/, "") + "/chat/completions").href; }
  catch { invalid(); }
  let validate;
  try { validate = compiled ? createSharedReviewRequestValidator({ ...sharedModel, systemPrompt: input.system_prompt,
    userPrompt: input.user_prompt, expectedHeaders: headers }) : createReviewRequestValidator({ endpoint, model: route.model, systemPrompt: input.system_prompt,
    userPrompt: input.user_prompt, maxTokens: route.max_output_tokens, expectedHeaders: headers }); }
  catch { invalid(); }
  const controller = new AbortController();
  let phase = "prepared", outcome = null, candidate = null, promise, wire, iterator, watchdog;
  let start = null, last = null, end = null, wait = 0, deadline = null, cleanup = false, remoteVerified = false;
  let usage = Object.freeze({ status: "unknown", input_tokens: null, output_tokens: null, total_tokens: null,
    cache_read_tokens: null, cache_write_tokens: null });
  let usageLate = false, rawEvents = 0;
  const records = [];
  let wake;
  const stopped = new Promise(resolve => { wake = resolve; });
  const record = event => { if (records.length < 16) records.push(Object.freeze({ event })); };
  const clock = () => {
    const mono = clocks.monotonic(), wall = clocks.wall();
    if (typeof mono !== "number" || !Number.isFinite(mono) || mono < 0 || typeof wall !== "number" || !Number.isFinite(wall)
        || last !== null && mono < last) invalid();
    last = mono; return { mono, wall };
  };
  const stop = value => {
    if (outcome !== null) return;
    outcome = value; phase = "settled"; candidate = null; record(value);
    try { end = clock().mono; } catch { end = null; }
    clearInterval(watchdog); controller.abort(); wake(null);
  };
  const current = () => {
    if (outcome !== null) return false;
    try {
      const now = clock();
      if (cfg.signal?.aborted) { stop("canceled"); return false; }
      if (now.wall >= cfg.deadlineMs || deadline !== null && now.mono >= deadline) { stop("timeout"); return false; }
      if (cfg.isCurrent() !== true) { stop("discarded"); return false; }
      return true;
    } catch { stop("transport-failure"); return false; }
  };
  const onRaw = event => {
    rawEvents = Math.min(1000000, rawEvents + 1);
    const observed = facts();
    if (observed.requests !== 1 || observed.response_bytes === 0) {
      if (outcome === null) stop("transport-failure"); return;
    }
    const reportedModel = read(event, "model");
    if (reportedModel !== route.model) { if (outcome === null) stop("transport-failure"); return; }
    remoteVerified = true;
    const next = reportedUsage(event, route);
    if (next !== null) {
      // 用量是Provider自报的累计值，不采用SDK默认0或SDK的本地cost。
      if (usage.status === "reported" && (next.input_tokens < usage.input_tokens || next.output_tokens < usage.output_tokens)) {
        if (outcome === null) stop("transport-failure"); return;
      }
      usage = next;
      if (outcome !== null) { usageLate = true; record("late-usage"); }
    }
  };
  const facts = () => wire?.snapshot() ?? Object.freeze({ invocations: 0, requests: 0, response_bytes: 0,
    body_complete: false, redirect_blocked: false, second_request_blocked: false, failure_code: null });
  const snapshot = () => {
    const f = facts();
    const badWire = f.second_request_blocked || f.failure_code !== null && !(cleanup && f.failure_code === "PI_RISK_FETCH_CANCELED");
    const result = outcome === "valid" && badWire ? "transport-failure" : outcome;
    const elapsed = start === null || end === null ? null : end - start;
    // 本地零平台调用不能覆盖gate提交/未知提交后的账户预留事实。
    const effectiveUsage = f.requests === 0 && f.gate_attempted !== true ? Object.freeze({ status: "not-sent", input_tokens: 0, output_tokens: 0,
      total_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 }) : usage;
    return Object.freeze({ schema_version: 1, phase, outcome: result, candidate: result === "valid" ? candidate : null,
      binding, route_identity: route.identity, pricing_identity: route.pricing_identity, currency: route.currency,
      provider: route.provider, model: route.model, remote_model_verified: remoteVerified, requests: f.requests,
      request_count_scope: "local-platform-fetch-invocations", usage: effectiveUsage, usage_late: usageLate,
      elapsed_ms: elapsed, model_wait_ms: elapsed === null ? null : Math.min(wait, elapsed), local_ms: elapsed === null ? null : Math.max(0, elapsed - wait),
      wire: f, raw_event_count: rawEvents, records: Object.freeze([...records]), product_gate: false });
  };
  const runOnce = async () => {
    try {
      if (outcome !== null) return snapshot();
      const now = clock(); start = now.mono; deadline = start + Math.min(maxDuration, Math.max(0, cfg.deadlineMs - now.wall));
      if (!current()) return snapshot();
      if (qualification.profile === "pi-base" || !qualification.enabled) { stop("not-called"); return snapshot(); }
      if (!qualification.hard_policy_allowed || !qualification.role_allows) { stop("policy-blocked"); return snapshot(); }
      if (qualification.requires_human || !qualification.automatic_risk_allowed) { stop("human-required"); return snapshot(); }
      if (compiled) {
        // 本地同步受信predicate；不含认证信息，不等待SDK/network或重入控制面。
        let qualified = false;
        try {
          const result = cfg.inputQualification?.(structuredClone({ model: compiled.sdk_model,
            policy: sharedModel.prepared.request_policy, input, model_identity: compiled.model_identity,
            configuration_identity: sharedModel.configuration_identity }));
          if (types.isPromise(result)) Promise.prototype.then.call(result, undefined, () => {});
          qualified = result === true;
        } catch {}
        if (!qualified) { record("input-unqualified"); stop("transport-failure"); return snapshot(); }
        if (!current()) return snapshot();
      }
      phase = "running"; record("admitted");
      watchdog = setInterval(current, Math.min(25, maxDuration));
      wire = createSingleRequestFetch({ send: cfg.send, validate, signal: controller.signal, expired: () => !current(), responseLimit,
        ...(cfg.beforeSend === undefined ? {} : { beforeSend: cfg.beforeSend }) });
      const model = compiled ? compiled.sdk_model : Object.freeze({ api: "openai-completions", provider: route.provider, id: route.model, name: route.model,
        baseUrl: route.base_url, reasoning: false, input: Object.freeze(["text"]), cost: route.cost,
        contextWindow: route.context_window, maxTokens: route.max_output_tokens,
        compat: Object.freeze({ supportsStore: false, supportsDeveloperRole: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens" }) });
      const context = sdk.normalizeContext({ systemPrompt: input.system_prompt,
        messages: [{ role: "user", content: input.user_prompt, timestamp: now.wall }] });
      if (!current()) return snapshot();
      const stream = sdk.streamSimple(model, context, { apiKey, signal: controller.signal, fetch: wire.fetch,
        maxRetries: 0, maxTokens: route.max_output_tokens, temperature: 0, timeoutMs: maxDuration, onProviderStreamEvent: onRaw,
        ...(compiled ? { reasoning: "off" } : {}) });
      iterator = stream[Symbol.asyncIterator]();
      while (current()) {
        const before = clock().mono;
        const next = await Promise.race([Promise.resolve().then(() => iterator.next()), stopped]);
        wait += Math.max(0, clock().mono - before);
        if (!current() || next === null) break;
        if (!next || next.done) { stop("protocol-failure"); break; }
        const event = next.value;
        if (read(event, "type") === "error") { stop("transport-failure"); break; }
        if (typeof read(event, "type") === "string" && read(event, "type").startsWith("toolcall")) { stop("protocol-failure"); break; }
        if (read(event, "type") !== "done") continue;
        const message = read(event, "message");
        if (read(message, "api") !== "openai-completions" || read(message, "provider") !== route.provider
            || read(message, "model") !== route.model || read(message, "stopReason") !== "stop") { stop("protocol-failure"); break; }
        const content = arrayData(read(message, "content"), 16);
        if (content === null) { stop("protocol-failure"); break; }
        let raw = "", valid = true;
        for (const item of content) {
          if (read(item, "type") === "thinking") continue;
          const part = read(item, "text");
          if (read(item, "type") !== "text" || !text(part, 8192) || Buffer.byteLength(raw, "utf8") + Buffer.byteLength(part, "utf8") > 8192) { valid = false; break; }
          raw += part;
        }
        if (!valid) { stop("protocol-failure"); break; }
        if (!current()) break;
        const f = facts();
        if (f.requests !== 1 || f.failure_code !== null || f.second_request_blocked || !remoteVerified) { stop("transport-failure"); break; }
        try { candidate = parseReviewResponse(raw, binding); } catch { stop("protocol-failure"); break; }
        if (!current()) break;
        outcome = "valid"; phase = "settled"; end = clock().mono; record("valid");
        break;
      }
    } catch { if (outcome === null) stop("transport-failure"); }
    finally {
      clearInterval(watchdog);
      // 正常终态也关闭残余body；这个主动cleanup不能把valid改成canceled。
      cleanup = true; controller.abort();
      try { Promise.resolve(iterator?.return?.()).catch(() => {}); } catch {}
    }
    return snapshot();
  };
  const abort = () => stop("canceled");
  cfg.signal?.addEventListener("abort", abort, { once: true });
  const run = () => {
    if (!promise) promise = runOnce().finally(() => cfg.signal?.removeEventListener("abort", abort));
    return promise;
  };
  return Object.freeze({ run, snapshot });
}
