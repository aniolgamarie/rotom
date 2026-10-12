// 官方ModelRuntime的非秘密配置边界。模型/账号发现及凭据解析仍由受信启动器负责。
import { createHash } from "node:crypto";
import { isAbsolute, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { optionalPrivateBytes } from "./private-files.ts";
import { strictJson } from "./strict-json.ts";
import { digest, clone } from "./managed-types.ts";

const fail = (code = "pi-model-config-invalid", exitCode = 2) => { const error = new Error(code); error.exitCode = exitCode; throw error; };
const plain = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value)) && !Object.getOwnPropertySymbols(value).length
  && Object.values(Object.getOwnPropertyDescriptors(value)).every(item => Object.hasOwn(item, "value") && item.enumerable);
const text = value => typeof value === "string" && value.length > 0 && value.length <= 4096 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const id = value => text(value) && /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$/.test(value);
const registryId = value => text(value) && ![".", ".."].includes(value) && !/[\/\\]/.test(value);
const secretRef = value => text(value) && value.startsWith("secret:") && value.length > 7
  && ![".", ".."].includes(value.slice(7)) && !/[\/\\]/.test(value.slice(7));
const bool = value => typeof value === "boolean";
const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
const positive = value => Number.isSafeInteger(value) && value > 0;
const choice = (...values) => value => values.includes(value);
const object = (fields, required = []) => value => plain(value) && required.every(key => Object.hasOwn(value, key) && value[key] !== undefined)
  && Object.entries(value).every(([key, item]) => Object.hasOwn(fields, key) && (item === undefined || fields[key](item)));
const list = check => value => Array.isArray(value) && value.length <= 4096 && value.every(check);
const empty = value => plain(value) && Object.keys(value).length === 0;
const levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const thinkingMap = object(Object.fromEntries(levels.map(key => [key, value => value === null || text(value)])));
const endpoint = value => {
  if (!text(value) || /[\s\\?#$]/u.test(value) || !/^https?:\/\/[^/]/.test(value)) return false;
  try {
    const url = new URL(value), authority = value.split("/")[2];
    return !!url.hostname && !authority.includes("@") && !authority.endsWith(":") && !url.username && !url.password
      && (!url.port || Number(url.port) >= 1 && Number(url.port) <= 65535);
  } catch { return false; }
};
const costs = { input: number, output: number, cacheRead: number, cacheWrite: number };
const cost = object({ ...costs, tiers: list(object({ inputTokensAbove: number, ...costs }, ["inputTokensAbove", ...Object.keys(costs)])) }, Object.keys(costs));
const compatBooleans = ["supportsStore", "supportsDeveloperRole", "supportsReasoningEffort", "supportsUsageInStreaming", "supportsFinishReason",
  "requiresToolResultName", "requiresAssistantAfterToolResult", "requiresThinkingAsText", "requiresReasoningContentOnAssistantMessages", "zaiToolStream",
  "supportsThinkingTokenBudget", "supportsOpenAIGrammarTools", "supportsMidConvoSystemMessages", "supportsMidConvoToolAdditions", "supportsStrictMode",
  "sendSessionAffinityHeaders", "supportsLongCacheRetention", "supportsAdditionalTools", "supportsToolSearch", "supportsExplicitPromptCacheMode",
  "supportsMaxOutputTokens", "supportsEagerToolInputStreaming", "supportsCacheControlOnTools", "supportsTemperature", "forceAdaptiveThinking",
  "allowEmptySignature", "supportsStrictTools", "supportsMidConvoEffort", "supportsMidConvoToolChanges"];
const compat = object({ ...Object.fromEntries(compatBooleans.map(key => [key, bool])),
  maxTokensField: choice("max_completion_tokens", "max_tokens"),
  thinkingFormat: choice("openai", "openrouter", "deepseek", "together", "baseten", "zai", "qwen", "chat-template", "qwen-chat-template", "string-thinking", "ant-ling"),
  thinkingTokenBudgetField: choice("thinking_token_budget", "thinking_budget", "thinking_budget_tokens"), cacheControlFormat: choice("anthropic"),
  sessionAffinityFormat: choice("openai", "openai-nosession", "openrouter"), vllmPriority: value => typeof value === "number" && Number.isFinite(value),
  allowedFallbackModels: list(object({ provider: id, model: id, cost }, ["provider", "model", "cost"])),
});
const input = value => Array.isArray(value) && value.length > 0 && value.every(choice("text", "image")) && new Set(value).size === value.length;
const fields = {
  id, provider: id, api: id, name: text, type: choice("chat"), baseUrl: endpoint, reasoning: bool, input, cost,
  contextWindow: positive, maxTokens: positive, thinkingLevelMap: thinkingMap, compat,
  promptCache: object({ short: number, long: number }),
  inputLimits: object({ maxRequestBytes: positive, images: object({ resize: object({ maxWidth: positive, maxHeight: positive, maxBytes: positive, jpegQuality: number }),
    maxPerMessage: positive, maxPerRequest: positive }) }),
  // 任意sampling/chat-template扩展对象可能含秘密。未有显式契约前拒绝非空内容，不静默丢弃。
  samplingParams: empty, samplingParamsByThinkingLevel: empty,
  // 请求头只进入会话私有基线比较；不能进入公开摘要或错误。
  headers: value => plain(value) && Object.values(value).every(item => typeof item === "string"),
};
const validModel = object(fields, ["id", "provider", "api", "name", "baseUrl", "reasoning", "input", "cost", "contextWindow", "maxTokens"]);
const definitionFields = Object.fromEntries(["id", "input", "name", "reasoning", "contextWindow", "maxTokens", "thinkingLevelMap", "compat"].map(key => [key, fields[key]]));
const validDefinition = object(definitionFields, ["id", "input"]);
const validConfig = object({ api: id, baseUrl: endpoint, models: list(validDefinition) }, ["api", "baseUrl", "models"]);
const validBinding = object({ logical_id: registryId, auth_kind: choice("api-key", "oauth"), owner: id }, ["logical_id", "auth_kind", "owner"]);
const validProvider = object({ logical_id: registryId, auth_kind: choice("api-key", "oauth"), owner: id,
  credential_ref: value => value === null || secretRef(value),
  config: value => value === null || validConfig(value) }, ["logical_id", "auth_kind", "owner", "credential_ref", "config"]);

// 已验证字段的undefined省略，与SDK可选字段的实际构造方式一致。
function project(value) {
  if (Array.isArray(value)) return value.map(project);
  if (plain(value)) return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined).map(([key, item]) => [key, project(item)]));
  return value;
}
function description(model) {
  if (!validModel(model)) fail("pi-model-description-invalid");
  return project(Object.fromEntries(Object.entries(model).filter(([key]) => key !== "headers" && key !== "type")));
}
const modelKey = model => JSON.stringify([model.provider, model.id]);

