import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { ExternalBridge } from "../external-executor.ts";
import { fixture } from "./fixtures.ts";
import { clone, digest } from "../managed-types.ts";

function setup() {
  const base = fixture(), cwd = mkdtempSync(join(tmpdir(), "external-queue-")), manager = new AgentManager(undefined, 1);
  const calls = [], requests = new Map(), states = new Map(), waiters = [];
  const owner = { ...base.owner, role: "manager" }, policy = { schema_version: 1, default: "deny", rules: [] };
  const runtime = { owner, installed: { runtime_identity: "c".repeat(64) }, manifest: { permission_policy: policy }, managedRequestScope: { getStore: () => null },
    supervisor: { async call(method, args) {
      calls.push([method, args]);
      if (method === "handshake") return { ...owner, runtime_identity: runtime.installed.runtime_identity };
      if (method === "delegate_prepare") {
        const value = { ...Object.fromEntries(["backend", "mode", "preset", "cwd", "timeout_seconds"].map(key => [key, args[key]])),
          schema_version: 2, run_id: "run-" + args.idempotency_key, lease_id: "lease-" + args.idempotency_key, requested_model: args.model,
          instance_id: owner.instance_id, owner_nonce: owner.owner_nonce, runtime_identity: runtime.installed.runtime_identity,
          execution_boundary: args.backend === "codex" ? "native-sandbox" : "agentcfg-tools", execution_policy_digest: "9".repeat(64),
          execution_mode: "delegate-readonly", policy_digest: digest(policy), candidate_digest: "a".repeat(64) };
        requests.set(value.run_id, value); states.set(value.run_id, "prepared"); return clone(value);
      }
      if (method === "delegate_start") { states.set(args.run_id, "running"); return { state: "running" }; }
      if (method === "delegate_status") return { state: states.get(args.run_id) };
      if (method === "delegate_cancel") { states.set(args.run_id, "cancel_requested"); return { accepted: true, termination_confirmed: false }; }
      if (method === "reconcile") {
        const state = states.get(args.lease_id.replace("lease-", "run-"));
        return { lease_id: args.lease_id, protected: state !== "completed", termination_evidence: state === "completed" ? { verified: true } : null };
      }
      if (method === "delegate_result") {
        const value = requests.get(args.run_id), receipt = { ...value, terminal_status: "completed", backend_resume_token: null,
          event_sequence_complete: true, final_artifact_id: "final", final_artifact_digest: "b".repeat(64), process_terminated: true,
          resources_reclaimed: true, usage: { input_tokens: null, output_tokens: null, cost: null }, feedback_dispositions: [], observed_model: null };
        return { receipt, receipt_digest: digest(receipt), verification: "verified-execution" };
      }
      throw Error("unexpected method");
    } } };
  const bridge = new ExternalBridge({ runtime, manager, store: base.store, pi: {}, getContext: () => ({ cwd }), pause: () => new Promise(resolve => waiters.push(resolve)) });
  const input = { backend: "pi", mode: "review", preset: "review", task: "fixture", cwd, model: { provider_id: "fixture", model_id: "model" }, timeout_seconds: 30 };
  const envelope = id => ({ request_id: id, idempotency_key: id, instance_id: owner.instance_id, policy_digest: digest(policy), request_digest: digest(input), backend_request: clone(input) });
  const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
  return { ...base, calls, states, waiters, runtime, manager, bridge, envelope, flush };
}

test("external runs share one existing manager capacity; repeated keys never allocate or start twice", async () => {
  const f = setup();
  const one = await f.bridge.submit_delegate(f.envelope("one")), two = await f.bridge.submit_delegate(f.envelope("two"));
  await f.flush();
  assert.equal(two.state, "queued");
  assert.equal(f.calls.filter(([kind]) => kind === "delegate_start").length, 1);
  assert.equal((await f.bridge.submit_delegate(f.envelope("one"))).run_id, one.run_id);
  assert.equal(f.calls.filter(([kind]) => kind === "delegate_prepare").length, 2);
  await f.bridge.cancel_delegate(f.owner, one.run_id); await f.flush();
  assert.equal(f.manager.getRecord(one.dispatch_id).status, "running");
  f.states.set(one.run_id, "completed"); f.waiters.splice(0).forEach(resolve => resolve()); await f.flush();
  assert.equal(f.manager.getRecord(one.dispatch_id).status, "completed");
  assert.equal(f.calls.filter(([kind]) => kind === "delegate_start").length, 2);
  assert.equal((await f.bridge.get_delegate_result(f.owner, one.run_id)).verification, "verified-execution");
  f.states.set(two.run_id, "completed"); f.waiters.splice(0).forEach(resolve => resolve()); await f.flush();
  await f.bridge.close(); await f.manager.dispose();
});

