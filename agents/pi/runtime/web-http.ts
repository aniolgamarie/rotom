// Web 独立声明服务与线路；使用自己的 dispatcher，不修改全局 fetch，也不回退到 curl/环境代理。
import { createHash } from "node:crypto";
import { lookup as dnsLookup } from "node:dns/promises";
import { isIP } from "node:net";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { runtimeModule } from "./runtime-module.ts";
import { reject } from "./managed-types.ts";
import { addressPolicy, checkWebHostname } from "./web-address.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
const redirects = new Set([301, 302, 303, 307, 308]);
const sensitiveHeaders = ["authorization", "cookie", "x-api-key", "x-goog-api-key", "x-subscription-token", "api-key"];
async function cancelable(value, signal) {
  value = Promise.resolve(value);
  if (signal.aborted) { void value.catch(() => {}); signal.throwIfAborted(); }
  signal.throwIfAborted();
  let stop;
  const canceled = new Promise((_, fail) => { stop = () => fail(new Error("WEB_REQUEST_ABORTED")); signal.addEventListener("abort", stop, { once: true }); });
  try { return await Promise.race([value, canceled]); }
  finally { signal.removeEventListener("abort", stop); }
}
function limit(value, fallback, maximum) {
  value ??= fallback;
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) reject("WEB_HTTP_LIMIT_INVALID", 2);
  return value;
}

