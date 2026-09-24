// 认证页面只向所选 HTTPS origin 发送该 profile 的 cookie；不自动读取浏览器账号。
import { webBrowserCookieHeader } from "./web-browser.ts";
import { webCredential } from "./web-config.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
export async function authenticatedWebFetch(runtime, profile, input, init = {}) {
  if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")] !== runtime) reject("WEB_AUTH_FETCH_STALE", 4);
  const operation = runtime.web.current(); requireOrdinaryHelper(runtime, "pi-web", operation.id ?? null);
  const binding = runtime.manifest.web_auth_fetch?.[profile];
  if (!binding) reject("WEB_AUTH_FETCH_NOT_SELECTED", 2);
  let url;
  try { url = new URL(input instanceof Request ? input.url : input); } catch { reject("WEB_AUTH_FETCH_URL", 2); }
  if (url.protocol !== "https:" || url.username || url.password || !binding.origins.includes(url.origin)) reject("WEB_AUTH_FETCH_ORIGIN", 4);
  const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  if (!["GET", "HEAD"].includes(method) || init.body !== undefined && init.body !== null || input instanceof Request && input.body) reject("WEB_AUTH_FETCH_METHOD", 4);
  const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
  if (["cookie", "authorization", "proxy-authorization", "x-api-key"].some(name => headers.has(name))) reject("WEB_AUTH_FETCH_HEADER_OVERRIDE", 4);
  const signal = AbortSignal.any([operation.controller.signal, ...(init.signal ? [init.signal] : []), ...(input instanceof Request ? [input.signal] : [])]);
  signal.throwIfAborted();
  const cookie = binding.browser_profile ? await webBrowserCookieHeader(binding.browser_profile, url, signal) : webCredential(binding.cookie_reference, signal);
  try { headers.set("cookie", cookie); } catch { reject("WEB_AUTH_FETCH_CREDENTIAL_INVALID", 3); }
  // 每次重定向必须重新通过所属 profile 的精确 origin 检查。
  return runtime.web.fetch("authenticated", url, { ...init, method, headers, signal, redirect: "manual" });
}
