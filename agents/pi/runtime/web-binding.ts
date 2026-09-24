// 供应方模块使用明确的服务入口；包加载阶段只查询声明，不触碰账号。
import { reject } from "./managed-types.ts";

function runtime() {
  const value = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!value || value.owner?.role !== "manager" || !value.manifest.plugins.includes("pi-web")) reject("WEB_NOT_SELECTED", 5);
  return value;
}
export function webServiceSelected(name) { return Object.hasOwn(runtime().manifest.web_services ?? {}, name); }
export function webFetchFor(name) {
  return (input, init) => {
    const value = runtime();
    if (!webServiceSelected(name)) reject("WEB_SERVICE_NOT_SELECTED", 2);
    if (!value.web?.fetch) reject("WEB_RUNTIME_UNAVAILABLE", 5);
    return value.web.fetch(name, input, init);
  };
}
export function runWebOperation(label, signal, callback) {
  const value = runtime();
  if (!value.web?.run) reject("WEB_RUNTIME_UNAVAILABLE", 5);
  return value.web.run(label, signal, callback);
}
export function trackWebWork(promise) {
  const value = runtime();
  if (!value.web?.track) reject("WEB_RUNTIME_UNAVAILABLE", 5);
  return value.web.track(promise);
}
export function withWebProxy(proxy, callback) {
  const value = runtime();
  if (!value.web?.withProxy) reject("WEB_RUNTIME_UNAVAILABLE", 5);
  return value.web.withProxy(proxy, callback);
}
export function webAuthenticatedFetch(profile, input, init) {
  const value = runtime();
  if (!value.web?.authenticatedFetch) reject("WEB_AUTH_FETCH_UNAVAILABLE", 5);
  return value.web.authenticatedFetch(profile, input, init);
}
export function webProxySelection() {
  const value = runtime();
  if (!value.web?.proxySelection) reject("WEB_RUNTIME_UNAVAILABLE", 5);
  return value.web.proxySelection();
}
