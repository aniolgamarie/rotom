import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { AttemptJournal, assertManagedTask } from "../src/contracts/agentcfg.ts";
import { descriptor } from "../../../runtime/tests/fixtures.ts";

function task() {
  return { schema_version: 1, task_id: "task", goal: "fixture goal", workflow: "inspect", candidate_id: "candidate", budget_scope_id: "original-budget",
    role_bindings: { reader: "task_keeper_reader", writer: "task_keeper_writer", reviewer: "task_keeper_reviewer" },
    policy_digest: "c".repeat(64), check_ids: [], required_review: true, second_view: null, state: "queued" };
}
function input() {
  const value = descriptor();
  for (const key of ["attempt_id", "task_id", "step_id", "continuation_of", "budget_scope_id"]) delete value[key];
  return { task_id: "task", step_id: "inspect", continuation_of: null, idempotency_key: "once", descriptor: value };
}

test("Task Keeper allocates and persists exact attempt identity before dispatch", () => {
  const root = mkdtempSync(join(tmpdir(), "attempt-journal-"));
  let store = new Store(root);
  const owner = store.claimOwner("fixture", "token");
  let journal = new AttemptJournal(store, owner);
  journal.createTask(task());
  const value = journal.allocate(input());
  assert.equal(value.attempt.state, "prepared");
  assert.equal(value.descriptor.attempt_id, value.attempt.attempt_id);
  assert.equal(value.descriptor.continuation_of, null);
  assert.equal(value.descriptor.budget_scope_id, "original-budget");
  assert.throws(() => journal.acknowledge(value.attempt.attempt_id, { attempt_id: "manager-changed", manager_run_id: "run", lease_id: "lease", state: "running" }), /DISPATCH_IDENTITY/);
  journal.acknowledge(value.attempt.attempt_id, { attempt_id: value.attempt.attempt_id, manager_run_id: "run", lease_id: "lease", state: "running" });
  store.close();
  store = new Store(root); journal = new AttemptJournal(store, owner);
  assert.equal(journal.allocate(input()).attempt.attempt_id, value.attempt.attempt_id);
  assert.equal(journal.read(value.attempt.attempt_id).attempt.lease_id, "lease");
  assert.throws(() => journal.allocate({ ...input(), descriptor: { ...input().descriptor, model_id: "changed" } }), /DISPATCH_CONFLICT/);
  assert.throws(() => journal.allocate({ ...input(), continuation_of: value.attempt.attempt_id, idempotency_key: "resume" }), /TERMINATION_UNKNOWN/);
  store.close();
});

test("task workflow, schema and identity overrides are closed", () => {
  assert.throws(() => assertManagedTask({ ...task(), workflow: "autonomous" }), /PROTOCOL_INVALID/);
  assert.throws(() => assertManagedTask({ ...task(), schema_version: 2 }), /PROTOCOL_INVALID/);
  assert.throws(() => assertManagedTask({ ...task(), bypassQueue: true }), /PROTOCOL_INVALID/);
  const store = new Store(mkdtempSync(join(tmpdir(), "attempt-journal-")));
  const owner = store.claimOwner("fixture", "token"), journal = new AttemptJournal(store, owner);
  journal.createTask(task());
  assert.throws(() => journal.createTask({ ...task(), budget_scope_id: "new-budget" }), /TASK_IDENTITY_CONFLICT/);
  assert.throws(() => journal.allocate({ ...input(), descriptor: { ...input().descriptor, attempt_id: "forged" } }), /PROTOCOL_INVALID/);
  store.revokeOwner(owner);
  assert.throws(() => journal.allocate(input()), /CONTROL_REVOKED/);
  store.close();
});

test("attempt identity is durable before acquiring a supervisor workspace allocation", () => {
  const store = new Store(mkdtempSync(join(tmpdir(), "attempt-journal-")));
  const owner = store.claimOwner("fixture", "token"), journal = new AttemptJournal(store, owner);
  try {
    journal.createTask(task());
    const { descriptor: template, ...identity } = input();
    const intent = journal.prepareIdentity(identity);
    assert.deepEqual(journal.prepareIdentity(identity), intent);
    assert.equal(store.list("agentcfg-attempt-intents-v1")[0].value.attempt_id, intent.attempt_id);
    // 真实工作区预留在这里发生，随后补齐 allocation_id/grant 字段。
    const prepared = journal.allocate({ ...identity, descriptor: template });
    assert.equal(prepared.attempt.attempt_id, intent.attempt_id);
    assert.equal(prepared.descriptor.attempt_id, intent.attempt_id);
  } finally { store.close(); }
});
