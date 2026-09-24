import assert from "node:assert/strict";
import { test } from "node:test";
import { ManagedBridge } from "../managed-bridge.ts";
import { assertDescriptor, clone, digest } from "../managed-types.ts";

import { descriptor, fixture } from "./fixtures.ts";
const hash = char => char.repeat(64);

async function start(f, value = descriptor()) {
  const admission = await f.bridge.preflight(value);
  return f.bridge.dispatch({ descriptor: value, admission_token: admission.admission_token, idempotency_key: "once" });
}

test("closed descriptors reject unknown fields and writers without shared workspace admission", () => {
  assertDescriptor(descriptor());
  assert.throws(() => assertDescriptor({ ...descriptor(), bypassQueue: true }), /PROTOCOL_INVALID/);
  assert.throws(() => assertDescriptor({ ...descriptor(), write_roots: ["project"] }), /WORKSPACE_BUSY/);
  assert.throws(() => assertDescriptor({ ...descriptor(), inherited_denials: [{ kind: "regex", pattern: ".*" }] }), /PROTOCOL_INVALID/);
});

test("zero or multiple listeners fail before preflight or execution", async () => {
  const f = fixture();
  for (const count of [0, 2]) {
    f.environment.listeners = count;
    assert.throws(() => f.bridge.handshake({ protocol_version: 1, instance_id: "instance", request_id: "handshake" }), /MANAGER_LISTENER_CONFLICT/);
    await assert.rejects(f.bridge.preflight(descriptor()), /MANAGER_LISTENER_CONFLICT/);
  }
  assert.deepEqual(f.calls, []);
});

test("preflight sends no request; dispatch echoes the already persisted attempt", async () => {
  const f = fixture(), value = descriptor();
  const admission = await f.bridge.preflight(value);
  assert.deepEqual(f.calls, []);
  const request = { descriptor: value, admission_token: admission.admission_token, idempotency_key: "once" };
  const [first, second] = await Promise.all([f.bridge.dispatch(request), f.bridge.dispatch(request)]);
  assert.equal(first.attempt_id, "persisted-attempt");
  assert.equal(first.manager_run_id, second.manager_run_id);
  assert.equal(f.calls.filter(([kind]) => kind === "dispatch").length, 1);
  await assert.rejects(f.bridge.dispatch({ ...request, descriptor: { ...value, model_id: "different" } }), /DISPATCH_CONFLICT/);
});

test("expired or changed grant rejects old admission; owner cannot be replaced", async () => {
  const f = fixture(), value = descriptor();
  const admission = await f.bridge.preflight(value);
  f.environment.generation = 2;
  await assert.rejects(f.bridge.dispatch({ descriptor: value, admission_token: admission.admission_token, idempotency_key: "once" }), /ADMISSION_STALE/);
  f.environment.generation = 1;
  f.environment.time = Date.parse("2026-09-16T02:00:00Z");
  await assert.rejects(f.bridge.dispatch({ descriptor: value, admission_token: admission.admission_token, idempotency_key: "once" }), /ADMISSION_STALE/);
  await assert.rejects(f.bridge.preflight({ ...value, owner_nonce: "foreign" }), /OWNER_MISMATCH/);
  assert.deepEqual(f.calls, []);
});

test("lost dispatch acknowledgment is durably unknown and cannot auto resend", async () => {
  const f = fixture();
  let calls = 0;
  f.executor.dispatch = async () => { calls++; throw Error("synthetic private transport error"); };
  const first = await start(f);
  const again = await start(f);
  assert.equal(first.state, "start_unknown");
  assert.deepEqual(first, again);
  assert.equal(calls, 1);
});

