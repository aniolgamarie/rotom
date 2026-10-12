// 纯 bootstrap 数据 codec；opaque object/frame 不是角色或 IO authority。
import { inspect, types } from "node:util";

const CODE = "PI_INITIALIZER_BOOTSTRAP_INVALID", CAP = 2048;
const NAMES = ["schema_version", "role", "instance_id", "supervisor_activation_id",
  "manager_activation_id", "host_lease_id", "grant_generation", "runtime_identity",
  "lock_identity", "slice_identity", "adapter_identity", "role_token"];
const SHORT = ["supervisor_activation_id", "manager_activation_id", "host_lease_id"];
const objectPrototype = Object.prototype, bytesPrototype = Uint8Array.prototype, bufferPrototype = Buffer.prototype;
const typed = Object.getPrototypeOf(bytesPrototype), apply = Reflect.apply;
const byteLength = Object.getOwnPropertyDescriptor(typed, "byteLength").get;
const byteOffset = Object.getOwnPropertyDescriptor(typed, "byteOffset").get;
const backingBuffer = Object.getOwnPropertyDescriptor(typed, "buffer").get;
const capacity = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, "byteLength").get;
const resizable = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, "resizable").get;
const setBytes = typed.set;
const records = new WeakMap();
const opaquePrototype = Object.freeze({
  toString() { return "InitializerBootstrap(<redacted>)"; },
  [inspect.custom]() { return "InitializerBootstrap(<redacted>)"; },
});

function invalid() { throw new Error(CODE); }
function reject() {
  const error = new Error(CODE);
  Object.defineProperties(error, { code: { value: CODE, enumerable: true }, exitCode: { value: 4, enumerable: true } });
  throw error;
}
function boundary(action) { try { return action(); } catch { reject(); } }
function validate(value) {
  if (value === null || typeof value !== "object" || types.isProxy(value)) invalid();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== objectPrototype && prototype !== null) invalid();
  const keys = Reflect.ownKeys(value);
  if (keys.length !== NAMES.length || keys.some(key => typeof key !== "string" || !NAMES.includes(key))) invalid();
  const data = Object.create(null);
  for (const name of NAMES) {
    const descriptor = Object.getOwnPropertyDescriptor(value, name);
    if (!descriptor || !descriptor.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
    data[name] = descriptor.value;
  }
  if (data.schema_version !== 1 || typeof data.schema_version !== "number" || data.role !== "durable-initializer") invalid();
  if (!Number.isSafeInteger(data.grant_generation) || data.grant_generation < 0 || Object.is(data.grant_generation, -0)) invalid();
  for (const name of NAMES) {
    if (["schema_version", "role", "grant_generation"].includes(name)) continue;
    const text = data[name], width = SHORT.includes(name) ? 32 : 64;
    if (typeof text !== "string" || text.length !== width || !/^[0-9a-f]+$/.test(text)) invalid();
  }
  return Object.freeze(data);
}
function payload(data) {
  return Buffer.from("{" + [...NAMES].sort().map(name => JSON.stringify(name) + ":" + JSON.stringify(data[name])).join(",") + "}", "ascii");
}
function capture(data) {
  const result = Object.freeze(Object.create(opaquePrototype));
  records.set(result, data);
  return result;
}
function originalFrame(value) {
  if (value === null || typeof value !== "object" || types.isProxy(value) || !types.isUint8Array(value)) invalid();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== bytesPrototype && prototype !== bufferPrototype) invalid();
  for (const name of ["byteLength", "byteOffset", "buffer", "length"]) {
    if (Object.getOwnPropertyDescriptor(value, name)) invalid();
  }
  const size = apply(byteLength, value, []);
  if (!Number.isSafeInteger(size) || size < 4 || size > CAP + 4) invalid();
  const offset = apply(byteOffset, value, []), buffer = apply(backingBuffer, value, []);
  if (types.isSharedArrayBuffer(buffer) || apply(resizable, buffer, []) || offset + size > apply(capacity, buffer, [])) invalid();
  const declared = value[0] * 16777216 + value[1] * 65536 + value[2] * 256 + value[3];
  if (declared < 1 || declared > CAP || size !== declared + 4) invalid();
  // cap 与完整 frame 已核，再用原 typed-array set 复制，忽略 foreign 方法。
  const copy = Buffer.alloc(size);
  apply(setBytes, copy, [value]);
  return copy;
}

export function captureInitializerBootstrap(...args) {
  return boundary(() => {
    if (args.length !== 1) invalid();
    return capture(validate(args[0]));
  });
}
export function encodeInitializerBootstrapFrame(...args) {
  return boundary(() => {
    if (args.length !== 1 || args[0] === null || typeof args[0] !== "object" || types.isProxy(args[0])) invalid();
    const data = records.get(args[0]);
    if (!data) invalid();
    const bytes = payload(validate(data));
    if (bytes.length < 1 || bytes.length > CAP) invalid();
    const header = Buffer.alloc(4); header.writeUInt32BE(bytes.length);
    return Buffer.concat([header, bytes]);
  });
}
export function decodeInitializerBootstrapFrame(...args) {
  return boundary(() => {
    if (args.length !== 1) invalid();
    const bytes = originalFrame(args[0]), raw = bytes.subarray(4);
    for (const byte of raw) if (byte > 127) invalid();
    const data = validate(JSON.parse(raw.toString("ascii")));
    if (!raw.equals(payload(data))) invalid();
    return capture(data);
  });
}
