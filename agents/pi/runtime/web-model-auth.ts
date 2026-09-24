// 搜索订阅账号只读取显式用途所指的实例 ModelRuntime；可用性查询不刷新或读取凭据。
import { createHash } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
function runtime() {
  const value = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!value || value.owner?.role !== "manager" || !value.manifest.plugins.includes("pi-web")) reject("WEB_NOT_SELECTED", 5);
  return value;
}
export function webSearchModel(purpose) {
  if (!["openai", "xai", "kimi"].includes(purpose)) reject("WEB_MODEL_PURPOSE", 2);
  const value = runtime(), binding = value.manifest.web_model_bindings?.[purpose];
  if (!binding) return undefined;
  return value.models?.current?.getModel(binding.provider, binding.model);
}
export function webSearchAuthAvailable(purpose) {
  const model = webSearchModel(purpose);
  return Boolean(model && runtime().models.current.hasConfiguredAuth?.(model.provider));
}
export async function webSearchAuth(purpose, signal) {
  const value = runtime(); requireOrdinaryHelper(value, "pi-web", value.web?.scope?.getStore()?.id ?? null);
  if (!value.manifest.web_model_bindings?.[purpose]) return undefined;
  const model = webSearchModel(purpose);
  if (!model) reject("WEB_MODEL_NOT_SELECTED", 2);
  const operation = value.web?.current();
  if (!operation) reject("WEB_OPERATION_CLOSED", 4);
  const combined = AbortSignal.any([operation.controller.signal, ...(signal ? [signal] : [])]);
  combined.throwIfAborted();
  const provider = value.manifest.provider_bindings?.[model.provider], environment = {};
  if (!provider || !["api-key", "oauth"].includes(provider.auth_kind)) reject("WEB_MODEL_PROVIDER_UNBOUND", 2);
  if (provider.auth_kind === "api-key") {
    if (typeof provider.logical_id !== "string" || !provider.logical_id) reject("WEB_MODEL_PROVIDER_UNBOUND", 2);
    const name = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update(provider.logical_id).digest("hex").slice(0, 16).toUpperCase();
    if (process.env[name]) environment[name] = process.env[name];
  }
  const resolution = await value.web.track(Promise.resolve().then(async () => {
    combined.throwIfAborted();
    try { return await value.models.current.getAuth(model, { signal: combined, env: environment }); }
    catch { reject("WEB_MODEL_AUTH_FAILED", 3); }
  }));
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== value) reject("WEB_MODEL_STALE", 4);
  combined.throwIfAborted(); requireOrdinaryHelper(value, "pi-web", value.web?.scope?.getStore()?.id ?? null);
  if (!resolution?.auth || typeof resolution.auth !== "object") reject("WEB_MODEL_AUTH_REQUIRED", 3);
  const headers = resolution.auth.headers ?? {};
  let apiKey = resolution.auth.apiKey;
  if (!apiKey) for (const [name, text] of Object.entries(headers)) {
    if (name.toLowerCase() === "authorization" && typeof text === "string") apiKey = /^Bearer\s+(.+)$/i.exec(text)?.[1];
  }
  if (typeof apiKey !== "string" || !apiKey || /[\x00-\x1f\x7f]/.test(apiKey)) reject("WEB_MODEL_AUTH_REQUIRED", 3);
  return { model, apiKey, headers };
}
