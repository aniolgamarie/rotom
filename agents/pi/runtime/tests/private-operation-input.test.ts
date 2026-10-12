import assert from "node:assert/strict";
import { test } from "node:test";
import { captureOperationInput } from "../private-operation-input.ts";

const invalid = error => error.message === "OPERATION_INPUT_INVALID" && error.exitCode === 2;
const capacity = error => error.message === "OPERATION_CAPACITY" && error.exitCode === 4;

test("capture owns a recursively frozen JSON copy and compares complete private input", () => {
  const input = { nested: [{ text: "synthetic-private-marker", flag: true }], nil: null, count: -0 };
  const captured = captureOperationInput(input);
  assert.deepEqual(Object.keys(captured).sort(), ["matches", "value"]);
  assert.equal(Object.isFrozen(captured), true);
  assert.equal(Object.isFrozen(captured.value.nested[0]), true);
  assert.equal(Object.isFrozen(captured.value.nested), true);
  assert.equal(Object.is(captured.value.count, -0), false);
  assert.equal(captured.matches({ count: 0, nil: null, nested: [{ flag: true, text: "synthetic-private-marker" }] }), true);
  input.nested[0].text = "changed";
  assert.equal(captured.value.nested[0].text, "synthetic-private-marker");
  assert.equal(captured.matches(input), false);
  assert.throws(() => { captured.value.nested[0].text = "mutation"; }, TypeError);
});
test("Unicode code point key order agrees with Python rather than UTF16 order", () => {
  const captured = captureOperationInput({ "𐀀": 1, "\ue000": 2, a: 3 });
  assert.deepEqual(Object.keys(captured.value), ["a", "\ue000", "𐀀"]);
  assert.equal(captured.matches({ a: 3, "\ue000": 2, "𐀀": 1 }), true);
});
test("null prototype and __proto__ are plain data with independent ownership", () => {
  const value = Object.create(null); value.__proto__ = { safe: true }; value.constructor = "data";
  const captured = captureOperationInput(value);
  assert.equal(Object.getPrototypeOf(captured.value), null);
  assert.deepEqual(captured.value.__proto__, { safe: true });
  assert.equal(captured.matches(JSON.parse('{"constructor":"data","__proto__":{"safe":true}}')), true);
});
for (const [value, encoding] of [
  [null, "null"], [true, "true"], [false, "false"], [-0, "0"], [9007199254740991, "9007199254740991"],
  ["中文😀\n\u0000\"\\", '"中文😀\\n\\u0000\\\"\\\\"'],
  [{ b: [], a: "é" }, '{"a":"é","b":[]}'],
]) test("exact canonical UTF8 capacity for " + typeof value + " " + encoding.length, () => {
  const size = Buffer.byteLength(encoding, "utf8");
  assert.equal(captureOperationInput(value, { maxBytes: size }).matches(value), true);
  assert.throws(() => captureOperationInput(value, { maxBytes: size - 1 }), size === 1 ? invalid : capacity);
});
for (const value of [undefined, NaN, Infinity, -Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1, 1n, () => {}, new Date(), new Map(), new Number(1), /x/, "\ud800", "\udc00", { "\ud800": 1 }, { nested: undefined }]) {
  test("rejects non JSON input without echoing contents " + typeof value, () => {
    assert.throws(() => captureOperationInput(value), invalid);
    assert.throws(() => captureOperationInput(null).matches(value), invalid);
  });
}
for (const kind of ["getter", "setter", "symbol", "hidden", "toJSON", "custom-prototype", "sparse", "array-extra", "array-symbol", "array-getter"]) test("rejects descriptor pollution " + kind, () => {
  let value = {}; let invoked = 0;
  if (kind === "getter") Object.defineProperty(value, "secret", { enumerable: true, get() { invoked++; return "synthetic-private-marker"; } });
  if (kind === "setter") Object.defineProperty(value, "secret", { enumerable: true, set(_) { invoked++; } });
  if (kind === "symbol") value[Symbol("secret")] = 1;
  if (kind === "hidden") Object.defineProperty(value, "secret", { value: "synthetic-private-marker" });
  if (kind === "toJSON") value.toJSON = () => { invoked++; return {}; };
  if (kind === "custom-prototype") value = Object.create({ secret: "synthetic-private-marker" });
  if (kind === "sparse") value = new Array(2);
  if (kind === "array-extra") { value = []; value.extra = true; }
  if (kind === "array-symbol") { value = []; value[Symbol()] = true; }
  if (kind === "array-getter") { value = [1]; Object.defineProperty(value, "0", { enumerable: true, get() { invoked++; return 1; } }); }
  assert.throws(() => captureOperationInput(value), invalid);
  assert.throws(() => captureOperationInput(null).matches(value), invalid);
  assert.equal(invoked, 0);
});
test("depth32 accepts leaves and depth33 rejects, including cycles", () => {
  let value = null; for (let i = 0; i < 32; i++) value = [value];
  captureOperationInput(value);
  assert.throws(() => captureOperationInput([value]), invalid);
  const cycle = {}; cycle.self = cycle; assert.throws(() => captureOperationInput(cycle), invalid);
});
for (const maxBytes of [0, -1, 1.5, true, Infinity, 1024 * 1024 + 1, "10"]) test("invalid explicit capacity " + String(maxBytes), () => {
  assert.throws(() => captureOperationInput(null, { maxBytes }), invalid);
});
test("matches preserves the same size bound and never returns a digest", () => {
  const captured = captureOperationInput("a", { maxBytes: 3 });
  assert.throws(() => captured.matches("synthetic-private-marker"), capacity);
  assert.equal(captured.matches("b"), false);
  assert.throws(() => captureOperationInput("synthetic-private-marker".repeat(60000)), capacity);
});

