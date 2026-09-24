import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runAuxiliary } from "../auxiliary-executor.ts";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";

const write = (path, value) => { mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, value, { mode: 0o600 }); };

test("trusted checks use the existing manager queue and verify bounded capture identity", async () => {
  const root = mkdtempSync(join(tmpdir(), "auxiliary-")), manager = new AgentManager(undefined, 1), calls = [];
  const key = Symbol.for("agentcfg.pi.managed.v1");
  const previous = globalThis[key];
  globalThis[key] = { manager, pi: {}, getContext: () => ({ cwd: root }) };
  const supervisor = { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
    calls.push(method);
    if (method === "workspace_identity") return { workspace_key: "a".repeat(64), worktree_path: root };
    if (method === "workspace_snapshot") return { snapshot_digest: "b".repeat(64) };
    if (method === "allocate") return { lease_id: "lease" };
    if (method === "start") {
      const directory = join(root, "state/activity/outputs/lease");
      const stdout = "2 passed in 0.10s\n", stderr = "";
      for (const [name, text] of [["stdout", stdout], ["stderr", stderr]]) write(join(directory, name), text);
      write(join(directory, "capture.json"), JSON.stringify({ complete: true, truncated: false,
        streams: { stdout: { sha256: createHash("sha256").update(stdout).digest("hex") }, stderr: { sha256: createHash("sha256").update(stderr).digest("hex") } } }));
      write(join(root, "state/activity/exits/lease.json"), JSON.stringify({ lease_id: "lease", exit_code: 0, process_identity: {} }));
      return { state: "running" };
    }
    if (method === "inspect" || method === "reconcile") return { lease_id: "lease", protected: false, state: "reclaimed", process_identity: {}, termination_evidence: { verified: true } };
    throw Error("unexpected method");
  } };
  const runtime = { supervisor, installed: { lock_identity: "a".repeat(64), slice_identity: "b".repeat(64) }, manifest: { permission_policy: {} } };
  try {
    const result = await runAuxiliary({ runtime, program: "check", payload: { check_id: "unit" }, cwd: root, taskId: "task", pause: async () => {} });
    assert.equal(result.exitCode, 0);
    assert.equal(result.terminationConfirmed, true);
    assert.equal(result.stdout, "2 passed in 0.10s\n");
    assert.equal(calls.filter(method => method === "start").length, 1);
    assert.equal(manager.hasRunning(), false);
  } finally { await manager.dispose(); globalThis[key] = previous; }
});

test("known auxiliary pre-spawn failure aborts its reservation and retires the consumed failed mirror", async () => {
  const root = mkdtempSync(join(tmpdir(), "auxiliary-failed-")), manager = new AgentManager(undefined, 1), calls = [];
  const key = Symbol.for("agentcfg.pi.managed.v1"), previous = globalThis[key];
  globalThis[key] = { manager, pi: {}, getContext: () => ({ cwd: root }) };
  let stopped = false;
  const runtime = { installed: { lock_identity: "a".repeat(64), slice_identity: "b".repeat(64) }, manifest: { permission_policy: {} },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method) {
      calls.push(method);
      if (method === "workspace_identity") return { workspace_key: "a".repeat(64), worktree_path: root };
      if (method === "workspace_snapshot") return { snapshot_digest: "b".repeat(64) };
      if (method === "allocate") return { lease_id: "lease" };
      if (method === "start") throw Error("CHECK_BINDING_REQUIRED");
      if (method === "abort_allocation") { stopped = true; return {}; }
      if (method === "inspect" || method === "reconcile") return { lease_id: "lease", state: stopped ? "failed" : "allocating", protected: !stopped, termination_evidence: stopped ? { verified: true } : null };
      throw Error("unexpected method");
    } } };
  try {
    await assert.rejects(runAuxiliary({ runtime, program: "check", payload: { check_id: "unit" }, cwd: root, taskId: "task" }), /CHECK_BINDING_REQUIRED/);
    assert.equal(stopped, true); assert.equal(manager.hasRunning(), false); assert.deepEqual(manager.listAgents(), []);
    assert.equal(calls.filter(method => method === "start").length, 1);
  } finally { await manager.dispose(); globalThis[key] = previous; }
});
