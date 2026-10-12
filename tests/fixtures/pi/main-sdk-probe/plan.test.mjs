// 默认测试只读自有JSON和plan函数；不加载SDK、不调用native入口。
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import { validatePlan, buildInvocation, CASES } from "../../../../scripts/pi-probe-main-sdk.mjs";
const template = JSON.parse(fs.readFileSync(new URL("./plan.json", import.meta.url), "utf8"));
const clone = () => structuredClone(template);
function frozen() {
  const plan = clone(); plan.state = "frozen";
  plan.candidate_inventory = { fixture: "candidate-inventory.json", sha256: "c".repeat(64), entries: 2, file_count: 1, bytes: 1 };
  plan.source_pins = Object.fromEntries(["official-model-scope.ts", "official-model-runtime.ts", "official-session.ts"].map(name => ["agents/pi/runtime/" + name, "a".repeat(64)]));
  plan.candidate_pins = Object.fromEntries(["pi-coding-agent", "pi-ai"].map(name => [`node_modules/@earendil-works/${name}/package.json`, "b".repeat(64)]));
  return plan;
}
const invocation = plan => ({ plan, sourceRoot: "/data/own/source", candidateRoot: "/data/own/candidate", nodeRoot: "/data/own/node", workRoot: "/tmp/own-main-sdk-work", worker: "/data/own/probe.mjs", fixtureRoot: "/data/own/fixture" });
const denied = value => assert.throws(value, /MAIN_SDK_PROBE_PLAN_INVALID/);
test("preparation plan is inert and independently copied; execution requires final freeze", () => {
  const plan = validatePlan(template); assert.deepEqual(plan.cases, [...CASES]); plan.provider.id = "changed";
  assert.equal(template.provider.id, "synthetic-main-probe"); denied(() => validatePlan(template, { requireFrozen: true })); denied(() => buildInvocation(invocation(template)));
});
test("closed plan rejects unknown config, omitted scenario and real credential substitution", () => {
  for (const edit of [p => { p.ambient = true; }, p => { p.cases.pop(); }, p => { p.provider.api_key = "do-not-accept"; }, p => { p.provider.base_url = "https://live.invalid"; }]) {
    const plan = clone(); edit(plan); denied(() => validatePlan(plan));
  }
});
test("fixed candidate versions, sandbox locations and finite deadlines cannot broaden", () => {
  for (const edit of [p => { p.versions.node = "25.0.0"; }, p => { p.source_root = "/"; }, p => { p.limits.total_timeout_ms = Infinity; }, p => { p.limits.case_timeout_ms = 999999; }]) {
    const plan = clone(); edit(plan); denied(() => validatePlan(plan));
  }
});
test("final plan requires source and package pins and rejects escaping paths", () => {
  assert.equal(validatePlan(frozen(), { requireFrozen: true }).state, "frozen");
  for (const edit of [p => { delete p.source_pins["agents/pi/runtime/official-session.ts"]; }, p => { p.source_pins["agents/pi/runtime/../../secret"] = "a".repeat(64); }, p => { p.candidate_pins["node_modules/@earendil-works/pi-ai/package.json"] = "invalid"; }]) {
    const plan = frozen(); edit(plan); denied(() => validatePlan(plan, { requireFrozen: true }));
  }
});
test("argv preparation keeps SDK/source readonly and network/ambient environment disabled without spawning", () => {
  const built = buildInvocation(invocation(frozen())); assert.deepEqual(built.env, {});
  assert(built.argv.includes("--unshare-all"));
  assert(!built.argv.includes("--clearenv"));
  for (const [host, guest] of [["/data/own/source", "/source"], ["/data/own/candidate", "/candidate"], ["/data/own/node", "/node"]]) {
    const index = built.argv.indexOf(host); assert.equal(built.argv[index - 1], "--ro-bind"); assert.equal(built.argv[index + 1], guest);
  }
  assert.equal(built.argv.filter(word => word === "--bind").length, 1); assert(built.argv.includes("--native-main-sdk-probe"));
  assert(!built.argv.includes("--share-net")); assert(!built.argv.includes("--persist"));
});
test("runner plan refuses ancestor writable work and malformed host paths", () => {
  for (const edit of [p => { p.workRoot = p.sourceRoot + "/work"; }, p => { p.candidateRoot = "/data/own/../candidate"; }, p => { p.nodeRoot = "/"; }, p => { p.workRoot = "/home/account/work"; }]) {
    const options = invocation(frozen()); edit(options); denied(() => buildInvocation(options));
  }
});

// tiny真实自有文件只验证完整收据checker，不触碰实际candidate或任何SDK。
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { verifyCandidateInventory } from "./candidate-inventory.mjs";
const sha = value => createHash("sha256").update(value).digest("hex");
function tinyTree() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "main-sdk-inventory-")), root = path.join(work, "candidate");
  fs.mkdirSync(root, { mode: 0o700 }); fs.writeFileSync(path.join(root, "owned.txt"), "own", { mode: 0o600 });
  const rows = [{ path: "candidate", kind: "directory", original_mode: 0o700 }, { path: "candidate/owned.txt", kind: "file", bytes: 3, sha256: sha("own"), original_mode: 0o644 }];
  const receiptPath = path.join(work, "receipt.json"), data = JSON.stringify(rows); fs.writeFileSync(receiptPath, data, { mode: 0o600 });
  return { work, root, receiptPath, receiptSha256: sha(data) };
}
test("complete receipt checker accepts a tiny own tree without SDK or mutation", () => {
  const f = tinyTree(); try {
    assert.deepEqual(verifyCandidateInventory({ candidateRoot: f.root, receiptPath: f.receiptPath, receiptSha256: f.receiptSha256 }), { sha256: f.receiptSha256, entries: 2, file_count: 1, bytes: 3 });
    assert.equal(fs.readFileSync(path.join(f.root, "owned.txt"), "utf8"), "own");
  } finally { fs.rmSync(f.work, { recursive: true, force: true }); }
});
test("complete receipt rejects extra and changed own files, not merely matching package metadata", () => {
  const f = tinyTree(); try {
    const check = () => verifyCandidateInventory({ candidateRoot: f.root, receiptPath: f.receiptPath, receiptSha256: f.receiptSha256 });
    fs.writeFileSync(path.join(f.root, "extra.txt"), "extra", { mode: 0o600 }); assert.throws(check, /MAIN_SDK_PROBE_CANDIDATE_INVALID/);
    fs.unlinkSync(path.join(f.root, "extra.txt")); fs.writeFileSync(path.join(f.root, "owned.txt"), "changed", { mode: 0o600 }); assert.throws(check, /MAIN_SDK_PROBE_CANDIDATE_INVALID/);
  } finally { fs.rmSync(f.work, { recursive: true, force: true }); }
});
