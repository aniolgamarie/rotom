
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { digest } from "../managed-types.ts";
import { runAuxiliary } from "../auxiliary-executor.ts";

const write = (path, value) => { mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, value, { mode: 0o600 }); };
function fixture({ lostAllocate = false, lostStart = false, wrongProof = false, badCapture = false, keepProtected = false, onStart } = {}) {
  const root = mkdtempSync(join(tmpdir(), "modern-aux-")), calls = [], signal = new AbortController();
  let allocation, row, clock = 1000, marked = 0;
  const process_identity = { pid: 201, start_time: "fixed-birth" };
  const finish = (never = false) => {
    row = { ...row, state: never ? "failed" : "reclaimed", protected: false, spawn_committed: !never,
      process_identity: never ? null : process_identity, external_status: {} };
    const evidence = { schema_version: 1, kind: never ? "never-started" : "terminated", verified: true,
      execution_lease_id: "lease", grant_generation: row.grant_generation, allocation_journal_digest: "a".repeat(64),
      external_work_ids: [], process_identities: never ? [] : [process_identity] };
    evidence.evidence_digest = digest(evidence);
    if (wrongProof) evidence.evidence_digest = "0".repeat(64);
    row.termination_evidence = evidence;
  };
  const files = () => {
    const dir = join(root, "state/activity/outputs/lease");
    const stdout = "2 passed\n", stderr = "";
    for (const [name, value] of [["stdout", stdout], ["stderr", stderr]]) write(join(dir, name), value);
    const info = value => ({ path: value === stdout ? "stdout" : "stderr", bytes: Buffer.byteLength(value),
      sha256: badCapture ? "0".repeat(64) : createHash("sha256").update(value).digest("hex"), truncated: false, failed: false });
    write(join(dir, "capture.json"), JSON.stringify({ schema_version: 1, complete: true, truncated: false,
      streams: { stdout: info(stdout), stderr: info(stderr) } }));
    write(join(root, "state/activity/exits/lease.json"), JSON.stringify({ schema_version: 1, lease_id: "lease", exit_code: 0, process_identity }));
  };
  const supervisor = { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
    calls.push([method, structuredClone(args)]);
    if (method === "workspace_identity") return { workspace_key: "a".repeat(64), worktree_path: root };
    if (method === "workspace_snapshot") return { snapshot_digest: "b".repeat(64) };
    if (method === "allocate") {
      allocation = args; row = { lease_id: "lease", state: "allocating", protected: true, spawn_committed: false,
        grant_generation: 1, task_id: args.task_id, attempt_id: args.attempt_id, process_identity: null, external_status: {}, termination_evidence: null };
      if (lostAllocate) throw Error("lost synthetic allocation ACK");
      return { lease_id: "lease", allocation_id: "lease", state: "allocating", grant_generation: 1 };
    }
    if (method === "start") {
      row = { ...row, state: "running", spawn_committed: true, process_identity };
      files();
      if (onStart) onStart(signal);
      else if (!keepProtected) finish();
      if (lostStart) throw Error("lost synthetic start ACK");
      return { lease_id: "lease", attempt_id: allocation.attempt_id, state: "running" };
    }
    if (method === "inspect" || method === "reconcile") return structuredClone(row);
    if (method === "cancel") {
      row.grant_generation += 1; row.state = "cancel_requested";
      if (!keepProtected) finish();
      return { lease_id: "lease", state: row.state };
    }
    if (method === "abort_allocation") { finish(true); return { lease_id: "lease", state: row.state }; }
    throw Error("unexpected synthetic RPC");
  } };
  const runtime = { supervisor, instanceRoot: root, installed: { schema_version: 2, profile_id: "pi-full",
    lock_identity: "c".repeat(64), slice_identity: "d".repeat(64), resources: { extensions: [{ capability_id: "task-workflow" }] } },
    manifest: { profile_id: "pi-full", plugins: ["task-keeper"], plugin_capabilities: { "task-keeper": { capability_id: "task-workflow" } },
      permission_policy: {}, options: { task_keeper: { enabled: true, check_ids: ["unit"], project_root: "project" }, paths: { roots: { project: { path: root, purpose: "project" } } }, checks: { unit: { project_root: "project" } } } } };
  const cwd = join(root, "pi-home/task-keeper/worktrees/task");
  const options = { runtime, program: "check", payload: { check_id: "unit", cwd, task_id: "task", contract_digest: "a".repeat(64) },
    cwd, taskId: "task", signal: signal.signal, timeoutMs: 10000,
    now: () => clock, pause: async ms => { clock += ms; }, onDispatch: async () => { marked++; } };
  return { options, calls, signal, marked: () => marked, row: () => row };
}
test("modern auxiliary uses original authority without any legacy manager and validates capture", async () => {
  const f = fixture(), result = await runAuxiliary(f.options);
  assert.equal(result.exitCode, 0); assert.equal(result.stdout, "2 passed\n");
  assert.equal(result.terminationConfirmed, true); assert.equal(f.marked(), 1);
  assert.equal(f.calls.filter(([name]) => name === "start").length, 1);
  assert.equal(f.calls.filter(([name]) => name === "allocate").length, 1);
});
test("aborted before admission or unavailable Base has zero allocation", async () => {
  const f = fixture(); f.signal.abort();
  await assert.rejects(runAuxiliary(f.options)); assert.equal(f.calls.length, 0);
  const b = fixture(); b.options.runtime.manifest.profile_id = "pi-base";
  await assert.rejects(runAuxiliary(b.options), /CAPABILITY_MISSING/); assert.equal(b.calls.length, 0);
});
test("modern markSent failure has zero allocate", async () => {
  const f = fixture(); f.options.onDispatch = async () => { throw Error("synthetic markSent failure"); };
  await assert.rejects(runAuxiliary(f.options), /AUXILIARY_CONTROL_UNAVAILABLE/);
  assert.equal(f.calls.some(([name]) => name === "allocate"), false);
});
test("modern lost allocation ACK retains sent intent and never retries allocate/start", async () => {
  const f = fixture({ lostAllocate: true });
  await assert.rejects(runAuxiliary(f.options), /TERMINATION_UNKNOWN/);
  assert.equal(f.marked(), 1); assert.equal(f.calls.filter(([name]) => name === "allocate").length, 1);
  assert.equal(f.calls.some(([name]) => ["start", "abort_allocation", "cancel"].includes(name)), false);
});
test("modern lost start ACK only observes original lease, no resend", async () => {
  const f = fixture({ lostStart: true }), result = await runAuxiliary(f.options);
  assert.equal(result.terminationConfirmed, true);
  assert.equal(f.calls.filter(([name]) => name === "start").length, 1);
});
test("cancel during in-flight start requests one cancel and does not return late success", async () => {
  const f = fixture({ onStart: signal => signal.abort() });
  await assert.rejects(runAuxiliary(f.options), /AUXILIARY_CANCELED/);
  assert.equal(f.calls.filter(([name]) => name === "start").length, 1);
  assert.equal(f.calls.filter(([name]) => name === "cancel").length, 1);
  assert.equal(f.row().state, "reclaimed");
});
test("cancel unknown termination retains protection and never repeats stop", async () => {
  const f = fixture({ keepProtected: true, onStart: signal => signal.abort() });
  await assert.rejects(runAuxiliary(f.options), /TERMINATION_UNKNOWN/);
  assert.equal(f.row().protected, true);
  assert.equal(f.calls.filter(([name]) => name === "cancel").length, 1);
});
test("invalid original termination or capture hash cannot become successful", async () => {
  const f = fixture({ wrongProof: true });
  await assert.rejects(runAuxiliary(f.options), /TERMINATION_UNKNOWN/);
  const h = fixture({ badCapture: true });
  await assert.rejects(runAuxiliary(h.options), /ORDINARY_OPERATION_EVIDENCE/);
});


