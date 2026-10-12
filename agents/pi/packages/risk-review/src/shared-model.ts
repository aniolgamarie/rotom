// 纯安全descriptor与固定reviewer请求variant；不读账户/env、加载SDK或签准入。
// Caller仍须检查公开describe/private完整Model baseline、配置当前性及authority价目。
import { createHash } from "node:crypto";
import { types } from "node:util";

const INVALID = "PI_RISK_REVIEW_MODEL_INVALID";
const UNSUPPORTED = "PI_RISK_REVIEW_MODEL_UNSUPPORTED";
const fields = ["id", "provider", "api", "name", "baseUrl", "reasoning", "input", "cost", "contextWindow", "maxTokens"];
const routeFields = ["logical_provider", "native_route", "model_id", "auth_kind", "owner", "api", "base_url"];
const levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
function fail(code = INVALID): never {
  const error = new Error(code); Object.assign(error, { code }); throw error;
}
function data(value: unknown, required: string[], optional: string[] = []): Record<string, unknown> {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) fail();
  const keys = Reflect.ownKeys(value);
  if (keys.length > required.length + optional.length || keys.some(key => typeof key !== "string" || ![...required, ...optional].includes(key)) || required.some(key => !Object.hasOwn(value, key))) fail();
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    const property = Object.getOwnPropertyDescriptor(value, key);
    if (!property?.enumerable || !Object.hasOwn(property, "value")) fail();
    result[key as string] = property.value;
  }
  return result;
}
function text(value: unknown, cap = 4096): asserts value is string {
  if (typeof value !== "string" || !value.length || value.length > cap || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(value) || Buffer.byteLength(value, "utf8") > cap) fail();
}
function id(value: unknown, cap = 256): asserts value is string {
  if (typeof value !== "string" || !value.length || value.length > cap || /[^\x21-\x7e]/.test(value)) fail();
}
function integer(value: unknown, cap: number): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > cap) fail();
}
function input(value: unknown): string[] {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype) fail();
  const length = Object.getOwnPropertyDescriptor(value, "length")?.value;
  if (!Number.isSafeInteger(length) || length < 1 || length > 2 || Reflect.ownKeys(value).length !== length + 1) fail();
  const result: string[] = [];
  for (let index = 0; index < length; index++) {
    const property = Object.getOwnPropertyDescriptor(value, String(index));
    if (!property?.enumerable || !Object.hasOwn(property, "value") || typeof property.value !== "string" || !["text", "image"].includes(property.value) || result.includes(property.value)) fail();
    result.push(property.value);
  }
  if (!result.includes("text")) fail();
  return result;
}
function endpoint(value: unknown): asserts value is string {
  text(value, 16384);
  if (!/^https:\/\/[^/]/.test(value) || /[\s\\?#$]/u.test(value)) fail();
  const url = new URL(value), authority = value.split("/")[2];
  if (!url.hostname || url.protocol !== "https:" || url.username || url.password || authority.includes("@") || authority.endsWith(":") || (url.port && (+url.port < 1 || +url.port > 65535))) fail();
}
function freeze(value: any): any {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function canonical(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
function prepare(options: unknown) {
  const cfg = data(options, ["descriptor", "route", "configuration_identity", "token_limits"]);
  const descriptor = data(cfg.descriptor, fields, ["thinkingLevelMap", "compat"]);
  const route = data(cfg.route, routeFields);
  const tokens = data(cfg.token_limits, ["input_tokens", "output_tokens"]);
  for (const key of ["id", "provider", "api"]) id(descriptor[key], key === "id" ? 512 : key === "api" ? 64 : 256);
  text(descriptor.name); endpoint(descriptor.baseUrl);
  if (typeof descriptor.reasoning !== "boolean") fail();
  descriptor.input = input(descriptor.input);
  integer(descriptor.contextWindow, 10000000); integer(descriptor.maxTokens, 10000000);
  if (descriptor.maxTokens > descriptor.contextWindow) fail();
  const cost = data(descriptor.cost, ["input", "output", "cacheRead", "cacheWrite"]);
  for (const value of Object.values(cost)) if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1000000) fail();
  descriptor.cost = cost; // SDK描述cost不代替外部authority价格。
  if (Object.hasOwn(descriptor, "thinkingLevelMap")) {
    const map = data(descriptor.thinkingLevelMap, [], levels);
    for (const value of Object.values(map)) if (value !== null) text(value);
    descriptor.thinkingLevelMap = map;
  }
  let unsupportedCompat = false;
  if (Object.hasOwn(descriptor, "compat")) {
    // 先拒绝所有奇异数据，再把当前未支持的公开compat分类unsupported。
    const value = descriptor.compat;
    if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) fail();
    const keys = Reflect.ownKeys(value);
    if (keys.length > 64 || keys.some(key => typeof key !== "string")) fail();
    for (const key of keys) {
      const property = Object.getOwnPropertyDescriptor(value, key);
      if (!property?.enumerable || !Object.hasOwn(property, "value")) fail();
    }
    unsupportedCompat = keys.some(key => !["requiresReasoningContentOnAssistantMessages", "thinkingFormat"].includes(key as string));
    const compat: Record<string, unknown> = {};
    for (const key of ["requiresReasoningContentOnAssistantMessages", "thinkingFormat"]) {
      if (Object.hasOwn(value, key)) compat[key] = Object.getOwnPropertyDescriptor(value, key)!.value;
    }
    if (Object.hasOwn(compat, "requiresReasoningContentOnAssistantMessages") && typeof compat.requiresReasoningContentOnAssistantMessages !== "boolean") fail();
    if (Object.hasOwn(compat, "thinkingFormat")) {
      text(compat.thinkingFormat);
      unsupportedCompat ||= compat.thinkingFormat !== "deepseek";
    }
    descriptor.compat = compat;
  }
  for (const key of routeFields) if (key !== "base_url") id(route[key], key === "model_id" ? 512 : key === "api" ? 64 : 256);
  endpoint(route.base_url);
  if (typeof cfg.configuration_identity !== "string" || !/^[a-f0-9]{64}$/.test(cfg.configuration_identity)) fail();
  integer(tokens.input_tokens, 10000000); integer(tokens.output_tokens, 4096);
  if (tokens.input_tokens + tokens.output_tokens > descriptor.contextWindow || tokens.output_tokens > descriptor.maxTokens) fail();
  // 不infer其他协议或OAuth；后续支持需新明确own适配契约。
  if (unsupportedCompat || route.auth_kind !== "api-key" || route.owner !== "pi-environment" || route.api !== "openai-completions" || descriptor.api !== "openai-completions") fail(UNSUPPORTED);
  if (route.native_route !== descriptor.provider || route.model_id !== descriptor.id || route.api !== descriptor.api || route.base_url !== descriptor.baseUrl) fail();
  const base_model = descriptor;
  const sdk_model = { ...descriptor, input: [...descriptor.input], cost: { ...cost },
    ...(descriptor.thinkingLevelMap ? { thinkingLevelMap: { ...(descriptor.thinkingLevelMap as object) } } : {}),
    compat: { ...(descriptor.compat as object ?? {}), supportsStore: false, supportsDeveloperRole: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens" } };
  const request_policy = {schema_version: 1, purpose: "risk-review", input_mode: "single-text", reasoning_mode: "off", max_retries: 0,
    temperature: 0, stream: true, include_usage: true, input_tokens: tokens.input_tokens, output_tokens: tokens.output_tokens};
  const model_identity = createHash("sha256").update(canonical({base_model, sdk_model, request_policy, route, configuration_identity: cfg.configuration_identity}), "utf8").digest("hex");
  return freeze({base_model, sdk_model, request_policy, model_identity});
}
export function prepareSharedReviewModel(options: unknown) {
  try { return prepare(options); }
  catch (error) { fail((error as {code?:string})?.code === UNSUPPORTED ? UNSUPPORTED : INVALID); }
}
