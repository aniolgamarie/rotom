// Web 的原生配置只取当前实例投影；凭据只解析本插件声明的引用，不运行命令或借用环境别名。
import { isAbsolute, join } from "node:path";
import { lstatSync, mkdirSync, realpathSync } from "node:fs";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
function runtime() {
  const value = globalThis[slot];
  if (!value || value.owner?.role !== "manager" || !value.manifest.plugins.includes("pi-web")) reject("WEB_NOT_SELECTED", 5);
  return value;
}
export function webConfigurationIdentity() { return runtime(); }
export function assertWebOperation() {
  const value = runtime();
  if (!value.web?.current) reject("WEB_OPERATION_CLOSED", 4);
  value.web.current();
}
export function webCacheDirectory(create) {
  const value = runtime();
  let path = value.instanceRoot;
  if (typeof path !== "string" || !isAbsolute(path) || realpathSync(path) !== path) reject("WEB_CACHE_ROOT_INVALID", 4);
  for (const part of [null, "pi-home", "web", "web-search-cache"]) {
    if (part !== null) path = join(path, part);
    let info;
    try { info = lstatSync(path); }
    catch (error) {
      if (error.code !== "ENOENT") throw error;
      if (!create) return null;
      if (part === null) reject("WEB_CACHE_ROOT_INVALID", 4);
      mkdirSync(path, { mode: 0o700 }); info = lstatSync(path);
    }
    if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid?.() || (info.mode & 0o777) !== 0o700) reject("WEB_CACHE_OWNERSHIP", 4);
  }
  return path;
}
export function webConfigDirectory() {
  const value = runtime();
  if (typeof value.instanceRoot !== "string" || !isAbsolute(value.instanceRoot)) reject("WEB_CONFIG_UNBOUND", 2);
  return join(value.instanceRoot, "pi-home", "web");
}
export function webConfig() {
  const value = runtime().manifest.web_config;
  if (!value || typeof value !== "object" || Array.isArray(value)) reject("WEB_CONFIG_UNBOUND", 2);
  return structuredClone(value);
}
function variable(reference) {
  if (typeof reference !== "string") reject("WEB_CREDENTIAL_UNDECLARED", 2);
  const match = /^\$(?:\{(AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16})\}|(AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}))$/.exec(reference);
  const name = match?.[1] ?? match?.[2];
  if (!name || !runtime().manifest.web_credential_variables?.includes(name)) reject("WEB_CREDENTIAL_UNDECLARED", 2);
  return name;
}
export function webCredentialDeclared(reference) {
  if (reference === undefined || reference === null || reference === "") return false;
  variable(reference); return true;
}
function credential(reference, signal, document) {
  signal?.throwIfAborted();
  const owner = runtime();
  requireOrdinaryHelper(owner, "pi-web", owner.web?.scope?.getStore()?.id ?? null);
  const name = variable(reference), value = process.env[name];
  if (!value) reject("WEB_CREDENTIAL_MISSING", 3);
  if (Buffer.byteLength(value) > (document ? 65536 : 16384) || (document ? /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/ : /[\x00-\x1f\x7f]/).test(value)) reject("WEB_CREDENTIAL_INVALID", 3);
  // ! 与 $ 都是秘密正文，不做第二次解释或展开。
  return value;
}

export function webCredential(reference, signal) { return credential(reference, signal, false); }
export function webCredentialDocument(reference, signal) { return credential(reference, signal, true); }
