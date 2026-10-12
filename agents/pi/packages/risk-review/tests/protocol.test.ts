import assert from "node:assert/strict";
import { test } from "node:test";
import { parseReviewResponse } from "../src/protocol.ts";

const code = "PI_RISK_REVIEW_PROTOCOL_INVALID";
const binding = () => ({ request_id: "1".repeat(32), operation_digest: "a".repeat(64), context_digest: "b".repeat(64), reviewer_identity: "c".repeat(64) });
const response = (decision = "allow", reason_code = "authorized-in-scope") => ({ schema_version: 1, ...binding(), decision, reason_code });
const raw = (decision, reason) => JSON.stringify(response(decision, reason));
function invalid(value, expected = binding()) {
  assert.throws(() => parseReviewResponse(value, expected), error => {
    assert.equal(error.message, code); assert.equal(error.code, code);
    assert.equal(error.cause, undefined); return true;
  });
}

for (const [decision, reason] of [["allow", "authorized-in-scope"], ["ask", "ambiguous-intent"], ["ask", "unverifiable-input"],
  ["ask", "needs-human"], ["deny", "outside-user-scope"], ["deny", "destructive-change"], ["deny", "untrusted-authorization"]])
  test("valid closed candidate " + decision + "/" + reason, () => {
    const expected = binding(), before = structuredClone(expected), result = parseReviewResponse(raw(decision, reason), expected);
    assert.deepEqual(result, { ...response(decision, reason), source: "reviewer" });
    assert.equal(Object.isFrozen(result), true); assert.deepEqual(expected, before);
    assert.throws(() => { result.source = "human"; }, TypeError);
    expected.operation_digest = "d".repeat(64); assert.equal(result.operation_digest, "a".repeat(64));
    assert.equal(Object.keys(result).length, 8);
  });

test("valid JSON whitespace and escaped string tokens are accepted", () => {
  const encoded = raw().replace('"allow"', '"\\u0061llow"').replace('"request_id"', '"request\\u005fid"');
  assert.equal(parseReviewResponse(" \t\r\n" + encoded + "\n", binding()).decision, "allow");
});
test("8192 UTF8 byte boundary is inclusive", () => {
  const value = raw(); assert.equal(Buffer.byteLength(value), value.length);
  assert.equal(parseReviewResponse(value + " ".repeat(8192 - value.length), binding()).source, "reviewer");
  invalid(value + " ".repeat(8193 - value.length));
});

for (const version of ["1.00000000000000001", "0.99999999999999999", "1.0", "1e0"])
  test("version token must be literal integer 1 without floating point coercion " + version, () => {
    invalid(raw().replace('"schema_version":1', '"schema_version":' + version));
  });

for (const key of Object.keys(binding())) test("binding mismatch " + key, () => {
  const value = response(); value[key] = key === "request_id" ? "2".repeat(32) : "d".repeat(64); invalid(JSON.stringify(value));
});
for (const fault of ["source", "human", "operation_id", "free-reason", "missing", "version-bool", "version-string", "version-two", "version-nested", "array", "null", "decision", "reason", "reason-nested", "binding-upper", "binding-short", "binding-number", "binding-null"])
  test("closed wire refuses " + fault, () => {
    const value = response();
    if (fault === "source") value.source = "human";
    if (fault === "human") value.human = true;
    if (fault === "operation_id") value.operation_id = "1".repeat(32);
    if (fault === "free-reason") value.reason = "synthetic-private-marker";
    if (fault === "missing") delete value.reason_code;
    if (fault === "version-bool") value.schema_version = true;
    if (fault === "version-string") value.schema_version = "1";
    if (fault === "version-two") value.schema_version = 2;
    if (fault === "version-nested") value.schema_version = { value: 1 };
    if (fault === "array") return invalid(JSON.stringify([value]));
    if (fault === "null") return invalid("null");
    if (fault === "decision") value.decision = "approve";
    if (fault === "reason") value.reason_code = "anything-safe";
    if (fault === "reason-nested") value.reason_code = { authorized: true };
    if (fault === "binding-upper") value.operation_digest = "A".repeat(64);
    if (fault === "binding-short") value.context_digest = "b".repeat(63);
    if (fault === "binding-number") value.reviewer_identity = 123;
    if (fault === "binding-null") value.request_id = null;
    invalid(JSON.stringify(value));
  });
for (const [decision, reason] of [["allow", "needs-human"], ["allow", "outside-user-scope"], ["ask", "authorized-in-scope"], ["ask", "destructive-change"], ["deny", "ambiguous-intent"], ["deny", "authorized-in-scope"]])
  test("reason cannot switch decision " + decision + "/" + reason, () => invalid(raw(decision, reason)));

for (const fault of ["duplicate", "escaped-duplicate", "double-object", "prefix", "suffix", "fence", "nan", "infinity", "trailing-comma", "unquoted", "unterminated", "control", "escape", "lone-surrogate", "raw-surrogate", "unicode-byte-overflow"])
  test("flat token parser refuses " + fault, () => {
    let value = raw();
    if (fault === "duplicate") value = value.replace("{", '{"decision":"deny",');
    if (fault === "escaped-duplicate") value = value.replace("{", '{"decis\\u0069on":"deny",');
    if (fault === "double-object") value += raw();
    if (fault === "prefix") value = "approved " + value;
    if (fault === "suffix") value += " done";
    if (fault === "fence") value = "```json\n" + value + "\n```";
    if (fault === "nan") value = value.replace('"schema_version":1', '"schema_version":NaN');
    if (fault === "infinity") value = value.replace('"schema_version":1', '"schema_version":Infinity');
    if (fault === "trailing-comma") value = value.slice(0, -1) + ",}";
    if (fault === "unquoted") value = value.replace('"decision"', 'decision');
    if (fault === "unterminated") value = value.slice(0, -2);
    if (fault === "control") value = value.replace("authorized-in-scope", "authorized\u0000-in-scope");
    if (fault === "escape") value = value.replace("authorized-in-scope", "authorized\\x20scope");
    if (fault === "lone-surrogate") value = value.replace("authorized-in-scope", "\\ud800");
    if (fault === "raw-surrogate") value = value.replace("authorized-in-scope", "\ud800");
    if (fault === "unicode-byte-overflow") value = "中".repeat(3000);
    invalid(value);
  });
for (const value of [undefined, null, {}, Buffer.from("{}"), "", "[]", "true", "false", "0"]) test("raw type or top-level shape rejected " + typeof value, () => invalid(value));
for (const fault of ["missing", "extra", "upper", "null", "array", "getter", "symbol", "proxy"]) test("expected binding is closed trusted data " + fault, () => {
  let expected = binding();
  if (fault === "missing") delete expected.request_id;
  if (fault === "extra") expected.source = "human";
  if (fault === "upper") expected.context_digest = "B".repeat(64);
  if (fault === "null") expected = null;
  if (fault === "array") expected = Object.values(expected);
  if (fault === "getter") Object.defineProperty(expected, "request_id", { get() { assert.fail("getter must not execute"); }, enumerable: true });
  if (fault === "symbol") expected[Symbol("authority")] = true;
  if (fault === "proxy") expected = new Proxy(expected, { get() { assert.fail("proxy must not execute"); } });
  invalid(raw(), expected);
});
