// MCP HTTP 请求固定服务源站和线路；不使用全局 fetch、环境代理或跨源重定向。
import http from "node:http";
import https from "node:https";
import { Readable } from "node:stream";
import { createHash } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { runtimeModule } from "./runtime-module.ts";
import { reject } from "./managed-types.ts";

async function boundedBody(request, signal) {
  if (signal.aborted) reject("MCP_REQUEST_ABORTED", 4);
  if (!request.body) return Buffer.alloc(0);
  const reader = request.body.getReader(), chunks = [];
  let length = 0, abort;
  const interrupted = new Promise((_, fail) => {
    abort = () => { void reader.cancel().catch(() => {}); fail(new Error("MCP_REQUEST_ABORTED")); };
    signal.addEventListener("abort", abort, { once: true });
  });
  try {
    if (signal.aborted) abort();
    while (true) {
      const item = await Promise.race([reader.read(), interrupted]);
      if (signal.aborted) reject("MCP_REQUEST_ABORTED", 4);
      if (item.done) return Buffer.concat(chunks, length);
      length += item.value.byteLength;
      if (length > 1024 * 1024) {
        void reader.cancel().catch(() => {});
        reject("MCP_REQUEST_OVERSIZE", 2);
      }
      chunks.push(Buffer.from(item.value));
    }
  } finally {
    signal.removeEventListener("abort", abort);
    reader.releaseLock();
  }
}

export async function mcpHttpFetch(runtime, name, { httpRequest = http.request, httpsRequest = https.request, proxyAgent } = {}) {
  requireOrdinaryHelper(runtime, "pi-mcp");
  const binding = runtime.manifest.options.mcp?.servers?.[name];
  const server = runtime.manifest.mcp_config?.mcpServers?.[name];
  const route = runtime.manifest.options.network?.routes?.[binding?.network_route];
  if (!server?.url || !route?.service_ids?.includes("mcp:" + name) || !["streamable-http", "sse"].includes(binding.transport)) reject("MCP_HTTP_BINDING_REQUIRED", 2);
  const endpoint = new URL(server.url);
  const oauth = binding.authentication === "oauth" && server.auth === "oauth";
  const origins = new Set([endpoint.origin]);
  if (oauth) {
    if (!binding.oauth?.allowed_origins?.length) reject("MCP_OAUTH_BINDING_REQUIRED", 2);
    for (const value of binding.oauth.allowed_origins) {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") reject("MCP_OAUTH_ORIGIN_INVALID", 2);
      origins.add(url.origin);
    }
  }
  let closed = false;
  const agents = new Map(), pendingAgents = new Map();
  const agentFor = async protocol => {
    if (closed) reject("MCP_REQUEST_ABORTED", 4);
    if (route.mode === "direct") return false;
    if (route.mode !== "proxy") reject("MCP_HTTP_ROUTE_INVALID", 2);
    if (agents.has(protocol)) return agents.get(protocol);
    if (!pendingAgents.has(protocol)) pendingAgents.set(protocol, (async () => {
      const variable = "AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update(binding.network_route).digest("hex").slice(0, 16).toUpperCase();
      const authorization = route.credential_ref ? process.env[variable] : undefined;
      if (route.credential_ref && (!authorization || /[\r\n\0]/.test(authorization))) reject("MCP_PROXY_CREDENTIAL_REQUIRED", 3);
      const options = authorization ? { headers: { "Proxy-Authorization": authorization } } : {};
      let agent;
      if (proxyAgent) agent = await proxyAgent(route.proxy_url, protocol, options);
      else {
        const module = await runtimeModule(protocol === "https:" ? "https-proxy-agent" : "http-proxy-agent");
        const Agent = protocol === "https:" ? module.HttpsProxyAgent : module.HttpProxyAgent;
        agent = new Agent(route.proxy_url, options);
      }
      if (closed) { agent.destroy(); reject("MCP_REQUEST_ABORTED", 4); }
      agents.set(protocol, agent);
      return agent;
    })());
    return pendingAgents.get(protocol);
  };
  await agentFor(endpoint.protocol);
  const requests = new Set(), lifetime = new AbortController();
  const fetch = async (input, init) => {
    requireOrdinaryHelper(runtime, "pi-mcp");
    const outbound = new Request(input, init), url = new URL(outbound.url);
    if (closed || !origins.has(url.origin) || url.username || url.password || !["GET", "HEAD", "POST", "DELETE"].includes(outbound.method)) reject("MCP_HTTP_ROUTE_MISMATCH", 4);
    const headers = new Headers(outbound.headers);
    if (server.auth === "bearer") {
      const token = process.env[server.bearerTokenEnv];
      if (!token || /[\r\n\0]/.test(token)) reject("MCP_CREDENTIAL_REQUIRED", 3);
      headers.set("authorization", "Bearer " + token);
    } else if (server.auth === false) headers.delete("authorization");
    else if (oauth) {
      // 服务访问令牌不能被 SDK 发现请求带到另一授权源站。
      if (url.origin !== endpoint.origin && /^Bearer\s/i.test(headers.get("authorization") ?? "")) headers.delete("authorization");
    } else reject("MCP_AUTH_TRANSPORT_NOT_READY", 5);
    headers.delete("host"); headers.delete("proxy-authorization"); headers.delete("content-length");
    const signal = AbortSignal.any([outbound.signal, lifetime.signal, AbortSignal.timeout(60000)]);
    const body = await boundedBody(outbound, signal);
    // 读取流期间可能退出或撤销上下文；不可在 close 后补发网络请求。
    requireOrdinaryHelper(runtime, "pi-mcp");
    const agent = await agentFor(url.protocol);
    if (closed || signal.aborted) reject("MCP_REQUEST_ABORTED", 4);
    return new Promise((resolve, fail) => {
      const request = (url.protocol === "https:" ? httpsRequest : httpRequest)(url, {
        method: outbound.method, headers: Object.fromEntries(headers), agent,
        signal,
      }, response => {
        if (response.statusCode >= 300 && response.statusCode < 400) {
          response.destroy(); fail(new Error("MCP_REDIRECT_FORBIDDEN")); return;
        }
        try {
          const responseHeaders = new Headers();
          for (const [key, value] of Object.entries(response.headers)) {
            for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) responseHeaders.append(key, item);
          }
          const empty = [204, 205, 304].includes(response.statusCode) || outbound.method === "HEAD";
          if (empty) response.resume();
          resolve(new Response(empty ? null : Readable.toWeb(response), { status: response.statusCode, headers: responseHeaders }));
        } catch { response.destroy(); fail(new Error("MCP_HTTP_RESPONSE_INVALID")); }
      });
      requests.add(request);
      request.once("close", () => requests.delete(request));
      request.once("error", () => fail(new Error("MCP_HTTP_TRANSPORT_FAILED")));
      request.end(body);
    });
  };
  fetch.close = () => { closed = true; lifetime.abort(); for (const request of requests) request.destroy(); requests.clear(); for (const agent of agents.values()) agent.destroy(); agents.clear(); };
  return fetch;
}
