// 摘要、改写与问答仅选择当前实例模型，调用完成前持续保留 Web 活动。
import { runWebModel } from "./web-model-execution.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { selectedPluginModel, selectedPluginModels } from "./plugin-model.ts";
import { reject } from "./managed-types.ts";
function runtime() {
  const value = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  requireOrdinaryHelper(value, "pi-web"); return value;
}
export function webModels() { runtime(); return selectedPluginModels("pi-web"); }
export function webModel(purpose, reference, currentModel) {
  const value = runtime();
  if (!["summary", "answer", "rewrite", "openai", "xai", "kimi", "gemini"].includes(purpose)) reject("WEB_MODEL_PURPOSE", 2);
  const bound = value.manifest.web_model_bindings?.[purpose];
  const selected = reference ?? (bound ? bound.provider + "/" + bound.model : undefined);
  return selectedPluginModel("pi-web", selected, currentModel);
}
export function webComplete(model, context, options = {}) {
  const value = runtime(), operation = value.web?.current();
  if (!operation) reject("WEB_OPERATION_CLOSED", 4);
  const selected = selectedPluginModel("pi-web", model.provider + "/" + model.id);
  if (!value.models?.current?.completeSimple) reject("WEB_MODEL_UNAVAILABLE", 5);
  if (Object.keys(options).some(name => !["signal", "maxTokens", "reasoning", "reasoningEffort"].includes(name))) reject("WEB_MODEL_OPTIONS", 2);
  if (options.reasoning !== undefined && options.reasoningEffort !== undefined && options.reasoning !== options.reasoningEffort) reject("WEB_MODEL_REASONING_CONFLICT", 2);
  const reasoning = options.reasoning ?? options.reasoningEffort;
  if (reasoning !== undefined && !["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(reasoning)) reject("WEB_MODEL_REASONING", 2);
  const signal = AbortSignal.any([operation.controller.signal, ...(options.signal ? [options.signal] : [])]);
  signal.throwIfAborted();
  const pending = Promise.resolve().then(() => {
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== value) reject("WEB_MODEL_STALE", 4);
    requireOrdinaryHelper(value, "pi-web"); signal.throwIfAborted();
    return runWebModel(value, signal, ownedSignal => value.models.current.completeSimple(selected, context, { signal: ownedSignal, maxRetries: 0,
      ...(options.maxTokens !== undefined ? { maxTokens: options.maxTokens } : {}),
      ...(reasoning !== undefined && reasoning !== "off" ? { reasoning } : {}) }));
  }).then(result => {
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== value) reject("WEB_MODEL_STALE", 4);
    signal.throwIfAborted(); requireOrdinaryHelper(value, "pi-web"); return result;
  });
  return value.web.track(pending);
}
