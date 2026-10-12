// 仅核验控制器固定的最终wire请求；不读取ambient环境，不授予许可。
import { types } from "node:util";
const code = "PI_RISK_REVIEW_REQUEST_INVALID";
const configKeys = ["endpoint", "model", "systemPrompt", "userPrompt", "maxTokens", "expectedHeaders"];
const headerNames = new Set(["authorization", "accept", "content-type", "user-agent", "x-stainless-lang",
  "x-stainless-package-version", "x-stainless-os", "x-stainless-arch", "x-stainless-runtime",
  "x-stainless-runtime-version", "x-stainless-retry-count", "x-stainless-timeout"]);
const encoder = new TextEncoder();
function fail() { const error = new Error(code); error.code = code; throw error; }
function scalar(value, maximum, empty = false) {
  return typeof value === "string" && (empty || value.length > 0) && value.length <= maximum
    && !/[\p{Cs}]/u.test(value) && encoder.encode(value).byteLength <= maximum;
}
function fields(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail();
  const result = Object.create(null);
  for (const key of Reflect.ownKeys(value)) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (typeof key !== "string" || !descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) fail();
    result[key] = descriptor.value;
  }
  return result;
}
function exact(value, keys) {
  const names = Object.keys(value);
  return names.length === keys.length && names.every(name => keys.includes(name));
}
function headers(value) {
  if (types.isProxy(value)) fail();
  const entries = value instanceof Headers ? [...Headers.prototype.entries.call(value)] : Object.entries(fields(value));
  const result = Object.create(null);
  let total = 0;
  for (const [name, content] of entries) {
    const lower = name.toLowerCase();
    if (!headerNames.has(lower) || Object.hasOwn(result, lower) || typeof content !== "string"
      || !content.length || content.length > (lower === "authorization" ? 8199 : 8192) || !/^[\x20-\x7e]+$/.test(content)) fail();
    total += name.length + content.length;
    if (total > 16384) fail();
    result[lower] = content;
  }
  return result;
}
class NumberToken {
  constructor(token) { this.token = token; }
}
// 专用有界JSON读取；所有层检查重复键，数字保留wire token以拒绝浮点舍入。
function parse(raw) {
  if (!scalar(raw, 131072)) fail();
  let index = 0, nodes = 0;
  const space = () => { while (/[ \t\r\n]/.test(raw[index] ?? "!") && index < raw.length) index++; };
  function string() {
    const start = index++;
    let escaped = false;
    while (index < raw.length) {
      const char = raw[index++];
      if (!escaped && char === '"') {
        const value = JSON.parse(raw.slice(start, index));
        if (!scalar(value, 131072, true)) fail();
        return value;
      }
      if (!escaped && char === "\\") escaped = true;
      else escaped = false;
    }
    fail();
  }
  function value(depth) {
    if (depth > 4 || ++nodes > 64) fail();
    space(); const char = raw[index];
    if (char === '"') return string();
    if (char === "{") {
      index++; space(); const object = Object.create(null);
      if (raw[index] === "}") { index++; return object; }
      while (true) {
        space(); if (raw[index] !== '"') fail(); const key = string();
        if (["__proto__", "constructor", "prototype"].includes(key) || Object.hasOwn(object, key)) fail();
        space(); if (raw[index++] !== ":") fail(); object[key] = value(depth + 1); space();
        const end = raw[index++]; if (end === "}") return object; if (end !== ",") fail();
      }
    }
    if (char === "[") {
      index++; space(); const array = [];
      if (raw[index] === "]") { index++; return array; }
      while (true) {
        if (array.length >= 8) fail(); array.push(value(depth + 1)); space();
        const end = raw[index++]; if (end === "]") return array; if (end !== ",") fail();
      }
    }
    for (const [literal, parsed] of [["true", true], ["false", false], ["null", null]]) {
      if (raw.startsWith(literal, index)) { index += literal.length; return parsed; }
    }
    const number = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(raw.slice(index));
    if (!number) fail(); index += number[0].length; return new NumberToken(number[0]);
  }
  const parsed = value(0); space(); if (index !== raw.length) fail(); return parsed;
}
function integer(value, maximum) {
  if (!(value instanceof NumberToken) || !/^[1-9][0-9]*$/.test(value.token)) return false;
  const parsed = Number(value.token);
  return Number.isSafeInteger(parsed) && parsed <= maximum;
}
function object(value, keys) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && !(value instanceof NumberToken) && exact(value, keys);
}
export function createReviewRequestValidator(options) {
  let captured;
  try {
    const config = fields(options); if (!exact(config, configKeys)) fail();
    const { endpoint, model, systemPrompt, userPrompt, maxTokens } = config;
    if (!scalar(endpoint, 2048) || !scalar(model, 256) || !scalar(systemPrompt, 131072, true)
      || !scalar(userPrompt, 131072) || !Number.isSafeInteger(maxTokens) || maxTokens < 1) fail();
    const url = new URL(endpoint);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || endpoint.includes("?") || endpoint.includes("#")
      || url.href !== endpoint || !url.pathname.endsWith("/chat/completions")) fail();
    const expectedHeaders = headers(config.expectedHeaders);
    if (!/^Bearer [^\s]+$/.test(expectedHeaders.authorization ?? "") || expectedHeaders.accept !== "application/json"
      || expectedHeaders["content-type"] !== "application/json") fail();
    const messages = systemPrompt === "" ? [{ role: "user", content: userPrompt }]
      : [{ role: "system", content: systemPrompt }, { role: "user", content: userPrompt }];
    if (!scalar(JSON.stringify({ model, messages, stream: true, stream_options: { include_usage: true }, temperature: 0, max_tokens: maxTokens }), 131072)) fail();
    captured = Object.freeze({ endpoint, model, messages, maxTokens, expectedHeaders });
  } catch { fail(); }
  return function validate(input, init) {
    try {
      if (typeof input !== "string" || input !== captured.endpoint) return false;
      const request = fields(init);
      if (!Object.hasOwn(request, "method") || !Object.hasOwn(request, "headers") || !Object.hasOwn(request, "body")
        || Object.keys(request).some(key => !["method", "headers", "body", "signal"].includes(key))
        || request.method !== "POST" || (Object.hasOwn(request, "signal") && (types.isProxy(request.signal) || !(request.signal instanceof AbortSignal)))) return false;
      const actualHeaders = headers(request.headers);
      if (!exact(actualHeaders, Object.keys(captured.expectedHeaders))
        || Object.keys(actualHeaders).some(name => actualHeaders[name] !== captured.expectedHeaders[name])) return false;
      const data = parse(request.body);
      if (!object(data, ["model", "messages", "stream", "stream_options", "temperature", "max_tokens"])
        || data.model !== captured.model || data.stream !== true
        || !object(data.stream_options, ["include_usage"]) || data.stream_options.include_usage !== true
        || !(data.temperature instanceof NumberToken) || data.temperature.token !== "0"
        || !integer(data.max_tokens, captured.maxTokens)
        || !Array.isArray(data.messages) || data.messages.length !== captured.messages.length) return false;
      return data.messages.every((message, index) => object(message, ["role", "content"])
        && message.role === captured.messages[index].role && message.content === captured.messages[index].content);
    } catch { return false; }
  };
}
