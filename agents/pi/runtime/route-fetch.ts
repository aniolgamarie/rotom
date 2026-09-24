// 直接/代理线路均显式绑定；代理失败不重试，不读取环境代理或切到直连。
import http from "node:http";
import https from "node:https";
import { Readable } from "node:stream";
import { canonical, clone, reject } from "./managed-types.ts";
import { runtimeModule } from "./runtime-module.ts";

export async function createRouteFetch(route, { httpRequest = http.request, httpsRequest = https.request, proxyAgent } = {}) {
  const selected = clone(route), endpoint = new URL(route.base_url);
  let agent = false;
  if (route.type === "proxy") {
    if (!route.proxy_url) reject("PROXY_ROUTE_MISSING", 2);
    if (proxyAgent) agent = await proxyAgent(route.proxy_url, endpoint.protocol);
    else if (endpoint.protocol === "https:") {
      const { HttpsProxyAgent } = await runtimeModule("https-proxy-agent");
      agent = new HttpsProxyAgent(route.proxy_url);
    } else {
      const { HttpProxyAgent } = await runtimeModule("http-proxy-agent");
      agent = new HttpProxyAgent(route.proxy_url);
    }
  } else if (route.type !== "direct" || route.proxy_url !== null) reject("PROXY_ROUTE_INVALID", 2);
  let closed = false;
  const fetch = async (url, options, current) => {
    if (closed || canonical(current) !== canonical(selected) || new URL(url).origin !== endpoint.origin
        || options.redirect !== "error" || options.method !== "POST" || typeof options.body !== "string") reject("MODEL_ROUTE_MISMATCH", 4);
    return new Promise((resolve, fail) => {
      const request = (endpoint.protocol === "https:" ? httpsRequest : httpRequest)(url, {
        method: options.method, headers: Object.fromEntries(new Headers(options.headers)), agent,
        signal: options.signal,
      }, response => {
        try {
          const headers = new Headers();
          for (const [name, value] of Object.entries(response.headers)) {
            if (Array.isArray(value)) for (const item of value) headers.append(name, item);
            else if (value !== undefined) headers.set(name, value);
          }
          if (response.statusCode >= 300 && response.statusCode < 400) {
            response.destroy(); fail(new Error("PROXY_REDIRECT_FORBIDDEN")); return;
          }
          resolve(new Response(Readable.toWeb(response), { status: response.statusCode, headers }));
        } catch { response.destroy(); fail(new Error("ROUTE_RESPONSE_INVALID")); }
      });
      request.once("error", () => fail(new Error("ROUTE_TRANSPORT_FAILED")));
      request.end(options.body);
    });
  };
  fetch.close = () => { closed = true; if (agent) agent.destroy(); };
  return fetch;
}
