// 默认仅plan/own FakeSupervisor；不会执行native入口/import任何SDK。
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { validatePlan, buildInvocation, createFakeSupervisor, LIMITS } from "../../../../scripts/pi-probe-base-product-sdk.mjs";
const original = JSON.parse(fs.readFileSync(new URL("./plan.json", import.meta.url), "utf8"));
function fakeFrozen() {
  const plan = structuredClone(original); plan.state = "frozen-pending-separate-authorization";
  plan.candidate_inventory = { fixture: "candidate-inventory.json", receipt_root_name: "own-candidate", sha256: "a".repeat(64), entries: 2, file_count: 1, bytes: 1 };
  plan.source_inventory = [...plan.base_runtime_seed, ...plan.packages.map(pkg => `agents/pi/packages/${pkg}/package.json`)].map(name => ({ path: name, bytes: 1, sha256: "b".repeat(64) })); return plan;
}
const request = (file, name = "write") => ({ control_id: "control", request_id: "request", context: { own: "context" }, tool_name: name, input: { path: file, content: "owned" } });
function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "base-product-fake-")), cwd = path.join(root, "project"), stateRoot = path.join(root, "state");
  fs.mkdirSync(cwd, { mode: 0o700 }); fs.mkdirSync(stateRoot, { mode: 0o700 });
  const budget = { sender: 0, starts: 0, rpc: 0 }; return { root, cwd, stateRoot, budget, ...createFakeSupervisor({ cwd, stateRoot, budget }), dispose: () => fs.rmSync(root, { recursive: true, force: true }) };
}
test("closed plan is prepared-only, has twelve scenes and mandatory source/receipt before native", () => {
  const plan = validatePlan(original); assert.equal(plan.cases.length, 12); assert.equal(plan.b12.execute, true);
  assert.throws(() => validatePlan(original, { requireFrozen: true }), /BASE_PRODUCT_PROBE_INVALID/);
  assert.equal(validatePlan(fakeFrozen(), { requireFrozen: true }).state, "frozen-pending-separate-authorization");
});
test("scope widening, unbounded budgets and old Full alias stages reject", () => {
  for (const edit of [p => { p.extra = true; }, p => { p.limits.starts++; }, p => { p.links[0].target = "../../agents/pi/runtime"; },
    p => { p.packages.push("model-delegate"); }, p => { p.base_runtime_seed.pop(); }, p => { p.b12.execute = false; }]) {
    const plan = structuredClone(original); edit(plan); assert.throws(() => validatePlan(plan), /BASE_PRODUCT_PROBE_INVALID/);
  }
});
test("source closure omissions, duplicate pins and escape paths cannot freeze", () => {
  for (const edit of [p => { p.source_inventory.pop(); }, p => { p.source_inventory.push(p.source_inventory[0]); }, p => { p.source_inventory[0].path = "agents/pi/runtime/../Full.ts"; }, p => { p.candidate_inventory = null; }]) {
    const plan = fakeFrozen(); edit(plan); assert.throws(() => validatePlan(plan, { requireFrozen: true }), /BASE_PRODUCT_PROBE_INVALID/);
  }
});
test("argv only describes original readonly/network-disabled pattern, empty ambient env and new entry", () => {
  const args = { plan: fakeFrozen(), sourceRoot: "/data/own/source", candidateRoot: "/data/own/candidate", nodeRoot: "/data/own/node", workRoot: "/tmp/own-work", worker: "/data/own/worker.mjs", fixtureRoot: "/data/own/fixture" };
  const result = buildInvocation(args); assert.deepEqual(result.env, {}); assert(result.argv.includes("--unshare-all")); assert(!result.argv.includes("--clearenv"));
  assert.equal(result.argv.filter(value => value === "--bind").length, 1); assert.equal(result.argv.at(-1), "--native-base-product-sdk-probe");
  assert.throws(() => buildInvocation({ ...args, workRoot: "/data/own/source/work" }), /BASE_PRODUCT_PROBE_INVALID/);
});
test("FakeSupervisor consumed receipt executes own IO once, never an OS process", async () => {
  const f = fixture(); try {
    const prepared = await f.supervisor.call("ordinary_admission_prepare", request("new.txt"));
    const permit = await f.supervisor.call("ordinary_admission_issue_deterministic", { operation_id: prepared.operation_id, context: prepared.context });
    const ticket = await f.supervisor.call("ordinary_admission_consume", { permit, context: prepared.context });
    await f.supervisor.call("ordinary_stage_write", { operation_id: ticket.operation_id, content: "owned", expected_digest: null });
    await f.supervisor.call("start", { lease_id: ticket.lease_id, program: "file-operation", payload: { operation_id: ticket.operation_id } });
    assert.equal(fs.readFileSync(path.join(f.cwd, "new.txt"), "utf8"), "owned"); assert.equal(f.budget.starts, 1);
    await assert.rejects(f.supervisor.call("start", { lease_id: ticket.lease_id, program: "file-operation", payload: { operation_id: ticket.operation_id } }), /BASE_PRODUCT_PROBE_INVALID/);
  } finally { f.dispose(); }
});
test("fake corpus cannot escape owned project or exceed operation/start budget", async () => {
  const f = fixture(); try {
    await assert.rejects(f.supervisor.call("ordinary_admission_prepare", request("../escape")), /BASE_PRODUCT_PROBE_INVALID/);
    f.budget.rpc = LIMITS.rpc_calls; await assert.rejects(f.supervisor.call("ordinary_finish", {}), /BASE_PRODUCT_PROBE_INVALID/);
  } finally { f.dispose(); }
});
test("stdio fixture emits only finite fixed JSON-RPC receipts and captures actual supplied frames", async () => {
  const f = fixture(); try {
    const ticket = await f.supervisor.call("ordinary_mcp_stdio_prepare", { server_name: "docs", operation_id: "own-service" });
    await f.supervisor.call("start", { lease_id: ticket.lease_id, program: "ordinary-command", payload: { operation_id: ticket.operation_id } });
    const frame = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26" } }) + "\n";
    await f.supervisor.call("ordinary_command_stdin", { operation_id: ticket.operation_id, data: frame, end: false });
    const output = await f.supervisor.call("ordinary_command_output", { operation_id: ticket.operation_id, cursor: 0 });
    assert.equal(JSON.parse(Buffer.from(output.events[0].data_b64, "base64")).result.serverInfo.name, "own-fake-docs");
    await f.supervisor.call("cancel", { lease_id: ticket.lease_id });
    const capture = JSON.parse(fs.readFileSync(path.join(f.stateRoot, "activity/outputs", ticket.lease_id, "capture.json"), "utf8"));
    assert.equal(capture.streams.stdout.bytes, fs.statSync(path.join(f.stateRoot, "activity/outputs", ticket.lease_id, "stdout")).size);
  } finally { f.dispose(); }
});