export function createOfficialModelConfiguration({ manifest, path }) {
  if (typeof path !== "string" || !isAbsolute(path) || resolve(path) !== path || !path.endsWith("/pi-home/models.json")) fail("pi-model-config-path");
  const declaration = manifest.model_configuration, bindings = manifest.provider_bindings, rows = manifest.allowed_models;
  if (!object({ schema_version: choice(1), providers: value => plain(value) && Object.entries(value).every(([key, item]) => id(key) && validProvider(item)) },
    ["schema_version", "providers"])(declaration) || !plain(bindings) || !Object.values(bindings).every(validBinding)
    || !list(object({ provider: id, model: id }, ["provider", "model"]))(rows) || !rows.length) fail();
  if (!isDeepStrictEqual(Object.keys(declaration.providers).sort(), Object.keys(bindings).sort())
      || !isDeepStrictEqual([...new Set(rows.map(row => row.provider))].sort(), Object.keys(bindings).sort())
      || new Set(rows.map(row => modelKey({ provider: row.provider, id: row.model }))).size !== rows.length) fail();
  const selected = rows.map(row => ({ ...row }));
  const expectedModels = new Map(), expectedProviders = {};
  for (const [route, value] of Object.entries(declaration.providers)) {
    const { logical_id, auth_kind, owner, credential_ref, config } = value;
    if (!isDeepStrictEqual(bindings[route], { logical_id, auth_kind, owner })) fail();
    if (auth_kind === "oauth") { if (credential_ref !== null || config !== null) fail(); continue; }
    if (owner !== "pi-environment" || credential_ref === null || config === null) fail();
    const ids = config.models.map(model => model.id);
    if (new Set(ids).size !== ids.length || !isDeepStrictEqual([...ids].sort(), rows.filter(row => row.provider === route).map(row => row.model).sort())) fail();
    const variable = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update(logical_id).digest("hex").slice(0, 16).toUpperCase();
    expectedProviders[route] = { ...clone(config), apiKey: "$" + variable };
    for (const model of config.models) {
      expectedModels.set(modelKey({ provider: route, id: model.id }), description({ ...model, provider: route, api: config.api, baseUrl: config.baseUrl,
        name: model.name ?? model.id, reasoning: model.reasoning ?? false, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: model.contextWindow ?? 128000, maxTokens: model.maxTokens ?? 16384 }));
    }
  }
  const expected = { providers: expectedProviders }, declarationDigest = digest(declaration);
  const checkFile = () => {
    let actual;
    try {
      const bytes = optionalPrivateBytes(path, 1024 * 1024);
      if (bytes === undefined && !Object.keys(expectedProviders).length) actual = { providers: {} };
      else actual = strictJson(new TextDecoder("utf8", { fatal: true }).decode(bytes));
    } catch { fail("pi-model-config-private", 4); }
    // 原文含apiKey/未知字段时仅比较，不散列、不携带到错误。只接受部署生成的引用形式。
    if (!isDeepStrictEqual(actual, expected)) fail("pi-model-config-stale", 4);
  };
  const describe = model => {
    const observed = description(model), expectedModel = expectedModels.get(modelKey(model));
    if (!selected.some(row => row.provider === model.provider && row.model === model.id)) fail("pi-model-not-selected");
    if (expectedModel && !isDeepStrictEqual(observed, expectedModel)) fail("pi-model-config-mismatch", 4);
    return observed;
  };
  checkFile();
  return Object.freeze({ declarationDigest, checkFile, describe });
}

export function createOfficialModels({ manifest, path, modelRuntime }) {
  const configuration = createOfficialModelConfiguration({ manifest, path });
  const checkRuntime = () => {
    // SDK组合失败会记录getError并回落到基础provider，不能只看getModel是否返回对象。
    if (typeof modelRuntime?.getError !== "function" || typeof modelRuntime?.getModel !== "function") fail("pi-model-runtime-incompatible", 5);
    try { if (modelRuntime.getError() !== undefined) fail(); } catch { fail("pi-model-runtime-error", 5); }
    configuration.checkFile();
  };
  checkRuntime();
  return Object.freeze({ declarationDigest: configuration.declarationDigest, checkRuntime, describe: configuration.describe });
}
