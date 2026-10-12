import assert from "node:assert/strict";
import { test } from "node:test";
import { canonicalProbeJson } from "../scripts/pi-probe-json.mjs";

function nullCopy(value) {
  if (Array.isArray(value)) return value.map(nullCopy);
  if (value && typeof value === "object") { const result = Object.create(null); for (const [key, child] of Object.entries(value)) result[key] = nullCopy(child); return result; }
  return value;
}
const original = { schema: 1, rows: [{ request: { input: { text: "Synthetic complete value" }, budget: { maxCalls: 2, maxCostUnits: 30 } }, nativeTaskId: 4 }] };
test("old prototype-sensitive comparator rejects same complete persisted JSON values", () => {
  const cached = nullCopy(original), persisted = JSON.parse(JSON.stringify(original));
  assert.equal(JSON.stringify(cached), JSON.stringify(persisted));
  assert.equal(canonicalProbeJson(cached), canonicalProbeJson(persisted));
});

const fixed = error => { assert.equal(error.message, "probe-json-invalid"); assert.equal(error.code, "probe-json-invalid"); assert.equal(error.cause, undefined); return true; };
test("object key order and allowed nested prototype do not change full JSON meaning", () => {
  assert.equal(canonicalProbeJson({ z: [1, { b: true, a: "值" }], a: null }), canonicalProbeJson({ a: null, z: [1, nullCopy({ a: "值", b: true })] }));
  assert.equal(canonicalProbeJson(-0), canonicalProbeJson(0));
  assert.equal(canonicalProbeJson({ then: "data" }), '{"then":"data"}');
});
for (const [a, b] of [[true, 1], [1, "1"], [null, false], [[1, 2], [2, 1]], [{ a: 1 }, { a: 1, b: null }], [{ a: null }, {}], [{ a: { b: 1 } }, { a: { b: 2 } }]]) test("full keys, primitive types/values and array order remain unequal", () => {
  assert.notEqual(canonicalProbeJson(a), canonicalProbeJson(b));
});
test("literal Unicode, escapes and key characters roundtrip without value changes", () => {
  const value = { '"\\\u0000😀': "😀中文\n\t\r\b\f\u0000\"\\\u2028\u2029", "": [1e100, 1e-100, 0, true, null] };
  assert.deepEqual(JSON.parse(canonicalProbeJson(value)), value);
});
test("shared noncyclic aliases are legal duplicated JSON values without freezing/mutation", () => {
  const shared = { x: [1, 2] }, value = { a: shared, b: shared };
  assert.equal(canonicalProbeJson(value), '{"a":{"x":[1,2]},"b":{"x":[1,2]}}'); assert.equal(value.a, value.b); assert(!Object.isFrozen(value)); assert(!Object.isFrozen(shared));
});
test("Proxy including revoked is rejected before any trap or getter", () => {
  let traps = 0; const proxy = new Proxy({}, { getPrototypeOf() { traps++; throw Error("SYNTHETIC_PRIVATE"); }, ownKeys() { traps++; throw Error("SYNTHETIC_PRIVATE"); }, get() { traps++; throw Error("SYNTHETIC_PRIVATE"); } });
  assert.throws(() => canonicalProbeJson(proxy), fixed);
  const revoked = Proxy.revocable([], {}); revoked.revoke(); assert.throws(() => canonicalProbeJson(revoked.proxy), fixed); assert.equal(traps, 0);
});
test("accessor/toJSON/then hooks are refused with zero invocation and no raw error", () => {
  let reads = 0;
  const getter = { get a() { reads++; throw Error("SYNTHETIC_PRIVATE"); } }, toJSON = { toJSON() { reads++; return {}; } }, then = { get then() { reads++; throw Error("SYNTHETIC_PRIVATE"); } };
  for (const value of [getter, toJSON, then, { toJSON: "data" }]) assert.throws(() => canonicalProbeJson(value), fixed);
  assert.equal(reads, 0);
});
for (const value of [undefined, 1n, () => {}, Symbol("synthetic"), NaN, Infinity, -Infinity, new Date(0), new (class Data { constructor() { this.a = 1; } })(), new (class Values extends Array {})()]) test("nonJSON primitive, nonfinite number and subclass rejected", () => {
  assert.throws(() => canonicalProbeJson(value), fixed);
});
for (const value of ["\ud800", "\udfff", "a\ud800x", { "\ud800": true }]) test("invalid Unicode value/key is refused", () => {
  assert.throws(() => canonicalProbeJson(value), fixed);
});
test("sparse arrays, extra array data, symbols and nonenumerable data refused", () => {
  const sparse = [1, , 3], extra = [1]; extra.extra = true;
  const hidden = {}; Object.defineProperty(hidden, "a", { value: 1 });
  const symbol = { a: 1, [Symbol("extra")]: true };
  const accessor = [1]; Object.defineProperty(accessor, "0", { get() { assert.fail("array accessor executed"); }, enumerable: true });
  for (const value of [sparse, extra, hidden, symbol, accessor]) assert.throws(() => canonicalProbeJson(value), fixed);
});
test("object and array cycles rejected instead of lossy omission", () => {
  const object = {}; object.self = object; const array = []; array.push(array);
  for (const value of [object, array]) assert.throws(() => canonicalProbeJson(value), fixed);
});
test("depth boundary is 128 edges, no optional argument can loosen it", () => {
  let value = null; for (let i = 0; i < 128; i++) value = [value]; assert.equal(JSON.parse(canonicalProbeJson(value)).length, 1);
  assert.throws(() => canonicalProbeJson([value], { maximumDepth: 1000 }), fixed);
});
test("65536 total value nodes cap includes containers and repeated shared values", () => {
  const value = new Array(65535).fill(0); assert.equal(JSON.parse(canonicalProbeJson(value)).length, 65535);
  assert.throws(() => canonicalProbeJson([...value, 0]), fixed);
  const shared = new Array(32767).fill(0); assert.throws(() => canonicalProbeJson([shared, shared]), fixed);
});
test("8MiB UTF8 serialized bytes cap includes quotes, Unicode and escape expansion", () => {
  const maximum = 8 * 1024 * 1024; const value = "x".repeat(maximum - 2);
  assert.equal(Buffer.byteLength(canonicalProbeJson(value), "utf8"), maximum);
  assert.throws(() => canonicalProbeJson(value + "x"), fixed);
  assert.throws(() => canonicalProbeJson("\u0000".repeat(Math.ceil(maximum / 6))), fixed);
  assert.throws(() => canonicalProbeJson("😀".repeat(maximum / 4)), fixed);
});
