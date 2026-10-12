// 仅闭合 owner 元数据；没有 fd/锁/进程或 SDK 操作。
import { types } from "node:util";

const apply = Reflect.apply, objectPrototype = Object.prototype, isUint8Array = types.isUint8Array;
const Bytes = Uint8Array, bytesPrototype = Uint8Array.prototype, bufferPrototype = Buffer.prototype;
const typed = Object.getPrototypeOf(bytesPrototype);
const lengthGetter = Object.getOwnPropertyDescriptor(typed, "byteLength").get;
const offsetGetter = Object.getOwnPropertyDescriptor(typed, "byteOffset").get;
const bufferGetter = Object.getOwnPropertyDescriptor(typed, "buffer").get;
const arrayLengthGetter = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, "byteLength").get;
const setBytes = typed.set;
const Encoder = TextEncoder, Decoder = TextDecoder, encodeText = TextEncoder.prototype.encode, decodeText = TextDecoder.prototype.decode;
const CODE = "PI_DURABLE_OWNER_MESSAGE_INVALID", U64 = "18446744073709551615";
const PROCESS = ["platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid"];
const RECORD = ["schema", "deployment_identity", "storage_identity", "epoch", "controller", "writer", "stage"];
const KINDS = ["hello", "bind", "bound", "close", "closed"];
function fail() { throw new Error(CODE); }
function integer(value, maximum = Number.MAX_SAFE_INTEGER, minimum = 0) {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0) || value < minimum || value > maximum) fail();
  return value;
}
function string(value) {
  if (typeof value !== "string") fail();
  let count = 0;
  for (let index = 0; index < value.length; index++) {
    const point = value.charCodeAt(index);
    if (point >= 0xd800 && point <= 0xdbff) {
      const next = value.charCodeAt(++index); if (!(next >= 0xdc00 && next <= 0xdfff)) fail();
    } else if (point >= 0xdc00 && point <= 0xdfff) fail();
    if (++count > 128) fail();
  }
  return value;
}
function copy(value, depth = 1, budget = { nodes: 0 }, ancestors = new Set()) {
  if (depth > 4 || ++budget.nodes > 64) fail();
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "string") return string(value);
  if (typeof value === "number") return integer(value);
  if (!value || typeof value !== "object" || types.isProxy(value) || ancestors.has(value)) fail();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== objectPrototype && prototype !== null) fail();
  const keys = Reflect.ownKeys(value); if (keys.length > 64) fail();
  const result = Object.create(null); ancestors.add(value);
  for (const key of keys) {
    string(key); const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) fail();
    result[key] = copy(descriptor.value, depth + 1, budget, ancestors);
  }
  ancestors.delete(value); return result;
}
function shape(value, names) {
  if (value === null || typeof value !== "object") fail();
  const keys = Object.keys(value);
  if (keys.length !== names.length || keys.some(key => !names.includes(key))) fail();
  return value;
}
function match(pattern, value) {
  string(value); const found = pattern.exec(value); if (!found || found[0] !== value) fail(); return found;
}
function decimal(value, positive = false) {
  match(/^(0|[1-9][0-9]*)$/, value);
  if (value.length > U64.length || value.length === U64.length && value > U64 || positive && value === "0") fail();
  return value;
}
function storage(value) { shape(value, ["device", "inode"]); decimal(value.device); decimal(value.inode, true); }
function processIdentity(value) {
  shape(value, PROCESS); if (value.platform !== "linux") fail();
  match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/, value.boot_id);
  integer(value.pid, 2 ** 31 - 1, 1); integer(value.ppid, 2 ** 31 - 1); integer(value.pgid, 2 ** 31 - 1, 1); integer(value.uid, 2 ** 32 - 2);
  decimal(value.start_time); const namespace = match(/^pid:\[([1-9][0-9]*)\]$/, value.namespace); decimal(namespace[1], true);
}
function record(value, kind) {
  shape(value, RECORD); if (value.schema !== 1) fail();
  match(/^[0-9a-f]{64}$/, value.deployment_identity); match(/^[0-9a-f]{64}$/, value.epoch); storage(value.storage_identity);
  processIdentity(value.controller); processIdentity(value.writer);
  if (value.controller.pid === value.writer.pid || value.controller.boot_id !== value.writer.boot_id || value.controller.uid !== value.writer.uid) fail();
  if (value.stage !== (kind === "bind" || kind === "bound" ? "bound" : "closing")) fail();
}
function freeze(value) { if (value && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); } return value; }
export function captureOwnerMessage(value) {
  try {
    const result = copy(value); if (!result || !KINDS.includes(result.type)) fail();
    const kind = result.type, flag = kind === "closed" ? "descriptor_closed" : "close_on_exec", body = kind === "hello" ? "writer" : "record";
    shape(result, ["schema", "type", body, "lock_identity", "fd", flag]);
    if (result.schema !== 1 || result.fd !== 3 || result[flag] !== true) fail();
    storage(result.lock_identity); if (kind === "hello") processIdentity(result.writer); else record(result.record, kind);
    return freeze(result);
  } catch { fail(); }
}
function parse(raw) {
  let index = 0, nodes = 0;
  function space() { while (index < raw.length && /[ \t\r\n]/.test(raw[index])) index++; }
  function quoted() {
    const start = index++; let escaped = false;
    while (index < raw.length) {
      const char = raw[index++];
      if (!escaped && char === '"') return string(JSON.parse(raw.slice(start, index)));
      if (!escaped && char === "\\") escaped = true; else escaped = false;
    }
    fail();
  }
  function value(depth) {
    if (depth > 4 || ++nodes > 64) fail(); space(); const char = raw[index];
    if (char === '"') return quoted();
    if (char === "{") {
      index++; space(); const result = Object.create(null);
      if (raw[index] === "}") { index++; return result; }
      for (;;) {
        space(); if (raw[index] !== '"') fail(); const key = quoted(); if (Object.hasOwn(result, key)) fail();
        space(); if (raw[index++] !== ":") fail(); result[key] = value(depth + 1); space();
        const end = raw[index++]; if (end === "}") return result; if (end !== ",") fail();
      }
    }
    for (const [token, parsed] of [["true", true], ["false", false], ["null", null]]) {
      if (raw.startsWith(token, index)) { index += token.length; return parsed; }
    }
    const token = /^(?:0|[1-9][0-9]*)/.exec(raw.slice(index)); if (!token) fail();
    index += token[0].length; return integer(Number(token[0]));
  }
  const result = value(1); space(); if (index !== raw.length) fail(); return result;
}
function bytes(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)) fail();
  const prototype = Object.getPrototypeOf(value); if (prototype !== bytesPrototype && prototype !== bufferPrototype || !apply(isUint8Array, types, [value])) fail();
  const size = apply(lengthGetter, value, []), offset = apply(offsetGetter, value, []), buffer = apply(bufferGetter, value, []);
  const capacity = apply(arrayLengthGetter, buffer, []);
  if (!Number.isSafeInteger(size) || size < 5 || size > 4100 || offset + size > capacity) fail();
  const result = new Bytes(size); apply(setBytes, result, [value]); return result;
}
export function decodeOwnerMessageFrame(value) {
  try {
    const frame = bytes(value), size = frame[0] * 16777216 + frame[1] * 65536 + frame[2] * 256 + frame[3];
    if (size < 1 || size > 4096 || frame.length !== size + 4) fail();
    // 手工复制自有快照的 payload，不调用 caller 的 slice/species。
    const payload = new Bytes(size); for (let index = 0; index < size; index++) payload[index] = frame[index + 4];
    const text = apply(decodeText, new Decoder("utf-8", { fatal: true, ignoreBOM: true }), [payload]);
    return captureOwnerMessage(parse(text));
  } catch { fail(); }
}
function canonical(value) {
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
export function encodeOwnerMessageFrame(value) {
  try {
    const captured = captureOwnerMessage(value), payload = apply(encodeText, new Encoder(), [canonical(captured)]), size = payload.length;
    if (size < 1 || size > 4096) fail(); const frame = new Bytes(size + 4);
    frame[0] = Math.floor(size / 16777216); frame[1] = Math.floor(size / 65536) % 256; frame[2] = Math.floor(size / 256) % 256; frame[3] = size % 256;
    apply(setBytes, frame, [payload, 4]); return frame;
  } catch { fail(); }
}