test("events deduplicate, detect gaps, reject backwards sequence and cancellation is not termination", async () => {
  const f = fixture(), run = await start(f);
  const event = { task_id: "task", step_id: "step", attempt_id: "persisted-attempt", manager_run_id: run.manager_run_id,
    producer_id: "worker", sequence: 1, event_id: "one", phase: "started", request_id: null, ordinal: null, usage_id: null,
    process_identity: null, active_tool_ids: [], external_work_ids: [], candidate_digest: hash("d"), result_digest: null, termination_confirmed: false };
  assert.equal((await f.bridge.event(f.owner, event)).duplicate, false);
  assert.equal((await f.bridge.event(f.owner, event)).duplicate, true);
  assert.equal((await f.bridge.event(f.owner, { ...event, sequence: 3, event_id: "three" })).sequence_complete, false);
  await assert.rejects(f.bridge.event(f.owner, { ...event, sequence: 2, event_id: "two" }), /EVENT_ORDER/);
  assert.deepEqual(await f.bridge.cancel(f.owner, run.manager_run_id, "user-request"), { accepted: true, termination_confirmed: false });
  assert.equal((await f.bridge.inspect(f.owner, run.manager_run_id)).state, "cancel_requested");
});

async function finished(f) {
  const value = descriptor(), run = await start(f, value);
  await f.bridge.event(f.owner, { task_id: "task", step_id: "step", attempt_id: value.attempt_id, manager_run_id: run.manager_run_id,
    producer_id: "worker", sequence: 1, event_id: "finished", phase: "finished", request_id: null, ordinal: null, usage_id: null,
    process_identity: null, active_tool_ids: [], external_work_ids: [], candidate_digest: hash("d"), result_digest: hash("a"), termination_confirmed: true });
  const receipt = { receipt_id: "receipt", task_id: "task", step_id: "step", attempt_id: value.attempt_id, manager_run_id: run.manager_run_id,
    candidate_digest: hash("d"), request_digest: digest(value), runtime_digest: hash("b"), policy_digest: hash("c"), final_artifact_digest: hash("a"),
    check_results: [], requested_model: { provider_id: "fixture", model_id: "selected" }, observed_model: null,
    terminal_status: "completed", termination_confirmed: true, external_work_empty: true, sequence_complete: true };
  return { run, receipt };
}

test("get_result never consumes, GC requires consume, and tombstones preserve dispatch idempotency", async () => {
  const f = fixture(), { run, receipt } = await finished(f);
  await f.bridge.publishResult(f.owner, run.manager_run_id, receipt);
  const first = await f.bridge.get_result(f.owner, "persisted-attempt");
  assert.deepEqual(first.receipt, receipt);
  assert.equal((await f.bridge.inspect(f.owner, run.manager_run_id)).consumed, false);
  await assert.rejects(f.bridge.gc(f.owner, run.manager_run_id), /EVIDENCE_NOT_CONSUMED/);
  await f.bridge.consume(f.owner, first.receipt.receipt_id, first.receipt_digest);
  await f.bridge.consume(f.owner, first.receipt.receipt_id, first.receipt_digest);
  await f.bridge.gc(f.owner, run.manager_run_id);
  await f.bridge.gc(f.owner, run.manager_run_id);
  assert.equal(f.calls.filter(([kind]) => kind === "gc").length, 1);
  assert.equal((await start(f)).manager_run_id, run.manager_run_id);
  assert.equal(f.calls.filter(([kind]) => kind === "dispatch").length, 1);
});

test("empty final, unknown physical termination, model mismatch and changed candidate reject success", async () => {
  for (const kind of ["empty", "termination", "model", "candidate"]) {
    const f = fixture(), { run, receipt } = await finished(f);
    if (kind === "empty") f.environment.nonempty = false;
    if (kind === "termination") f.environment.terminated = false;
    if (kind === "model") receipt.observed_model = { provider_id: "fixture", model_id: "wrong" };
    if (kind === "candidate") f.environment.snapshot = hash("e");
    await assert.rejects(f.bridge.publishResult(f.owner, run.manager_run_id, receipt), /EVIDENCE_MISSING|TERMINATION_UNKNOWN|MODEL_MISMATCH|SNAPSHOT_STALE/);
    await assert.rejects(f.bridge.get_result(f.owner, "persisted-attempt"), /EVIDENCE_MISSING/);
  }
});

