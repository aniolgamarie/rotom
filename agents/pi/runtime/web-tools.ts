// Web 入口先核验实际登记与运行时，再交给唯一 manager 管理请求和后台工作。
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
import { closeWebCurators, webCuratorSettings } from "./web-listener.ts";
import { claimTool } from "./tool-ownership.ts";
const registries = new WeakMap();
export function bindWebTools(pi) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager" || !runtime.manifest.plugins.includes("pi-web")) reject("WEB_NOT_SELECTED", 5);
  const owner = {}, claims = new Set();
  let closed = false;
  const current = (serviceId = null) => {
    if (closed || globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_TOOL_STALE", 4);
    requireOrdinaryHelper(runtime, "pi-web", serviceId);
  };
  const handler = (label, definition) => ({ ...definition, async handler(...args) {
    current();
    if (!runtime.web?.run) reject("WEB_RUNTIME_UNAVAILABLE", 5);
    let serviceId = null;
    const result = await runtime.web.run(label, undefined, () => {
      serviceId = runtime.web.current?.()?.id ?? null;
      return definition.handler(...args);
    });
    current(serviceId); return result;
  } });
  let records = registries.get(runtime);
  if (!records) registries.set(runtime, records = new Map());
  return {
    registerTool(definition) {
      if (typeof definition.execute !== "function" || definition.parameters?.type !== "object") reject("WEB_TOOL_INVALID", 2);
      const claim = claimTool(runtime, definition.name, owner, "WEB");
      claims.add(claim); records.set(definition.name, claim);
      const check = (serviceId = null) => {
        if (!claim.current() || records.get(definition.name) !== claim) reject("WEB_TOOL_STALE", 4);
        requireOrdinaryHelper(runtime, "pi-web", serviceId);
      };
      try {
        pi.registerTool({ ...definition, parameters: { ...definition.parameters, additionalProperties: false },
          async execute(id, params, signal, onUpdate, ctx) {
            check();
            if (params?.workflow === "summary-review") webCuratorSettings(runtime);
            if (!runtime.web?.run) reject("WEB_RUNTIME_UNAVAILABLE", 5);
            let serviceId = null;
            const result = await runtime.web.run(definition.name, signal, ownedSignal => {
              serviceId = runtime.web.current?.()?.id ?? null;
              return definition.execute(id, params, ownedSignal, onUpdate, ctx);
            });
            check(serviceId); return result;
          },
        });
      } catch (error) {
        claim.release(); claims.delete(claim);
        if (records.get(definition.name) === claim) records.delete(definition.name);
        throw error;
      }
    },
    registerCommand(name, definition) { pi.registerCommand(name, handler("command:" + name, definition)); },
    registerShortcut(key, definition) { pi.registerShortcut(key, handler("shortcut:" + key, definition)); },
    async reset() {
      current();
      await closeWebCurators(runtime);
      await runtime.web?.close?.();
    },
    async close() {
      closed = true;
      for (const claim of claims) claim.release();
      for (const [name, claim] of records) if (claims.has(claim)) records.delete(name);
      claims.clear();
      await closeWebCurators(runtime);
      await runtime.web?.close?.();
    },
  };
}
export function isBoundWebTool(runtime, name) {
  const claim = registries.get(runtime)?.get(name);
  if (!claim?.current()) return false;
  requireOrdinaryHelper(runtime, "pi-web");
  return true;
}
