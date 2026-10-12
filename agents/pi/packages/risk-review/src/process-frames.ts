// 私密FD上的有界字节framing；不解析JSON，不认证来源，也不授予许可。
import { types } from "node:util";
const code = "PI_RISK_REVIEW_FRAME_INVALID";
const typedArray = Object.getPrototypeOf(Uint8Array.prototype);
const byteLength = Object.getOwnPropertyDescriptor(typedArray, "byteLength").get;
function fail() { const error = new Error(code); error.code = code; throw error; }
function options(value, keys) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) fail();
  const names = Reflect.ownKeys(value);
  if (names.length !== keys.length || names.some(key => typeof key !== "string" || !keys.includes(key))) fail();
  const captured = {};
  for (const key of keys) {
    const field = Object.getOwnPropertyDescriptor(value, key);
    if (!field?.enumerable || !Object.hasOwn(field, "value")) fail();
    captured[key] = field.value;
  }
  return captured;
}
function limit(value, maximum) { if (!Number.isSafeInteger(value) || value < 1 || value > maximum) fail(); return value; }
function validText(text, maximum) {
  if (typeof text !== "string" || text.length === 0 || text.length > maximum) fail();
  for (let index = 0; index < text.length; index++) {
    const point = text.charCodeAt(index);
    if (point >= 0xd800 && point <= 0xdbff) {
      const next = text.charCodeAt(++index);
      if (!(next >= 0xdc00 && next <= 0xdfff)) fail();
    } else if (point >= 0xdc00 && point <= 0xdfff) fail();
  }
}
export function encodeReviewFrame(text, configuration) {
  try {
    const { maxFrameBytes } = options(configuration, ["maxFrameBytes"]);
    limit(maxFrameBytes, 524288); validText(text, maxFrameBytes);
    const payload = new TextEncoder().encode(text);
    if (payload.length > maxFrameBytes) fail();
    const result = new Uint8Array(payload.length + 4), size = payload.length;
    result[0] = Math.floor(size / 16777216); result[1] = Math.floor(size / 65536) % 256;
    result[2] = Math.floor(size / 256) % 256; result[3] = size % 256;
    result.set(payload, 4);
    return result;
  } catch { fail(); }
}
export function createReviewFrameReader(configuration) {
  const limits = options(configuration, ["maxFrameBytes", "maxFrames", "maxTotalBytes"]);
  const maximum = limit(limits.maxFrameBytes, 524288), frameLimit = limit(limits.maxFrames, 1000000), totalLimit = limit(limits.maxTotalBytes, 8388608);
  const header = new Uint8Array(4);
  let headerBytes = 0, payload = null, payloadBytes = 0;
  let frames = 0, bytes = 0, failed = false, finished = false;
  const snapshot = () => Object.freeze({ frames, bytes, buffered_bytes: headerBytes + payloadBytes, failed, finished });
  function failure() {
    failed = true;
    // 失败后丢掉私密内容，只保留计数；后续操作不能恢复为成功。
    header.fill(0); payload = null;
    fail();
  }
  function push(chunk) {
    if (failed || finished) return failure();
    try {
      if (!chunk || types.isProxy(chunk)) failure();
      const prototype = Object.getPrototypeOf(chunk);
      if (prototype !== Uint8Array.prototype && prototype !== Buffer.prototype) failure();
      // intrinsic getter与数字索引不调用caller方法、getter或Symbol.species。
      const size = byteLength.call(chunk), previousBytes = bytes;
      bytes += size;
      if (bytes > totalLimit) failure();
      const result = []; let offset = 0;
      while (offset < size) {
        if (payload === null) {
          while (headerBytes < 4 && offset < size) header[headerBytes++] = chunk[offset++];
          if (headerBytes < 4) break;
          const length = header[0] * 16777216 + header[1] * 65536 + header[2] * 256 + header[3];
          // budget按此header的流位置计算，不能因当前chunk还含payload而重复扣减。
          if (length === 0 || length > maximum || frames >= frameLimit || length > totalLimit - (previousBytes + offset)) failure();
          payload = new Uint8Array(length);
        }
        const count = Math.min(payload.length - payloadBytes, size - offset);
        for (let index = 0; index < count; index++) payload[payloadBytes + index] = chunk[offset + index];
        payloadBytes += count; offset += count;
        if (payloadBytes === payload.length) {
          // ignoreBOM保留原文本里的U+FEFF，fatal拒绝替换字符式容错。
          result.push(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(payload));
          frames++; payload = null; payloadBytes = 0; headerBytes = 0;
        }
      }
      return result;
    } catch { return failure(); }
  }
  function end() {
    if (failed) fail();
    if (finished) return snapshot();
    if (headerBytes !== 0 || payload !== null) return failure();
    finished = true;
    return snapshot();
  }
  return Object.freeze({ push, end, snapshot });
}
