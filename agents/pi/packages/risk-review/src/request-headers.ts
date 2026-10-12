// 显式可信平台输入的私密header基线；不读ambient环境或反向采信SDK请求。
import { types } from "node:util";
const code = "PI_RISK_REVIEW_HEADERS_INVALID";
const keys = ["apiKey", "timeoutMs", "platform", "arch", "release", "runtimeVersion", "sdkVersion"];
function fail() { const error = new Error(code); error.code = code; throw error; }
export function createReviewHeaders(options) {
  if (!options || typeof options !== "object" || types.isProxy(options) || Object.getPrototypeOf(options) !== Object.prototype) fail();
  const names = Reflect.ownKeys(options);
  if (names.length !== keys.length || names.some(key => typeof key !== "string" || !keys.includes(key))) fail();
  const captured = {};
  for (const key of keys) {
    const property = Object.getOwnPropertyDescriptor(options, key);
    if (!property?.enumerable || !Object.hasOwn(property, "value")) fail();
    captured[key] = property.value;
  }
  const { apiKey, timeoutMs, platform, arch, release, runtimeVersion, sdkVersion } = captured;
  // Bearer凭据不能含空白/控制或非ASCII；错误不保留key、正文或cause。
  if (typeof apiKey !== "string" || apiKey.length < 1 || apiKey.length > 8192 || /[\x00-\x20\x7f-\uffff]/.test(apiKey)
    || typeof release !== "string" || release.length < 1 || release.length > 256 || /[\x00-\x1f\x7f-\uffff]/.test(release)
    || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 300000
    || platform !== "linux" || arch !== "x64" || runtimeVersion !== "v24.14.0" || sdkVersion !== "7.19.0") fail();
  // 固定Pi UA不含包版本；SDK timeout按毫秒截断为秒，短于1秒仍为合法0。
  return Object.freeze({
    authorization: "Bearer " + apiKey,
    accept: "application/json",
    "content-type": "application/json",
    "user-agent": "pi (linux " + release + "; x64)",
    "x-stainless-lang": "js",
    "x-stainless-package-version": "7.19.0",
    "x-stainless-os": "Linux",
    "x-stainless-arch": "x64",
    "x-stainless-runtime": "node",
    "x-stainless-runtime-version": "v24.14.0",
    "x-stainless-retry-count": "0",
    "x-stainless-timeout": String(Math.trunc(timeoutMs / 1000)),
  });
}
