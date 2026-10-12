// 纯 bootstrap 数据测试；无真实 token/source/角色 IO 或 SDK。
import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { inspect } from "node:util";
import { captureInitializerBootstrap as capture, encodeInitializerBootstrapFrame as encode,
  decodeInitializerBootstrapFrame as decode } from "../initializer-bootstrap.ts";

const fixture = JSON.parse(fs.readFileSync(new URL("../../../../tests/fixtures/pi/initializer-bootstrap-v1.json", import.meta.url), "utf8"));
const token = fixture.input.role_token, golden = Buffer.from(fixture.frame_hex, "hex");
const code = "PI_INITIALIZER_BOOTSTRAP_INVALID", secret = "SYNTHETIC_FOREIGN_BOOTSTRAP_EXCEPTION";
const names = Object.keys(fixture.input), maximum = Number.MAX_SAFE_INTEGER;
const value = () => ({ ...fixture.input });
function frame(payload) {
  if (typeof payload === "string") payload = Buffer.from(payload, "utf8");
  const header = Buffer.alloc(4); header.writeUInt32BE(payload.length);
  return Buffer.concat([header, payload]);
}
function reject(action) {
  assert.throws(action, error => {
    assert.equal(error.message, code); assert.equal(error.code, code); assert.equal(error.exitCode, 4);
    assert.equal(Object.hasOwn(error, "cause"), false);
    assert(!String(error.stack).includes(secret)); assert(!String(error.stack).includes(token));
    return true;
  });
}