export async function createWebFetch(runtime, name, { fetchImpl, dispatcherFactory, lookup = dnsLookup, serviceRunId = null, routeName, onProxyFailure = () => {} } = {}) {
  requireOrdinaryHelper(runtime, "pi-web", serviceRunId);
  const binding = runtime.manifest.web_services?.[name];
  routeName ??= binding?.network_route;
  const route = runtime.manifest.options.network?.routes?.[routeName];
  if (!binding || !["api", "public"].includes(binding.type) || !route?.service_ids?.includes("web:" + name)
      || !["direct", "proxy"].includes(route.mode)) reject("WEB_HTTP_BINDING_REQUIRED", 2);
  const origins = new Set(binding.origins ?? []);
  if (binding.type === "api" && !origins.size) reject("WEB_HTTP_BINDING_REQUIRED", 2);
  for (const origin of origins) {
    const url = new URL(origin);
    if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.origin !== origin) reject("WEB_HTTP_ORIGIN_INVALID", 2);
  }
  const checkAddress = addressPolicy(binding.allow_ranges);
  const maxRequest = limit(binding.max_request_bytes, ["gemini-api", "gemini-web"].includes(name) ? 64 * 1024 * 1024 : 8 * 1024 * 1024, 1024 ** 3);
  const maxResponse = limit(binding.max_response_bytes, 128 * 1024 * 1024, 1024 ** 3);
  const maxHeaders = limit(binding.max_header_bytes, name === "gemini-web" ? 4 * 1024 * 1024 : 16384, 8 * 1024 * 1024);
  const timeout = limit(binding.timeout_ms, 120000, 1800000);
  let authorization;
  if (route.mode === "proxy") {
    let proxy;
    try { proxy = new URL(route.proxy_url); } catch { reject("WEB_PROXY_INVALID", 2); }
    if (!/^https?:$/.test(proxy.protocol) || proxy.username || proxy.password || proxy.search || proxy.hash || proxy.pathname !== "/") reject("WEB_PROXY_INVALID", 2);
    if (route.credential_ref) {
      authorization = process.env["AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update(routeName).digest("hex").slice(0, 16).toUpperCase()];
      if (!authorization || /[\r\n\0]/.test(authorization)) reject("WEB_PROXY_CREDENTIAL_REQUIRED", 3);
    }
  }
  const native = fetchImpl && dispatcherFactory ? null : await runtimeModule("undici");
  fetchImpl ??= native.fetch;
  const pool = (origin, options) => new native.Pool(origin, { ...options, maxHeaderSize: maxHeaders, pipelining: 1 });
  dispatcherFactory ??= ({ route, servername }) => route.mode === "proxy"
    ? new native.ProxyAgent({ uri: route.proxy_url, ...(authorization ? { token: authorization } : {}),
      requestTls: servername ? { servername } : {}, factory: pool, clientFactory: pool })
    : new native.Agent({ connect: servername ? { servername } : {}, factory: pool });
  const active = new Set(), lifetime = new AbortController(); let closed = false, proxyFailed = false, count = 0;
  const finishEntry = entry => entry.finish ??= Promise.resolve().then(async () => {
    try { await entry.dispatcher.destroy(); } catch { throw new Error("WEB_TERMINATION_UNKNOWN"); }
    active.delete(entry);
  });
  const maximum = limit(binding.max_requests, 1024, 4096);
  const assertCurrent = () => {
    if (globalThis[slot] !== runtime || closed) reject("WEB_HTTP_CLOSED", 4);
    requireOrdinaryHelper(runtime, "pi-web", serviceRunId);
    if (proxyFailed) reject("WEB_PROXY_FAILED", 5);
  };
  const once = async outbound => {
    assertCurrent();
    const requestSignal = AbortSignal.any([outbound.signal, lifetime.signal, AbortSignal.timeout(timeout)]);
    requestSignal.throwIfAborted();
    if (++count > maximum) reject("WEB_HTTP_REQUEST_LIMIT", 4);
    const url = new URL(outbound.url);
    if (!/^https?:$/.test(url.protocol) || url.username || url.password
        || !["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"].includes(outbound.method)) reject("WEB_HTTP_REQUEST_INVALID", 2);
    const headers = new Headers(outbound.headers);
    for (const key of ["host", "proxy-authorization", "content-length", "connection", "transfer-encoding"]) headers.delete(key);
    let address, servername;
    if (binding.type === "api") {
      if (!origins.has(url.origin)) reject("WEB_HTTP_ORIGIN_DENIED", 4);
    } else {
      if (!["GET", "HEAD"].includes(outbound.method)) reject("WEB_PUBLIC_METHOD_DENIED", 4);
      for (const header of sensitiveHeaders) headers.delete(header);
      const host = checkWebHostname(url, binding);
      if (isIP(host)) { checkAddress(host); address = host; }
      else {
        let addresses;
        try { addresses = await cancelable(lookup(host, { all: true, verbatim: true }), requestSignal); }
        catch { reject(requestSignal.aborted ? "WEB_REQUEST_ABORTED" : "WEB_DNS_FAILED", requestSignal.aborted ? 4 : 5); }
        if (!Array.isArray(addresses) || !addresses.length || addresses.length > 64) reject("WEB_DNS_FAILED", 5);
        for (const row of addresses) {
          if (![4, 6].includes(row.family) || isIP(row.address) !== row.family) reject("WEB_ADDRESS_INVALID", 4);
          checkAddress(row.address);
        }
        address = addresses[0].address;
      }
      servername = isIP(host) ? undefined : host;
      headers.set("host", url.host);
    }
    assertCurrent();
    requestSignal.throwIfAborted();
    const wireUrl = new URL(url);
    if (address) wireUrl.hostname = isIP(address) === 6 ? "[" + address + "]" : address;
    const dispatcher = await dispatcherFactory({ route, servername, address, authorization, maxHeaders });
    const controller = new AbortController();
    const entry = { controller, dispatcher, finish: null };
    const finish = () => finishEntry(entry);
    active.add(entry);
    try {
      assertCurrent();
      const signal = AbortSignal.any([requestSignal, controller.signal]);
      signal.throwIfAborted();
      let sent = 0;
      const body = outbound.body?.pipeThrough(new TransformStream({ transform(chunk, output) {
        assertCurrent(); signal.throwIfAborted();
        sent += chunk.byteLength;
        if (sent > maxRequest) { controller.abort(); reject("WEB_REQUEST_OVERSIZE", 2); }
        output.enqueue(chunk);
      } }));
      const response = await fetchImpl(wireUrl.href, { method: outbound.method, headers: Object.fromEntries(headers),
        ...(body ? { body, duplex: "half" } : {}), signal, redirect: "manual", dispatcher });
      assertCurrent();
      if (!response.body) { await finish(); return response; }
      const reader = response.body.getReader(); let received = 0;
      const stream = new ReadableStream({ async pull(output) {
        try {
          assertCurrent();
          const item = await reader.read();
          assertCurrent(); signal.throwIfAborted();
          if (item.done) { await finish(); output.close(); return; }
          received += item.value.byteLength;
          if (received > maxResponse) reject("WEB_RESPONSE_OVERSIZE", 5);
          output.enqueue(item.value);
        } catch {
          controller.abort();
          if (route.mode === "proxy") { proxyFailed = true; onProxyFailure(); }
          await reader.cancel().catch(() => {}); await finish();
          output.error(new Error(route.mode === "proxy" ? "WEB_PROXY_FAILED" : "WEB_HTTP_BODY_FAILED"));
        }
      }, async cancel() { controller.abort(); await reader.cancel().catch(() => {}); await finish(); } });
      const result = new Response(stream, { status: response.status, statusText: response.statusText, headers: response.headers });
      Object.defineProperty(result, "url", { value: url.href });
      return result;
    } catch {
      controller.abort();
      if (route.mode === "proxy") { proxyFailed = true; onProxyFailure(); }
      await finish();
      reject(route.mode === "proxy" ? "WEB_PROXY_FAILED" : "WEB_HTTP_FAILED", 5);
    }
  };
  const fetch = async (input, init) => {
    // 非标准 dispatcher/__proxy 不能覆盖所选线路；调用方需选择另一条已声明绑定。
    if (init && (Object.hasOwn(init, "dispatcher") || Object.hasOwn(init, "__proxy"))) reject("WEB_ROUTE_OVERRIDE_UNBOUND", 2);
    let request;
    try { request = new Request(input, init); } catch { reject("WEB_HTTP_REQUEST_INVALID", 2); }
    let replayBody = init?.body;
    for (let hop = 0; ; hop++) {
      const response = await once(request);
      if (!redirects.has(response.status) || request.redirect === "manual" || !response.headers.get("location")) return response;
      await response.body?.cancel();
      if (request.redirect === "error" || hop >= 5) reject("WEB_REDIRECT_FORBIDDEN", 4);
      const next = new URL(response.headers.get("location"), request.url);
      let method = request.method, headers = new Headers(request.headers);
      if (response.status === 303 && !["GET", "HEAD"].includes(method) || [301, 302].includes(response.status) && method === "POST") {
        method = "GET"; replayBody = undefined; headers.delete("content-type"); headers.delete("content-length");
      }
      if (next.origin !== new URL(request.url).origin) for (const name of [...sensitiveHeaders, ...(binding.credential_headers ?? [])]) headers.delete(name);
      if (!["GET", "HEAD"].includes(method) && (replayBody === undefined || replayBody instanceof ReadableStream)) reject("WEB_REDIRECT_BODY_UNREPLAYABLE", 4);
      request = new Request(next, { method, headers, signal: request.signal, redirect: request.redirect,
        ...(!["GET", "HEAD"].includes(method) ? { body: replayBody, duplex: "half" } : {}) });
    }
  };
  fetch.close = async () => {
    closed = true; lifetime.abort();
    await Promise.all([...active].map(entry => { entry.controller.abort(); return finishEntry(entry); }));
  };
  return fetch;
}
