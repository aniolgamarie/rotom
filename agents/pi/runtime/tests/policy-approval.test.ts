import assert from "node:assert/strict";
import { test } from "node:test";
import { aggregateApproval, assertRule, canonical } from "../managed-types.ts";
import { convertParentPolicy } from "../permission-policy.ts";

const modes = ["human", "reviewer", "deterministic-policy"];
const rule = (kind = "file", effect = "allow") => ({ id: "fixture", kind, effect,
  tool_ids: [kind === "file" ? "read" : "bash"], operations: [kind === "file" ? "read" : "execute"],
  ...(kind === "file" ? { root_ref: "project", relative_path: ".", match: "subtree" } : { command_ref: "tool:build" }) });

for (const kind of ["file", "command"]) for (const approval of modes) test(`${kind} accepts explicit ${approval} without mutation`, () => {
  const value = { ...rule(kind), approval }, before = canonical(value);
  assert.equal(assertRule(value), value);
  assert.equal(canonical(value), before);
});

test("old rules stay unchanged without a synthetic approval field", () => {
  const value = rule(), before = canonical(value);
  assertRule(value); assert.equal(canonical(value), before);
  assert.equal(Object.hasOwn(value, "approval"), false);
});

for (const approval of [...modes, null, true, 1, {}, [], "unknown"]) test(`deny rejects approval ${typeof approval}`, () => {
  assert.throws(() => assertRule({ ...rule("file", "deny"), approval }));
});
for (const approval of [null, true, 1, {}, [], "unknown"]) test(`allow rejects invalid approval ${typeof approval}`, () => {
  assert.throws(() => assertRule({ ...rule(), approval }));
});

test("rule approval getters and proxies are never executed", () => {
  let calls = 0;
  const value = rule(); Object.defineProperty(value, "approval", { enumerable: true, get() { calls++; throw Error("SYNTHETIC_PRIVATE"); } });
  assert.throws(() => assertRule(value));
  const proxy = new Proxy(rule(), { get() { calls++; throw Error("SYNTHETIC_PRIVATE"); }, getOwnPropertyDescriptor() { calls++; throw Error("SYNTHETIC_PRIVATE"); } });
  assert.throws(() => assertRule(proxy)); assert.equal(calls, 0);
  assert.throws(() => assertRule({ ...rule(), approval: "human", source: "reviewer" }));
});

for (const values of modes.flatMap(a => modes.flatMap(b => modes.map(c => [a, b, c])))) test(`aggregation is strictest for ${values.join("/")}`, () => {
  const before = [...values], expected = modes.find(mode => values.includes(mode));
  assert.equal(aggregateApproval(values), expected);
  assert.equal(aggregateApproval([...values].reverse()), expected);
  assert.deepEqual(values, before);
});

test("single and repeated modes retain classification at maximum capacity", () => {
  for (const mode of modes) {
    assert.equal(aggregateApproval([mode]), mode);
    assert.equal(aggregateApproval(Array(4096).fill(mode)), mode);
  }
});

for (const value of [null, {}, [], [null], [true], [1], ["unknown"], Array(4097).fill("human"), new class extends Array {}("human"), [new String("human")], new Array(2)]) test("invalid aggregation safely rejects native type/size/holes", () => {
  assert.throws(() => aggregateApproval(value), error => error.code === "APPROVAL_CLASSIFICATION_INVALID" && error.exitCode === 2 && !String(error).includes("SYNTHETIC_PRIVATE"));
});

test("aggregation cannot execute accessors, Proxy traps or arbitrary coercion", () => {
  let calls = 0;
  const values = ["human"];
  Object.defineProperty(values, "0", { enumerable: true, get() { calls++; throw Error("SYNTHETIC_PRIVATE"); } });
  const proxy = new Proxy(["human"], { get() { calls++; throw Error("SYNTHETIC_PRIVATE"); }, ownKeys() { calls++; throw Error("SYNTHETIC_PRIVATE"); } });
  const coercion = [{ toString() { calls++; return "human"; } }];
  for (const value of [values, proxy, coercion]) assert.throws(() => aggregateApproval(value), /APPROVAL_CLASSIFICATION_INVALID/);
  assert.equal(calls, 0);
});

test("aggregation rejects extra array keys/symbols and hidden element descriptors", () => {
  for (const key of ["extra", Symbol("private")]) {
    const value = ["human"]; value[key] = true;
    assert.throws(() => aggregateApproval(value), /APPROVAL_CLASSIFICATION_INVALID/);
  }
  const hidden = ["human"]; Object.defineProperty(hidden, "0", { enumerable: false });
  assert.throws(() => aggregateApproval(hidden), /APPROVAL_CLASSIFICATION_INVALID/);
});

for (const kind of ["file", "command"]) test(`canonical parent ${kind} conversion retains approval and does not rewrite source`, () => {
  const input = { ...rule(kind), approval: "reviewer" };
  const source = { schema_version: 1, source_id: "fixture", source_digest: "a".repeat(64), rules: [input] };
  const before = canonical(source);
  const converted = convertParentPolicy(source, { roots: {}, commands: {} });
  assert.equal(converted.policy.rules[0].approval, "reviewer");
  assert.equal(canonical(source), before);
});

test("legacy absolute-file/argv inputs explicitly reject approval rather than dropping it", () => {
  const rules = [
    { id: "file", kind: "absolute-file", effect: "allow", tool_ids: ["read"], operations: ["read"], path: "/fixture/project", recursive: true, approval: "human" },
    { id: "cmd", kind: "argv", effect: "allow", tool_ids: ["bash"], executable: "/fixture/bash", args: [], approval: "reviewer" },
  ];
  for (const value of rules) assert.throws(() => convertParentPolicy({ schema_version: 1, source_id: "fixture", source_digest: "a".repeat(64), rules: [value] }, {
    roots: { project: { path: "/fixture/project" } }, commands: { "tool:build": { argv: ["/fixture/bash"] } },
  }), /PERMISSION_UNREPRESENTABLE/);
});
