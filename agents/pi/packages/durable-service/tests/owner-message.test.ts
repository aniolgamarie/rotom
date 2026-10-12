import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { captureOwnerMessage, decodeOwnerMessageFrame, encodeOwnerMessageFrame } from "../src/owner-message.ts";

const vectors = JSON.parse(readFileSync(new URL("../../../../../tests/fixtures/pi/durable-owner-message-codec/vectors.json", import.meta.url), "utf8")).vectors;
const CODE = "PI_DURABLE_OWNER_MESSAGE_INVALID", SECRET = "SYNTHETIC_OWNER_MESSAGE_SECRET";
const raw = (kind = "bind") => structuredClone(vectors.find(value => value.name === kind + "_minimal").value);
function invalid(call) {
  assert.throws(call, error => { assert.equal(error.constructor, Error); assert.equal(error.message, CODE); assert.equal(Object.hasOwn(error, "cause"), false); assert.ok(!error.stack.includes(SECRET)); assert.equal(Object.hasOwn(error, "doc"), false); return true; });
}
function frame(text) {
  const payload = typeof text === "string" ? new TextEncoder().encode(text) : text;
  const result = new Uint8Array(payload.length + 4); const n = payload.length;
  result[0] = Math.floor(n / 16777216); result[1] = Math.floor(n / 65536) % 256; result[2] = Math.floor(n / 256) % 256; result[3] = n % 256; result.set(payload, 4); return result;
}
const hex = value => Buffer.from(value).toString("hex");
for (const vector of vectors) test(`shared full golden ${vector.name}`, () => {
  const source = structuredClone(vector.value), result = captureOwnerMessage(source);
  assert.equal(hex(encodeOwnerMessageFrame(result)), vector.hex);
  assert.deepEqual(decodeOwnerMessageFrame(Buffer.from(vector.hex, "hex")), result);
  assert.ok(Object.isFrozen(result)); assert.ok(Object.isFrozen(result.lock_identity)); assert.equal(Object.isFrozen(source), false);
  assert.equal(Object.hasOwn(result, "writer_lock_verified"), false); assert.equal(Object.hasOwn(result, "database_allowed"), false);
  if (result.record) { assert.ok(Object.isFrozen(result.record.writer)); assert.notEqual(result.record.storage_identity.inode, result.lock_identity.inode); }
  if (vector.name.endsWith("u64_max")) assert.equal(result.lock_identity.device, "18446744073709551615");
});

