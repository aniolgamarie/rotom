import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { registerManagedRpc } from "@agentcfg/pi-runtime/managed-rpc";
import { digest } from "@agentcfg/pi-runtime/managed-types";
import { descriptor, fixture } from "../../../runtime/tests/fixtures.ts";

function setup() {
  const f = fixture(), emitter = new EventEmitter(), state = { dropDispatchReply: false, dropId: null };
  const events = { emit(channel, value) {
    if (channel.endsWith(":dispatch") && state.dropDispatchReply) state.dropId = value.request_id;
    if (channel.endsWith(":reply:" + state.dropId)) return;
    emitter.emit(channel, value);
  }, on(channel, fn) { emitter.on(channel, fn); return () => emitter.off(channel, fn); } };
  const store = new Store(mkdtempSync(join(tmpdir(), "tk-adapter-"))), owner = store.claimOwner("fixture", "token");
  const adapter = new SubagentsAdapter({ events }, store, {}, owner, { owner: { ...f.owner, role: "manager" }, installed: { runtime_identity: "b".repeat(64) }, managedBackend: f.executor }, { timeout: 20 });
  const off = registerManagedRpc(events, f.bridge);
  adapter.journal.createTask({ schema_version: 1, task_id: "task", goal: "fixture", workflow: "inspect", candidate_id: "candidate", budget_scope_id: "task-budget",
    role_bindings: { reader: "task_keeper_reader", writer: "task_keeper_writer", reviewer: "task_keeper_reviewer" }, policy_digest: "c".repeat(64),
    check_ids: [], required_review: true, second_view: null, state: "queued" });
  const value = descriptor();
  for (const key of ["attempt_id", "task_id", "step_id", "continuation_of", "budget_scope_id"]) delete value[key];
  value.allocation_id = "lease";
  const prepared = adapter.journal.allocate({ task_id: "task", step_id: "step", continuation_of: null, idempotency_key: "once", descriptor: value });
  return { ...f, managerOwner: f.owner, protocolStore: f.store, adapter, store, owner, prepared, state, off };
}

test("Task Keeper new adapter persists admission and exact attempt before one dispatch", async () => {
  const f = setup();
  try {
    await f.adapter.preflight(f.prepared.attempt.attempt_id);
    assert.equal(f.calls.length, 0);
    const run = await f.adapter.dispatch(f.prepared.attempt.attempt_id);
    assert.equal(run.attempt_id, f.prepared.attempt.attempt_id);
    assert.equal(run.state, "running");
    assert.equal(f.calls.length, 1);
    assert.deepEqual(await f.adapter.dispatch(run.attempt_id), run);
    assert.equal(f.calls.length, 1);
    assert.equal((await f.adapter.cancel(run.attempt_id, "user-stop")).termination_confirmed, false);
  } finally { f.off(); f.store.close(); }
});

test("lost dispatch reply remains start_unknown in task database without automatic resend", async () => {
  const f = setup();
  try {
    const id = f.prepared.attempt.attempt_id;
    await f.adapter.preflight(id);
    f.state.dropDispatchReply = true;
    assert.equal((await f.adapter.dispatch(id)).state, "start_unknown");
    f.state.dropDispatchReply = false;
    assert.equal((await f.adapter.dispatch(id)).state, "start_unknown");
    assert.equal(f.calls.length, 1);
  } finally { f.off(); f.store.close(); }
});

test("revoked owner and changed manager cannot reuse saved admission", async () => {
  const f = setup();
  try {
    const id = f.prepared.attempt.attempt_id;
    await f.adapter.preflight(id);
    f.bridge.owner.owner_nonce = "different-manager";
    await assert.rejects(f.adapter.dispatch(id), /MANAGER_IDENTITY_CONFLICT/);
    assert.equal(f.calls.length, 0);
    f.store.revokeOwner(f.owner);
    await assert.rejects(f.adapter.preflight(id), /CONTROL_REVOKED/);
  } finally { f.off(); f.store.close(); }
});

test("managed parent helpers are denied before ordinary transport observers and send", async () => {
  const { activeManagedParentGuard } = await import("../src/adapters/subagents.ts");
  const { installHttpTransport } = await import("../src/adapters/http-transport.ts");
  const key = Symbol.for("agentcfg.pi.runtime.v1");
  const saved = globalThis[key], original = globalThis.fetch;
  let sent = 0, observed = 0, denied = 0;
  globalThis.fetch = async () => { sent++; return new Response("unexpected"); };
  globalThis[key] = { managedRequestScope: { getStore: () => ({ recordDenial: () => { denied++; } }) } };
  const transport = installHttpTransport(() => { observed++; return null; }, { priorGuard: activeManagedParentGuard }, false, false);
  try {
    for (const method of ["POST", "GET"]) await assert.rejects(transport.fetch("https://fixture.invalid/helper", { method }), /UNBUDGETED_PARENT_HELPER_DENIED/);
    assert.equal(sent, 0); assert.equal(observed, 0); assert.equal(denied, 2);
  } finally { transport.dispose(); globalThis[key] = saved; globalThis.fetch = original; }
});


test("lost dispatch acknowledgment adopts only a fully verified receipt for the original attempt", async () => {
  const f = setup();
  try {
    const id = f.prepared.attempt.attempt_id, value = f.prepared.descriptor;
    await f.adapter.preflight(id); f.state.dropDispatchReply = true;
    await f.adapter.dispatch(id); f.state.dropDispatchReply = false;
    const run = Object.values(f.protocolStore.snapshot().runs)[0];
    const receipt = { receipt_id: "receipt", task_id: "task", step_id: "step", attempt_id: id, manager_run_id: run.manager_run_id,
      candidate_digest: value.snapshot_digest, request_digest: digest(value), runtime_digest: value.runtime_digest, policy_digest: value.policy_digest,
      final_artifact_digest: "a".repeat(64), check_results: [], requested_model: { provider_id: value.provider_id, model_id: value.model_id }, observed_model: null,
      terminal_status: "completed", termination_confirmed: true, external_work_empty: true, sequence_complete: true };
    await f.bridge.event(f.managerOwner, { task_id: "task", step_id: "step", attempt_id: id, manager_run_id: run.manager_run_id,
      producer_id: "worker", sequence: 1, event_id: "finished", phase: "finished", request_id: null, ordinal: null, usage_id: null,
      process_identity: null, active_tool_ids: [], external_work_ids: [], candidate_digest: value.snapshot_digest, result_digest: "a".repeat(64), termination_confirmed: true });
    await f.bridge.publishResult(f.managerOwner, run.manager_run_id, receipt);
    f.environment.terminated = false;
    await assert.rejects(f.adapter.get_result(id), /TERMINATION_UNKNOWN/);
    assert.equal(f.adapter.journal.read(id).attempt.manager_run_id, null);
    f.environment.terminated = true;
    assert.equal((await f.adapter.inspect(id)).state, "completed");
    assert.equal(f.adapter.journal.read(id).attempt.manager_run_id, run.manager_run_id);
    assert.equal(f.calls.filter(([kind]) => kind === "dispatch").length, 1);
  } finally { f.off(); f.store.close(); }
});
