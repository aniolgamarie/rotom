// 插件辅助请求复用当前受约束ModelRuntime，不通过provider或compat创建另一条调用链。
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

export function pluginModelMethod(capability, method) {
  if (!["complete", "completeSimple", "stream", "streamSimple"].includes(method)) reject("PLUGIN_MODEL_METHOD", 2);
  return (model, context, options = {}) => {
    const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    requireOrdinaryHelper(runtime, capability);
    const current = runtime.models?.current;
    if (typeof current?.[method] !== "function") reject("PLUGIN_MODEL_UNAVAILABLE", 5);
    return current[method](model, context, { ...options, maxRetries: 0 });
  };
}

export function selectedPluginModel(capability, reference, currentModel) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  requireOrdinaryHelper(runtime, capability);
  let provider = currentModel?.provider, modelId = currentModel?.id;
  if (reference !== undefined) {
    if (typeof reference !== "string" || /[\s\x00-\x1f\x7f]/.test(reference) || reference.indexOf("/") < 1) reject("PLUGIN_MODEL_REFERENCE", 2);
    const split = reference.indexOf("/"); provider = reference.slice(0, split); modelId = reference.slice(split + 1);
  }
  const model = runtime.models?.current?.getModel(provider, modelId);
  if (!model || model.provider !== provider || model.id !== modelId) reject("PLUGIN_MODEL_NOT_SELECTED", 2);
  return model;
}

export function selectedPluginModels(capability) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  requireOrdinaryHelper(runtime, capability);
  if (!runtime.models?.current?.getModels) reject("PLUGIN_MODEL_UNAVAILABLE", 5);
  return runtime.models.current.getModels();
}

export function ownedCompactionHook(handler) {
  return async (...args) => {
    try {
      const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
      requireOrdinaryHelper(runtime, "pi-smart-compact");
      const result = await handler(...args);
      return result?.compaction ? result : { cancel: true };
    } catch { return { cancel: true }; }
  };
}