test("source graphs remain mutable and independent; plain/null prototypes and key order", () => {
  const source = raw(), result = captureOwnerMessage(source), original = hex(encodeOwnerMessageFrame(result));
  source.record.controller.pid = 99; source.lock_identity.inode = "99";
  assert.equal(hex(encodeOwnerMessageFrame(result)), original); assert.equal(Object.isFrozen(source.record), false);
  const nullproto = Object.assign(Object.create(null), raw()); assert.equal(hex(encodeOwnerMessageFrame(nullproto)), original);
  const reversed = Object.fromEntries(Object.entries(raw()).reverse()); assert.equal(hex(encodeOwnerMessageFrame(reversed)), original);
  assert.equal(hex(encodeOwnerMessageFrame(decodeOwnerMessageFrame(frame(" \n\t" + JSON.stringify(raw(), null, 1) + "\r\n ")))), original);
});
for (const kind of ["hello", "bind", "bound", "close", "closed"]) test(`${kind} exact root/stage/flags`, () => {
  const source = raw(kind);
  for (const key of Object.keys(source)) { const value = structuredClone(source); delete value[key]; invalid(() => captureOwnerMessage(value)); }
  for (const key of ["extra", "writer_lock_verified", "database_allowed", "can_take_over"]) invalid(() => captureOwnerMessage({ ...source, [key]: true }));
  for (const key of ["schema", "fd"]) invalid(() => captureOwnerMessage({ ...source, [key]: true }));
  invalid(() => captureOwnerMessage({ ...source, [kind === "closed" ? "descriptor_closed" : "close_on_exec"]: false }));
  if (kind !== "hello") for (const stage of ["acquired", "ready", "released", kind === "bind" || kind === "bound" ? "closing" : "bound"]) {
    const value = structuredClone(source); value.record.stage = stage; invalid(() => captureOwnerMessage(value));
  }
});
for (const bad of ["00", "01", "+1", "-1", "1.0", " 1", "1\n", "١", "18446744073709551616", 1, true]) test(`u64 canonical rejects ${String(bad)}`, () => {
  for (const field of ["lock_identity", "storage_identity"]) {
    const value = raw(), target = field === "lock_identity" ? value[field] : value.record[field]; target.device = bad; invalid(() => captureOwnerMessage(value));
  }
});
for (const token of ["1.0", "1e0", "-0", "-1", "NaN", "Infinity", "1e999", "9007199254740992"]) test(`wire numeric token ${token} rejects before normalization`, () => {
  invalid(() => decodeOwnerMessageFrame(frame(JSON.stringify(raw("hello")).replace('"schema":1', '"schema":' + token))));
});
for (const field of ["schema", "fd", "pid", "ppid", "pgid", "uid"]) test(`native -0 in ${field} cannot be encoded as zero`, () => {
  const value = raw("hello"); if (["schema", "fd"].includes(field)) value[field] = -0; else value.writer[field] = -0;
  invalid(() => captureOwnerMessage(value)); invalid(() => encodeOwnerMessageFrame(value));
});
for (const cut of ["root", "record", "process", "storage"]) test(`decoded duplicate ${cut}`, () => {
  let text = JSON.stringify(raw());
  if (cut === "root") text = text.replace('"fd":3', '"fd":2,"\\u0066d":3');
  if (cut === "record") text = text.replace('"stage":"bound"', '"stage":"ready","st\\u0061ge":"bound"');
  if (cut === "process") text = text.replace('"pid":10', '"pid":9,"\\u0070id":10');
  if (cut === "storage") text = text.replace('"inode":"1"', '"inode":"2","\\u0069node":"1"');
  invalid(() => decodeOwnerMessageFrame(frame(text)));
});
test("identity numeric/record relationship/unknown fields", () => {
  for (const [key, bad] of [["pid", 0], ["pid", 2 ** 31], ["uid", 2 ** 32 - 1], ["uid", true], ["ppid", -1], ["start_time", "18446744073709551616"], ["namespace", "pid:[0]"], ["boot_id", "bad"]]) {
    const value = raw(); value.record.writer[key] = bad; invalid(() => captureOwnerMessage(value));
  }
  for (const mode of ["same-pid", "uid", "boot", "missing", "extra-record", "extra-process"]) {
    const value = raw();
    if (mode === "same-pid") value.record.writer.pid = value.record.controller.pid;
    if (mode === "uid") value.record.writer.uid++;
    if (mode === "boot") value.record.writer.boot_id = "ffffffff-ffff-ffff-ffff-ffffffffffff";
    if (mode === "missing") value.record.writer = null;
    if (mode === "extra-record") value.record.extra = true;
    if (mode === "extra-process") value.record.writer.extra = true;
    invalid(() => captureOwnerMessage(value));
  }
});
test("resource/surrogate/array/cycle/native foreign values reject", () => {
  const cycle = {}; cycle.x = cycle;
  const deep = { x: { x: { x: { x: 0 } } } };
  for (const value of [{ x: [] }, { x: "\ud800" }, { x: "x".repeat(129) }, deep, Object.fromEntries(Array.from({ length: 65 }, (_, i) => [String(i), 0])), cycle, { x: 1n }, { x: undefined }, { x: Infinity }]) invalid(() => captureOwnerMessage(value));
  invalid(() => decodeOwnerMessageFrame(frame('{"x":"\\ud800"}')));
});
test("bad UTF8/BOM/UTF16, zero/overflow/truncated/multiple/extra frames", () => {
  const valid = Buffer.from(vectors[0].hex, "hex");
  for (const value of [new Uint8Array(), new Uint8Array(4), Uint8Array.of(0, 0, 16, 1), Uint8Array.of(0, 0, 0, 1), Buffer.concat([valid, valid]), Buffer.concat([valid, Buffer.of(1)]), frame(Buffer.of(255)), frame(Buffer.concat([Buffer.of(239,187,191), valid.subarray(4)])), frame(Buffer.of(254,255,0,123,0,125))]) invalid(() => decodeOwnerMessageFrame(value));
});
test("Proxy/getter/toJSON/subclass hooks never run", () => {
  let calls = 0; const target = raw();
  const proxy = new Proxy(target, { get() { calls++; throw Error(SECRET); }, getPrototypeOf() { calls++; throw Error(SECRET); }, ownKeys() { calls++; throw Error(SECRET); } });
  invalid(() => captureOwnerMessage(proxy)); invalid(() => encodeOwnerMessageFrame(proxy));
  const revoked = Proxy.revocable(target, {}); revoked.revoke(); invalid(() => captureOwnerMessage(revoked.proxy));
  const getter = raw(); Object.defineProperty(getter.record.writer, "pid", { enumerable: true, get() { calls++; throw Error(SECRET); } }); invalid(() => captureOwnerMessage(getter));
  const toJSON = raw(); Object.defineProperty(toJSON, "toJSON", { enumerable: true, get() { calls++; throw Error(SECRET); } }); invalid(() => encodeOwnerMessageFrame(toJSON));
  class Wrong { get schema() { calls++; throw Error(SECRET); } } invalid(() => captureOwnerMessage(new Wrong()));
  invalid(() => decodeOwnerMessageFrame(proxy)); invalid(() => decodeOwnerMessageFrame(revoked.proxy)); assert.equal(calls, 0);
});
test("exact binary brand/nonshared bytes and no own constructor/species/iterator access", () => {
  const valid = Buffer.from(vectors[0].hex, "hex"); let calls = 0;
  const bytes = new Uint8Array(valid); Object.defineProperty(bytes, "constructor", { get() { calls++; throw Error(SECRET); } });
  Object.defineProperty(bytes, Symbol.iterator, { get() { calls++; throw Error(SECRET); } }); Object.defineProperty(bytes, "byteLength", { get() { calls++; throw Error(SECRET); } });
  assert.equal(decodeOwnerMessageFrame(bytes).type, "hello"); assert.equal(calls, 0);
  class Wrong extends Uint8Array {} invalid(() => decodeOwnerMessageFrame(new Wrong(valid)));
  invalid(() => decodeOwnerMessageFrame(Object.create(Uint8Array.prototype)));
  const other = new Uint16Array(20); Object.setPrototypeOf(other, Uint8Array.prototype); invalid(() => decodeOwnerMessageFrame(other));
  const shared = new Uint8Array(new SharedArrayBuffer(valid.length)); shared.set(valid); invalid(() => decodeOwnerMessageFrame(shared));
  const detached = new Uint8Array(valid); structuredClone(detached.buffer, { transfer: [detached.buffer] }); invalid(() => decodeOwnerMessageFrame(detached));
  const source = new Uint8Array(valid), captured = decodeOwnerMessageFrame(source); source.fill(0); assert.equal(hex(encodeOwnerMessageFrame(captured)), vectors[0].hex);
});

test("inode zero rejected separately; different namespace grants no authority; offset Buffer snapshot", () => {
  for (const location of ["lock_identity", "storage_identity"]) {
    const value = raw(), target = location === "lock_identity" ? value[location] : value.record[location]; target.inode = "0";
    invalid(() => captureOwnerMessage(value));
  }
  const value = raw(); value.record.writer.namespace = "pid:[2]"; const result = captureOwnerMessage(value);
  assert.equal(result.record.writer.namespace, "pid:[2]"); assert.equal(Object.hasOwn(result, "database_allowed"), false);
  const bytes = Buffer.from(vectors[0].hex, "hex"), surrounding = Buffer.concat([Buffer.of(1,2,3), bytes, Buffer.of(4)]);
  assert.equal(decodeOwnerMessageFrame(surrounding.subarray(3, 3 + bytes.length)).type, "hello");
});
