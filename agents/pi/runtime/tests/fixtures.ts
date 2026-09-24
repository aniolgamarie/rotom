import assert from "node:assert/strict";
import { ManagedBridge } from "../managed-bridge.ts";
import { clone } from "../managed-types.ts";

const hash = char => char.repeat(64);
export function descriptor() {
  return { protocol_version: 1, request_id: "request-one", instance_id: "instance", manager_activation_id: "manager", owner_nonce: "private-fixture-nonce",
    task_id: "task", step_id: "step", attempt_id: "persisted-attempt", continuation_of: null, budget_scope_id: "task-budget",
    role_id: "task-keeper-reader", role_digest: hash("a"), runtime_digest: hash("b"), policy_digest: hash("c"),
    candidate_id: "candidate", snapshot_digest: hash("d"), cwd: "/fixture/candidate", source_cwd: "/fixture/source",
    allowed_tools: ["tk_read"], read_roots: ["project"], write_roots: [], inherited_denials: [], context_mode: "fresh", nested: false, executor: "managed-process",
    provider_id: "fixture", model_id: "selected", model_digest: hash("e"), route_id: "direct", thinking: "medium",
    request_ceiling: 3, turn_ceiling: 3, deadline: "2026-09-16T01:00:00Z", result_schema_digest: hash("f"), allowed_artifact_ids: ["final"],
    workspace_write_lease_ids: [], workspace_identity_digest: hash("a"), grant_generation: 1, allocation_id: "allocation" };
}
export function fixture() {
  const owner = { instance_id: "instance", manager_activation_id: "manager", owner_nonce: "private-fixture-nonce" };
  let state = {}, tail = Promise.resolve();
  const store = {
    transaction(fn) {
      const operation = tail.then(async () => { const next = clone(state); const result = await fn(next); state = next; return result; });
      tail = operation.catch(() => {});
      return operation;
    },
    snapshot: () => clone(state),
  };
  const calls = [], environment = { listeners: 1, generation: 1, time: Date.parse("2026-09-16T00:00:00Z"), snapshot: hash("d"), terminated: true, nonempty: true };
  const executor = {
    async dispatch(value, run) {
      assert.equal(Object.values(store.snapshot().runs)[0].state, "starting");
      calls.push(["dispatch", clone(value)]);
      return { attempt_id: value.attempt_id, lease_id: "lease" };
    },
    async cancel(...args) { calls.push(["cancel", ...args]); },
    async verify_result(leaseId, artifactDigest) {
      return { lease_id: leaseId, termination_confirmed: environment.terminated, external_work_empty: true,
        artifact_digest: artifactDigest, artifact_nonempty: environment.nonempty, candidate_digest: environment.snapshot };
    },
    async gc(runId) { calls.push(["gc", runId]); },
  };
  const bridge = new ManagedBridge({ owner, runtime: { identity: hash("b"), slice_identity: hash("c"),
    capabilities: ["managed-process", "fresh-context", "guarded-tools", "request-metering", "durable-results", "physical-termination", "workspace-leases"] },
    store, executor, listeners: () => environment.listeners, now: () => environment.time,
    resolve: async value => ({ transport_authenticated: true, role_digest: value.role_digest, policy_digest: value.policy_digest,
      model_digest: value.model_digest, workspace_identity_digest: value.workspace_identity_digest, grant_generation: environment.generation,
      provider_id: value.provider_id, model_id: value.model_id, allowed_tools: value.allowed_tools, snapshot_digest: environment.snapshot }) });
  return { owner, bridge, environment, calls, executor, store };
}