test("managed scope and model tool write cannot reach supervisor admission", async () => {
  const f = setup();
  f.runtime.managedRequestScope.getStore = () => ({ task_id: "managed" });
  await assert.rejects(f.bridge.submit_delegate(f.envelope("managed")), /UNMETERED_EXTERNAL_DELEGATE/);
  f.runtime.managedRequestScope.getStore = () => null;
  const request = f.envelope("write"); request.backend_request.mode = "implement"; request.request_digest = digest(request.backend_request);
  await assert.rejects(f.bridge.submit_delegate(request), /DELEGATE_REQUEST_INVALID/);
  assert.equal(f.calls.some(([kind]) => kind === "delegate_prepare"), false);
  await f.bridge.close(); await f.manager.dispose();
});

test("explicit batch is idempotent and keeps partial results separate from complete success", async () => {
  const f = setup(), items = [f.envelope("one"), f.envelope("two")];
  const batch = await f.bridge.submit_batch(f.owner, "batch", items);
  await f.flush();
  assert.equal(batch.dispatch_ids.length, 2);
  assert.deepEqual((await f.bridge.submit_batch(f.owner, "batch", items)).dispatch_ids, batch.dispatch_ids);
  assert.equal(f.calls.filter(([kind]) => kind === "delegate_prepare").length, 2);
  await assert.rejects(f.bridge.submit_batch(f.owner, "batch", [items[0]]), /DELEGATE_BATCH_CONFLICT/);
  f.states.set("run-one", "completed"); f.waiters.splice(0).forEach(resolve => resolve()); await f.flush();
  assert.equal((await f.bridge.get_batch(f.owner, "batch")).state, "running");
  f.states.set("run-two", "completed"); f.waiters.splice(0).forEach(resolve => resolve()); await f.flush();
  const final = await f.bridge.get_batch(f.owner, "batch");
  assert.equal(final.state, "completed"); assert.equal(final.result_refs.length, 2);
  await f.store.transaction(state => { Object.values(state.delegates).find(row => row.request?.run_id === "run-two").state = "canceled"; });
  assert.equal((await f.bridge.get_batch(f.owner, "batch")).state, "partial");
  const invalid = f.envelope("invalid"); invalid.backend_request.mode = "implement"; invalid.request_digest = digest(invalid.backend_request);
  assert.equal((await f.bridge.submit_batch(f.owner, "partial", [invalid])).state, "partial");
  assert.equal((await f.bridge.get_batch(f.owner, "partial")).state, "partial");
  await f.bridge.close(); await f.manager.dispose();
});

test("result refresh is followed by a fresh physical proof", async () => {
  const request = { schema_version: 2, lease_id: "lease", execution_mode: "delegate-readonly", candidate_digest: "a".repeat(64), requested_model: { provider_id: "fixture", model_id: "model" } };
  const receipt = { ...request, terminal_status: "completed", backend_resume_token: null, event_sequence_complete: true,
    final_artifact_id: "artifact", final_artifact_digest: "b".repeat(64), process_terminated: true, resources_reclaimed: true,
    usage: { input_tokens: null, output_tokens: null, cost: null }, feedback_dispositions: [], observed_model: null };
  const bridge = Object.create(ExternalBridge.prototype), calls = [];
  bridge.find = async () => ({ request, dispatch_id: "dispatch" });
  bridge.manager = { getRecord: () => null };
  bridge.supervisor = { async call(method) {
    calls.push(method);
    if (method === "delegate_result") return { receipt, receipt_digest: digest(receipt), verification: "verified-execution" };
    return { lease_id: "lease", protected: !calls.includes("delegate_result"), termination_evidence: { verified: calls.includes("delegate_result") } };
  } };
  assert.equal((await bridge.get_delegate_result({}, "run")).verification, "verified-execution");
  assert.deepEqual(calls, ["delegate_result", "reconcile"]);
});

test("external execution refreshes its result before taking terminal physical evidence", async () => {
  const f = setup(), original = f.runtime.supervisor.call.bind(f.runtime.supervisor), refreshed = new Set();
  f.runtime.supervisor.call = async (method, args) => {
    if (method === "delegate_result") refreshed.add(args.run_id);
    if (method === "reconcile") {
      const ready = refreshed.has(args.lease_id.replace("lease-", "run-"));
      return { lease_id: args.lease_id, protected: !ready, termination_evidence: ready ? { verified: true } : null };
    }
    return original(method, args);
  };
  const submitted = await f.bridge.submit_delegate(f.envelope("fresh-proof"));
  await f.flush();
  f.states.set(submitted.run_id, "completed"); f.waiters.splice(0).forEach(resolve => resolve()); await f.flush();
  const row = await f.bridge.find(f.owner, submitted.run_id);
  assert.equal(row.state, "completed"); assert.equal(row.result.verification, "verified-execution");
  assert.ok(refreshed.has(submitted.run_id));
  await f.bridge.close(); await f.manager.dispose();
});