test("independent golden canonical bytes and cross-language frame roundtrip", () => {
  const dto = capture(value()), encoded = encode(dto);
  assert(encoded.equals(golden), "synthetic golden mismatch");
  assert.equal(encoded.length, 746); assert.equal(encoded.length - 4, 742);
  assert(encode(decode(golden)).equals(golden), "roundtrip mismatch");
  assert(encode(decode(new Uint8Array(golden))).equals(golden));
});
for (const generation of [0, 1, maximum]) test("safe integer generation " + generation, () => {
  const data = value(); data.grant_generation = generation;
  const encoded = encode(capture(data));
  assert.equal(encoded.length - 4, generation === maximum ? 757 : 742);
  assert(encode(decode(encoded)).equals(encoded));
});
test("capture is immutable opaque data; inspect/JSON/string do not contain token", () => {
  const data = value(), dto = capture(data);
  data.role_token = "a".repeat(64); data.grant_generation = 7;
  assert(encode(dto).equals(golden), "capture aliases input");
  assert(Object.isFrozen(dto)); assert.deepEqual(Object.keys(dto), []);
  for (const output of [JSON.stringify(dto), inspect(dto), String(dto)]) assert(!output.includes(token));
  assert(encode(dto).includes(Buffer.from(token)), "explicit encoded frame retains private data");
  for (const name of ["role_token", "fd", "fileno", "launch", "authority"]) assert.equal(Object.hasOwn(dto, name), false);
});
test("null prototype plain data is accepted", () => {
  assert(encode(capture(Object.assign(Object.create(null), value()))).equals(golden));
});
for (const name of names) test("closed field " + name, () => {
  const missing = value(); delete missing[name]; reject(() => capture(missing));
  const extra = value(); extra.extra = "unused"; reject(() => capture(extra));
  for (const bad of [null, true, [], {}, new String("a")]) {
    const data = value(); data[name] = bad; reject(() => capture(data));
  }
});
for (const name of names.filter(name => !["schema_version", "role", "grant_generation"].includes(name))) test("exact lowercase hex field " + name, () => {
  const width = value()[name].length;
  for (const bad of ["A".repeat(width), "a".repeat(width - 1), "a".repeat(width + 1), "a".repeat(width - 1) + "\n", "é".repeat(width), "\ud800".repeat(width)]) {
    const data = value(); data[name] = bad; reject(() => capture(data));
  }
});
test("literal schema/role and nonnegative exact safe integer range", () => {
  for (const [name, bad] of [["schema_version", 0], ["schema_version", 2], ["role", "initializer"],
    ["grant_generation", -1], ["grant_generation", maximum + 1], ["grant_generation", 0.5],
    ["grant_generation", -0], ["grant_generation", NaN], ["grant_generation", Infinity], ["grant_generation", 0n]]) {
    const data = value(); data[name] = bad; reject(() => capture(data));
  }
});
test("proxy/getters/symbol/foreign prototype reject without foreign execution", () => {
  let touched = 0;
  const proxy = new Proxy(value(), { ownKeys() { touched++; throw new Error(secret); }, getPrototypeOf() { touched++; throw new Error(secret); } });
  const getter = value(); Object.defineProperty(getter, "role_token", { get() { touched++; throw new Error(secret); }, enumerable: true });
  const symbol = value(); symbol[Symbol("foreign")] = "x";
  const foreign = value(); Object.setPrototypeOf(foreign, {});
  for (const data of [proxy, getter, symbol, foreign, [], null]) reject(() => capture(data));
  assert.equal(touched, 0);
});
test("opaque aliases/proxies/structured copies are never registered codec objects", () => {
  const dto = capture(value());
  for (const candidate of [{ ...dto }, structuredClone(dto), Object.create(Object.getPrototypeOf(dto)), new Proxy(dto, {}), value(), null]) reject(() => encode(candidate));
});
test("single frame caps, truncation and trailing frames", () => {
  for (const raw of [Buffer.alloc(0), Buffer.alloc(1), Buffer.alloc(3), Buffer.alloc(4),
    Buffer.from([0, 0, 8, 1]), Buffer.from([255, 255, 255, 255]), frame("x".repeat(2048)), frame("x".repeat(2049)),
    Buffer.concat([golden, Buffer.from([0])]), Buffer.concat([golden, golden]), golden.subarray(0, -1)]) reject(() => decode(raw));
  const mismatch = frame("x".repeat(2048)); mismatch.writeUInt32BE(2047); reject(() => decode(mismatch));
});
for (const [name, mutate] of [
  ["leading", raw => " " + raw], ["trailing", raw => raw + "\n"], ["spacing", raw => raw.replace(",", ", ")],
  ["float", raw => raw.replace('"grant_generation":0', '"grant_generation":0.0')],
  ["exponent", raw => raw.replace('"grant_generation":0', '"grant_generation":0e0')],
  ["negative-zero", raw => raw.replace('"grant_generation":0', '"grant_generation":-0')],
  ["leading-zero", raw => raw.replace('"grant_generation":0', '"grant_generation":00')],
  ["nonfinite", raw => raw.replace('"grant_generation":0', '"grant_generation":NaN')],
  ["duplicate", raw => raw.replace('"schema_version":1', '"schema_version":1,"schema_version":1')],
  ["escape", raw => raw.replace('"role":"durable-initializer"', '"role":"durable-\\u0069nitializer"')],
  ["unknown", raw => raw.slice(0, -1) + ',"extra":0}'], ["order", raw => JSON.stringify(value())],
  ["array", raw => "[]"], ["nested", raw => '{"role":{}}'], ["null", raw => "null"],
]) test("noncanonical wire " + name, () => reject(() => decode(frame(mutate(fixture.canonical_payload)))));
test("BOM/UTF8/nonASCII/surrogate wire rejected", () => {
  for (const raw of [Buffer.concat([Buffer.from([239, 187, 191]), golden.subarray(4)]), Buffer.from([255]), Buffer.from('{"role":"é"}'), Buffer.from('{"role":"\\ud800"}')]) reject(() => decode(frame(raw)));
});
test("proxy/shared/subclass/detached/resizable/metadata-getter views reject", () => {
  let touched = 0;
  const proxy = new Proxy(golden, { get() { touched++; throw new Error(secret); } });
  const shared = new Uint8Array(new SharedArrayBuffer(golden.length)); shared.set(golden);
  class ForeignBytes extends Uint8Array {}
  const getter = new Uint8Array(golden); Object.defineProperty(getter, "byteLength", { get() { touched++; throw new Error(secret); } });
  const backing = new ArrayBuffer(golden.length); const detached = new Uint8Array(backing); detached.set(golden); structuredClone(backing, { transfer: [backing] });
  const resizable = new Uint8Array(new ArrayBuffer(golden.length, { maxByteLength: 2052 })); resizable.set(golden);
  for (const raw of [proxy, shared, new ForeignBytes(golden), getter, detached, resizable, new DataView(new ArrayBuffer(8)), golden.toString("hex"), null]) reject(() => decode(raw));
  assert.equal(touched, 0);
});
test("all three functions reject bad argument counts with fixed error", () => {
  for (const action of [capture, encode, decode]) {
    reject(() => action()); reject(() => action(value(), secret));
  }
});
test("nonenumerable own data property is rejected", () => {
  const data = value(); Object.defineProperty(data, "role_token", { value: token, enumerable: false });
  reject(() => capture(data));
});