test("modern aux rejects task/root mismatches before any RPC allocation", async () => {
  const f = fixture(); f.options.payload.cwd = "/foreign";
  await assert.rejects(runAuxiliary(f.options), /AUXILIARY_INPUT_INVALID/); assert.equal(f.calls.length, 0);
  const g = fixture(); g.options.runtime.manifest.options.checks.unit.project_root = "unknown";
  await assert.rejects(runAuxiliary(g.options), /AUXILIARY_INPUT_INVALID/); assert.equal(g.calls.length, 0);
});

test("cancel after markSent stays unknown before allocation, no not-sent claim", async () => {
  const f = fixture(); f.options.onDispatch = async () => { f.signal.abort(); };
  await assert.rejects(runAuxiliary(f.options), /TERMINATION_UNKNOWN/);
  assert.equal(f.calls.some(([name]) => name === "allocate"), false);
});


test("modern check contract is closed and missing/invalid values make zero RPC or markSent calls", async () => {
  for (const invalid of [undefined, "", "short", "A".repeat(64), true]) {
    const f = fixture(); if (invalid === undefined) delete f.options.payload.contract_digest; else f.options.payload.contract_digest = invalid;
    await assert.rejects(runAuxiliary(f.options), /AUXILIARY_INPUT_INVALID/); assert.equal(f.calls.length, 0); assert.equal(f.marked(), 0);
  }
  const f = fixture(); f.options.payload.approved = true;
  await assert.rejects(runAuxiliary(f.options), /AUXILIARY_INPUT_INVALID/); assert.equal(f.calls.length, 0); assert.equal(f.marked(), 0);
});
