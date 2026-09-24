import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { UsageLedger } from "../src/usage/ledger.ts";
import { importManagedUsage } from "../src/usage/managed.ts";

test("unknown and settled managed requests import once; user reassignment never resets execution budget", () => {
  const store = new Store(mkdtempSync(join(tmpdir(), "managed-usage-")));
  try {
    store.put("managed-jobs", "task", { id: "task", goal: "fixture", workflow: "inspect", workScope: "scope", createdAt: 1 });
    const request = { request_id: "request", attempt_id: "attempt", reserved_at: 2, sent_at: 3, settled_at: null, state: "unknown", settled_usage: null };
    const record = { schema_version: 1, revision: 1, state: { request_budgets: { budget: { budget_scope_id: "budget-task", requests_used: 1, requests: { request } } } } };
    store.put("agentcfg-request-ledger-v1", "task", record);
    const descriptor = { attempt_id: "attempt", provider_id: "fixture", model_id: "model", model_digest: "a".repeat(64), role_id: "reader" };
    importManagedUsage(store, "task", descriptor); importManagedUsage(store, "task", descriptor);
    const usage = new UsageLedger(store);
    assert.equal(usage.facts("task").length, 1); assert.equal(usage.facts("task")[0].tokens.input, null);
    usage.begin({ id: "comparison", sessionId: "scope", title: "compare", comparisonGroup: "group" }, 1);
    usage.link("managed-request", "comparison", "user-reassignment");
    request.state = "settled"; request.settled_at = 4; request.settled_usage = { input_tokens: 12, output_tokens: 3, cost: null };
    store.put("agentcfg-request-ledger-v1", "task", record);
    importManagedUsage(store, "task", descriptor);
    assert.equal(usage.facts("task").length, 0); assert.equal(usage.facts("comparison")[0].tokens.input, 12);
    assert.equal(usage.facts("comparison")[0].cost.amount, null);
    assert.equal(store.get("agentcfg-request-ledger-v1", "task").state.request_budgets.budget.requests_used, 1);
    assert.equal(store.get("agentcfg-request-ledger-v1", "task").state.request_budgets.budget.budget_scope_id, "budget-task");
  } finally { store.close(); }
});