test("exact 1MiB boundary accepts without truncation and rejects one extra byte", () => {
  const value = "a".repeat(1024 * 1024 - 2);
  const captured = captureOperationInput(value);
  assert.equal(captured.value.length, value.length);
  assert.equal(captured.matches(value), true);
  assert.throws(() => captureOperationInput(value + "a"), capacity);
});
test("valid surrogate pairs remain Unicode characters while broken nested pairs reject", () => {
  const captured = captureOperationInput({ emoji: "😀", text: "x😀y" });
  assert.equal(captured.matches({ text: "x\ud83d\ude00y", emoji: "\ud83d\ude00" }), true);
  assert.throws(() => captured.matches({ emoji: "😀", text: "x\ud83dy" }), invalid);
});
test("non enumerable array indices and inherited array prototypes cannot be captured", () => {
  const array = [1]; Object.defineProperty(array, "0", { enumerable: false });
  assert.throws(() => captureOperationInput(array), invalid);
  const subclass = [1]; Object.setPrototypeOf(subclass, Object.create(Array.prototype));
  assert.throws(() => captureOperationInput(subclass), invalid);
});
test("all primitive and nested type changes affect matches", () => {
  const captured = captureOperationInput({ value: [1, null, true, "1"] });
  for (const other of [{ value: ["1", null, true, "1"] }, { value: [1, false, true, "1"] }, { value: [1, null, true] }, { value: [1, null, true, "1"], extra: null }]) {
    assert.equal(captured.matches(other), false);
  }
});

test("proxies reject without executing reflection traps, including revoked proxies", () => {
  let traps = 0;
  const value = new Proxy({}, { getPrototypeOf() { traps++; throw new Error("synthetic-private-marker"); }, ownKeys() { traps++; return []; } });
  assert.throws(() => captureOperationInput(value), invalid);
  assert.throws(() => captureOperationInput(null).matches({ nested: value }), invalid);
  const pair = Proxy.revocable([], {}); pair.revoke();
  assert.throws(() => captureOperationInput(pair.proxy), invalid);
  assert.equal(traps, 0);
});

test("toJSON data keys follow JSON semantics without calling conversion methods", () => {
  const captured = captureOperationInput({ toJSON: "ordinary data", nested: { toJSON: null } });
  assert.equal(captured.matches({ nested: { toJSON: null }, toJSON: "ordinary data" }), true);
  let invoked = false;
  assert.throws(() => captureOperationInput({ toJSON() { invoked = true; return {}; } }), invalid);
  assert.equal(invoked, false);
});

test("finite MCP numbers require an explicit capture option and preserve integer defaults", () => {
  const input = { ratio: 1.25, large: 1e100, negative: -0 };
  assert.throws(() => captureOperationInput(input), invalid);
  const captured = captureOperationInput(input, { allowFiniteNumbers: true });
  assert.equal(captured.value.ratio, 1.25);
  assert.equal(captured.matches({ large: 1e100, negative: 0, ratio: 1.25 }), true);
  for (const value of [NaN, Infinity, -Infinity]) assert.throws(() => captureOperationInput(value, { allowFiniteNumbers: true }), invalid);
  assert.throws(() => captureOperationInput(1, { allowFiniteNumbers: "yes" }), invalid);
});
