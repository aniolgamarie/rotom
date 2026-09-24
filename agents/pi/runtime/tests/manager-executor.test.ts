import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { ManagerExecutor } from "../manager-executor.ts";
import { fixture, descriptor } from "./fixtures.ts";
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

test("bridge executor uses the existing manager queue and never spawns queued allocations", async () => {
  const f = fixture(), cwd = mkdtempSync(join(tmpdir(), "manager-executor-"));
  const manager = new AgentManager(undefined, 1), starts = [], finishes = new Map();
  const backend = {
    async allocate(value) { return { lease_id: "lease-" + value.attempt_id, attempt_id: value.attempt_id }; },
    async recheck() {},
    async execute(value) { starts.push(value.attempt_id); return new Promise(resolve => finishes.set(value.attempt_id, resolve)); },
    async cancel() { return undefined; },
  };
  const executor = new ManagerExecutor({ manager, backend, store: f.store, pi: {}, context: () => ({ cwd }) });
  f.bridge.executor = executor;
  async function submit(attempt) {
    const value = { ...descriptor(), cwd, attempt_id: attempt };
    const admission = await f.bridge.preflight(value);
    return f.bridge.dispatch({ descriptor: value, admission_token: admission.admission_token, idempotency_key: attempt });
  }
  const one = await submit("one"), two = await submit("two");
  await flush();
  assert.equal(one.state, "running");
  assert.equal(two.state, "queued");
  assert.deepEqual(starts, ["one"]);
  assert.ok(manager.getRecord(one.manager_run_id));
  finishes.get("one")({ terminal_status: "completed", response_text: "fixture", termination_confirmed: true, external_work_empty: true });
  await flush();
  assert.deepEqual(starts, ["one", "two"]);
  await executor.gc(one.manager_run_id);
  assert.equal(manager.getRecord(one.manager_run_id), undefined);
  assert.ok(manager.getRecord(two.manager_run_id));
  await manager.dispose();
});

test("reconcile frees a stuck logical slot only after verified physical reclamation", async () => {
  const f = fixture(), cwd = mkdtempSync(join(tmpdir(), "manager-reconcile-")), manager = new AgentManager(undefined, 1);
  let proof = { protected: true, termination_evidence: null };
  const backend = { async allocate(value) { return { lease_id: "lease", attempt_id: value.attempt_id }; }, async recheck() {},
    async execute() { throw Error("malformed worker evidence"); }, async cancel() {}, async reconcile() { return proof; } };
  const executor = new ManagerExecutor({ manager, backend, store: f.store, pi: {}, context: () => ({ cwd }) });
  f.bridge.executor = executor;
  const value = { ...descriptor(), cwd }, admission = await f.bridge.preflight(value);
  const run = await f.bridge.dispatch({ descriptor: value, admission_token: admission.admission_token, idempotency_key: "once" });
  await flush();
  assert.equal(manager.getRecord(run.manager_run_id).status, "running");
  await f.bridge.reconcile(f.owner, "lease");
  assert.equal(manager.getRecord(run.manager_run_id).status, "running");
  proof = { protected: false, termination_evidence: { verified: true } };
  await f.bridge.reconcile(f.owner, "lease");
  assert.equal(manager.getRecord(run.manager_run_id).status, "error");
  await assert.rejects(f.bridge.get_result(f.owner, value.attempt_id), /EVIDENCE_MISSING/);
  await manager.dispose();
});