test("shell prepare/status/consume keep the prepared resolution digest and exact own executor shapes", async () => {
  const f = fixture(); try {
    const prepared = await f.supervisor.call("ordinary_admission_prepare", { ...request("."), tool_name: "bash", input: { command: "synthetic only" } });
    const status = await f.supervisor.call("ordinary_admission_status", { operation_id: prepared.operation_id });
    assert.equal(status.execution.request_digest, prepared.operation_digest);
    assert.equal(status.execution.command_ref, prepared.resolution.target.command_ref);
    assert.equal(status.execution.timeout_seconds * 1000, prepared.resolution.target.timeout_ms);
    assert.equal(status.execution.write, Boolean(prepared.resolution.write_roots.length));
    const permit = await f.supervisor.call("ordinary_admission_issue_deterministic", { operation_id: prepared.operation_id, context: prepared.context });
    const ticket = await f.supervisor.call("ordinary_admission_consume", { permit, context: prepared.context });
    assert.equal(ticket.request_digest, prepared.operation_digest);
    const before = await f.supervisor.call("inspect", { lease_id: ticket.lease_id });
    assert.equal(before.state, "allocating"); assert.equal(before.spawn_committed, false); assert.equal(before.process_identity, null);
    await assert.rejects(f.supervisor.call("start", { lease_id: ticket.lease_id, program: "file-operation", payload: { operation_id: ticket.operation_id } }), /BASE_PRODUCT_PROBE_INVALID/);
    const started = await f.supervisor.call("start", { lease_id: ticket.lease_id, program: "ordinary-shell", payload: { operation_id: ticket.operation_id } });
    assert.equal(started.lease_id, ticket.lease_id);
    const ended = await f.supervisor.call("reconcile", { lease_id: ticket.lease_id });
    assert.equal(ended.protected, false); assert.equal(ended.termination_evidence.verified, true);
    assert.equal(f.budget.starts, 1);
  } finally { f.dispose(); }
});

test("graded fake prepared digests match the original public admission canonical newline contract", async () => {
  const { digest } = await import("../../../../agents/pi/runtime/managed-types.ts");
  const f = fixture(); try {
    const prepared = await f.supervisor.call("ordinary_admission_prepare", request("source.txt"));
    const { operation_digest, ...bound } = prepared;
    assert.equal(operation_digest, digest(bound));
  } finally { f.dispose(); }
});

test("fake grep relative reads remain below the selected project root", async () => {
  const f = fixture(); try {
    fs.writeFileSync(path.join(f.cwd, "source.txt"), "needle");
    const prepared = await f.supervisor.call("ordinary_admission_prepare", { ...request("."), tool_name: "grep" });
    const read = await f.supervisor.call("ordinary_read", { operation_id: prepared.operation_id, relative_path: "source.txt", offset: 0, limit: 65536 });
    assert.equal(Buffer.from(read.data_b64, "base64").toString(), "needle");
    await assert.rejects(f.supervisor.call("ordinary_read", { operation_id: prepared.operation_id, relative_path: "../escape", offset: 0, limit: 65536 }), /BASE_PRODUCT_PROBE_INVALID/);
  } finally { f.dispose(); }
});
