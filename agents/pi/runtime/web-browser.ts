// 浏览器认证只使用显式 profile 与监督器副本；原目录从不由插件自行扫描。
import { randomUUID } from "node:crypto";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { webCredential } from "./web-config.ts";
import { closed, reject } from "./managed-types.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), readers = new WeakMap();
const supported = { linux: ["chrome", "chromium"], darwin: ["chrome", "brave", "helium", "arc"] };
function runtime() {
  const value = globalThis[slot];
  if (!value || value.owner?.role !== "manager" || !value.manifest.plugins.includes("pi-web")) reject("WEB_NOT_SELECTED", 5);
  return value;
}
export function webBrowserDeclared(name) {
  const value = runtime(); name ??= value.manifest.web_config?.agentcfgBrowserProfile;
  return typeof name === "string" && Object.hasOwn(value.manifest.web_browser_profiles ?? {}, name)
    && Boolean(supported[process.platform]?.includes(value.manifest.web_browser_profiles[name].browser));
}
export function registerWebCookieReader(reader) {
  const value = runtime();
  if (typeof reader !== "function") reject("WEB_BROWSER_READER_INVALID", 2);
  readers.set(value, reader);
}
export async function webBrowserCookieHeader(name, url, signal) {
  const value = runtime(); requireOrdinaryHelper(value, "pi-web", value.web.current().id ?? null); signal?.throwIfAborted();
  const reader = readers.get(value);
  if (!reader || !webBrowserDeclared(name)) reject("WEB_BROWSER_READER_UNAVAILABLE", 5);
  const result = await reader(name, url, signal);
  if (globalThis[slot] !== value) reject("WEB_BROWSER_STALE", 4);
  signal?.throwIfAborted();
  if (typeof result !== "string" || !result || Buffer.byteLength(result) > 16384 || /[\x00-\x1f\x7f]/.test(result)) reject("WEB_BROWSER_COOKIE_UNAVAILABLE", 3);
  return result;
}
export async function webBrowserSnapshot(options) {
  const value = runtime();
  const operation = value.web.current(); requireOrdinaryHelper(value, "pi-web", operation.id ?? null);
  const name = options.binding ?? value.manifest.web_config?.agentcfgBrowserProfile;
  const profile = value.manifest.web_browser_profiles?.[name];
  if (!profile || options.browser && options.browser !== profile.browser || options.profile && options.profile !== profile.profile
      || !Array.isArray(options.hosts) || options.hosts.some(host => !profile.allowed_hosts.includes(host))) reject("WEB_BROWSER_PROFILE_UNSELECTED", 4);
  if (!supported[process.platform]?.includes(profile.browser)) reject("WEB_BROWSER_PLATFORM_UNAVAILABLE", 5);
  const signal = AbortSignal.any([operation.controller.signal, ...(options.signal ? [options.signal] : [])]);
  signal.throwIfAborted();
  webCredential(profile.password_reference, signal);
  const response = await value.supervisor.call("ordinary_web_browser_prepare", { operation_id: randomUUID(), profile_id: name, hosts: options.hosts });
  let released = false;
  const release = async () => {
    if (released) return;
    const result = await value.supervisor.call("ordinary_web_browser_finish", { snapshot_id: response.snapshot_id });
    if (result.released !== true) reject("WEB_BROWSER_RELEASE_UNKNOWN", 4);
    released = true;
  };
  try {
    closed(response, ["snapshot_id", "directory", "profile", "browser", "sidecars"]);
    const root = join(dirname(dirname(dirname(value.supervisor.options.endpoint))), "credential-cache/web-browser");
    if (typeof response.snapshot_id !== "string" || !/^[a-f0-9]{64}$/.test(response.snapshot_id) || typeof response.directory !== "string" || !isAbsolute(response.directory) || resolve(response.directory) !== response.directory
        || dirname(response.directory) !== root || !/^[a-f0-9]{32}$/.test(basename(response.directory))
        || response.profile !== profile.profile || response.browser !== profile.browser || !Array.isArray(response.sidecars)
        || new Set(response.sidecars).size !== response.sidecars.length || response.sidecars.some(value => !["-wal", "-shm"].includes(value))) reject("WEB_BROWSER_SNAPSHOT_INVALID", 5);
    if (globalThis[slot] !== value) reject("WEB_BROWSER_STALE", 4);
    signal.throwIfAborted();
    return { ...response, release, password() {
      if (released || globalThis[slot] !== value) reject("WEB_BROWSER_STALE", 4);
      value.web.current(); signal.throwIfAborted(); return webCredential(profile.password_reference, signal);
    } };
  } catch (error) {
    if (/^[a-f0-9]{64}$/.test(response.snapshot_id)) await release();
    throw error;
  }
}
