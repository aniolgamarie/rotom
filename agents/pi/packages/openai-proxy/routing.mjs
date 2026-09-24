import { Dispatcher, ProxyAgent, fetch as proxyFetch, getGlobalDispatcher, setGlobalDispatcher } from "undici";
import { createDiagnostics, MeteredProxyDispatcher, snapshot } from "./diagnostics.mjs";
import { createHash } from "node:crypto";

function selectedProxy() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  const id = runtime?.manifest.options.network?.openai_proxy_route;
  const route = runtime?.manifest.options.network?.routes?.[id];
  if (!runtime || runtime.owner?.role !== "manager" || !route || route.mode !== "proxy") throw new Error("OPENAI_PROXY_ROUTE_REQUIRED");
  const url = new URL(route.proxy_url);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("OPENAI_PROXY_ROUTE_INVALID");
  const variable = "AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update(id).digest("hex").slice(0, 16).toUpperCase();
  const token = route.credential_ref ? process.env[variable] : undefined;
  if (route.credential_ref && (!token || /[\r\n\0]/.test(token))) throw new Error("OPENAI_PROXY_CREDENTIAL_REQUIRED");
  return { uri: route.proxy_url, token, authIdentity: createHash("sha256").update(token ?? "").digest("hex") };
}
function rejectManagedHelper() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (runtime?.managedRequestScope?.getStore()) throw new Error("UNMETERED_PROXY_HELPER_DENIED");
}
const STATE_KEY = Symbol.for("starter.pi.openai-proxy");
export const VERSION = "0.2.0";

export function isOpenAIOrigin(origin) {
  const url = new URL(origin);
  if (url.protocol !== "https:" && url.protocol !== "http:") return false;
  return ["openai.com", "chatgpt.com"].some(
    (domain) => url.hostname === domain || url.hostname.endsWith(`.${domain}`),
  );
}

export class OpenAIProxyDispatcher extends Dispatcher {
  constructor(fallback, proxy) {
    super();
    this.fallback = fallback;
    this.proxy = proxy;
  }

  dispatch(options, handler) {
    rejectManagedHelper();
    const target = isOpenAIOrigin(options.origin) ? this.proxy : this.fallback;
    return target.dispatch(options, handler);
  }

  // The fallback belongs to Pi; this extension only owns the proxy pool.
  close(...args) { return this.proxy.close(...args); }
  destroy(...args) { return this.proxy.destroy(...args); }
}

export function createOpenAIProxyFetch(fallback, proxy, fetchThroughProxy = proxyFetch) {
  return async (input, init) => {
    rejectManagedHelper();
    const url = typeof input === "string" || input instanceof URL ? input : input.url;
    if (!isOpenAIOrigin(url)) return fallback(input, init);
    return fetchThroughProxy(input, { ...init, dispatcher: proxy });
  };
}

export function installOpenAIProxy({ reload = false } = {}) {
  const current = getGlobalDispatcher();
  const previous = globalThis[STATE_KEY];
  const { uri, token, authIdentity } = selectedProxy();
  const proxyUrl = new URL(uri);
  const existingPool = previous?.rawProxy ?? previous?.proxy;
  const reusePool = existingPool && !existingPool.closed && !existingPool.destroyed
    && previous.uri === uri && previous.authIdentity === authIdentity;
  if (!reload && reusePool && previous?.version === VERSION
    && current === previous.dispatcher && globalThis.fetch === previous.fetch) return current;

  // Keep one pool across /reload; do not interrupt an in-flight request.
  const rawProxy = reusePool ? existingPool : new ProxyAgent({
    uri,
    ...(token ? { token } : {}),
    allowH2: false,
    headersTimeout: 300_000,
    bodyTimeout: 300_000,
    connect: { autoSelectFamilyAttemptTimeout: 2_000 },
  });
  const diagnostics = previous?.diagnostics ?? createDiagnostics();
  for (const stats of [diagnostics.total, diagnostics.active, diagnostics.last]) {
    if (stats) stats.cancellations ??= 0;
  }
  const proxy = new MeteredProxyDispatcher(rawProxy, diagnostics);
  const fallbackDispatcher = current === previous?.dispatcher ? previous.dispatcher.fallback : current;
  const dispatcher = new OpenAIProxyDispatcher(fallbackDispatcher, proxy);
  setGlobalDispatcher(dispatcher);
  // Pi calls configureHttpDispatcher() again AFTER loading extensions, before
  // --list-models and session_start. A global dispatcher alone gets replaced.
  // Pi preserves deliberate fetch overrides, so OAuth, catalog and SSE fetches
  // also select the proxy explicitly, independently of the global dispatcher.
  const originalFetch = globalThis.fetch === previous?.fetch && previous.originalFetch
    ? previous.originalFetch : globalThis.fetch;
  const fetch = createOpenAIProxyFetch(originalFetch, proxy);
  globalThis.fetch = fetch;
  globalThis[STATE_KEY] = { version: VERSION, uri, authIdentity, proxyLabel: proxyUrl.origin, dispatcher, rawProxy, proxy, fetch, originalFetch, diagnostics };
  if (existingPool && !reusePool) void existingPool.close().catch(() => {});
  return dispatcher;
}

export function getProxyDiagnostics() {
  return globalThis[STATE_KEY]?.diagnostics;
}

export function getProxyStatus() {
  const state = globalThis[STATE_KEY];
  if (!state) return { installed: false };
  return {
    installed: true,
    version: state.version,
    proxy: state.proxyLabel,
    fetchActive: globalThis.fetch === state.fetch,
    dispatcherActive: getGlobalDispatcher() === state.dispatcher,
    poolOpen: !state.rawProxy.closed && !state.rawProxy.destroyed,
    total: snapshot(state.diagnostics.total),
    current: state.diagnostics.active ? snapshot(state.diagnostics.active) : null,
    last: state.diagnostics.last ? snapshot(state.diagnostics.last) : null,
  };
}