test("candidate changes make a previously published receipt stale", async () => {
  const f = fixture(), { run, receipt } = await finished(f);
  await f.bridge.publishResult(f.owner, run.manager_run_id, receipt);
  f.environment.snapshot = hash("e");
  await assert.rejects(f.bridge.get_result(f.owner, "persisted-attempt"), /SNAPSHOT_STALE/);
});

test("cancel after a verified final does not rewrite the terminal state", async () => {
  const f = fixture(), { run, receipt } = await finished(f);
  await f.bridge.publishResult(f.owner, run.manager_run_id, receipt);
  assert.deepEqual(await f.bridge.cancel(f.owner, run.manager_run_id, "late-user-request"), { accepted: true, termination_confirmed: true });
  assert.equal((await f.bridge.inspect(f.owner, run.manager_run_id)).state, "completed");
  assert.equal(f.calls.filter(([kind]) => kind === "cancel").length, 0);
  f.environment.nonempty = false;
  await assert.rejects(f.bridge.get_result(f.owner, "persisted-attempt"), /EVIDENCE_MISSING/);
});

test("reconcile asks the supervisor for old records without granting old control rights", async () => {
  const f = fixture();
  const calls = [];
  f.executor.reconcile = async (lease, principal) => {
    calls.push([lease, principal]);
    return { lease_id: lease, protected: true, process_status: "unknown" };
  };
  const result = await f.bridge.reconcile(f.owner, "old-lease");
  assert.equal(result.protected, true);
  assert.deepEqual(calls, [["old-lease", { instance_id: "instance" }]]);
  assert.deepEqual(f.calls, []);
  await assert.rejects(f.bridge.reconcile({ ...f.owner, owner_nonce: "old-nonce" }, "old-lease"), /OWNER_MISMATCH/);
});

test("writer receipts require a supervised mutation chain from the initial to final candidate", async () => {
  for (const verified of [true, false]) {
    const f = fixture();
    const value = { ...descriptor(), role_id: "task-keeper-writer", write_roots: ["project"], workspace_write_lease_ids: ["writer"] };
    const run = await start(f, value);
    f.environment.snapshot = hash("e");
    f.executor.verify_result = async (leaseId, artifactDigest) => ({ lease_id: leaseId, termination_confirmed: true, external_work_empty: true,
      artifact_digest: artifactDigest, artifact_nonempty: true, candidate_digest: hash("e"), initial_candidate_digest: hash("d"), mutation_chain_verified: verified });
    await f.bridge.event(f.owner, { task_id: "task", step_id: "step", attempt_id: value.attempt_id, manager_run_id: run.manager_run_id,
      producer_id: "worker", sequence: 1, event_id: "writer-finished", phase: "finished", request_id: null, ordinal: null, usage_id: null,
      process_identity: null, active_tool_ids: [], external_work_ids: [], candidate_digest: hash("e"), result_digest: hash("a"), termination_confirmed: true });
    const receipt = { receipt_id: "writer-receipt", task_id: "task", step_id: "step", attempt_id: value.attempt_id, manager_run_id: run.manager_run_id,
      candidate_digest: hash("e"), request_digest: digest(value), runtime_digest: hash("b"), policy_digest: hash("c"), final_artifact_digest: hash("a"),
      check_results: [], requested_model: { provider_id: "fixture", model_id: "selected" }, observed_model: null,
      terminal_status: "completed", termination_confirmed: true, external_work_empty: true, sequence_complete: true };
    if (verified) {
      await f.bridge.publishResult(f.owner, run.manager_run_id, receipt);
      assert.equal((await f.bridge.get_result(f.owner, value.attempt_id)).receipt.candidate_digest, hash("e"));
    } else await assert.rejects(f.bridge.publishResult(f.owner, run.manager_run_id, receipt), /SNAPSHOT_STALE/);
  }
});
