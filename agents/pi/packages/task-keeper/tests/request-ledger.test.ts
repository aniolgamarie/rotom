import assert from "node:assert/strict";
import { test } from "node:test";
import { RequestLedger } from "../src/store/request-ledger.ts";
import { fixture } from "../../../runtime/tests/fixtures.ts";
import { digest } from "@agentcfg/pi-runtime/managed-types";

function setup(limits = {}) {
  const { store } = fixture();
  const state = { valid: true, now: Date.parse("2026-09-16T00:00:00Z") };
  const options = { store, task_id: "task", budget_scope_id: "original-budget",
    limits: { model_requests: 2, model_turns: 2, deadline: "2026-09-16T01:00:00Z", ...limits }, now: () => state.now,
    verify: request => ({ valid: state.valid, route_id: request.route_id, grant_digest: request.grant_digest, bounds_certified: true }) };
  const request = { task_id: "task", attempt_id: "attempt", request_id: "one", reason: "initial", turn_id: "turn",
    route_id: "direct", grant_digest: "a".repeat(64), payload_digest: digest({ prompt: "fixture" }), reserved_input_tokens: 100, reserved_output_tokens: 50, reserved_cost: "0.10" };
  return { ledger: new RequestLedger(options), options, state, request };
}

test("initial, retry, compaction and helper reservations share the same atomic task budget", async () => {
  const f = setup();
  const first = await f.ledger.reserve(f.request);
  assert.deepEqual(await f.ledger.reserve(f.request), first);
  await f.ledger.mark_sent("one");
  await f.ledger.reserve({ ...f.request, request_id: "two", reason: "retry" });
  for (const reason of ["compaction", "handoff", "schema-repair", "second-view", "helper", "proxy"]) {
    await assert.rejects(f.ledger.reserve({ ...f.request, request_id: reason, reason }), /BUDGET_EXHAUSTED/);
  }
  assert.equal((await f.ledger.summary()).requests_used, 2);
  assert.equal((await f.ledger.summary()).turns_used, 1);
});

test("unknown sending cannot refund or resend; only reserved and proven never sent can refund", async () => {
  const f = setup();
  await f.ledger.reserve(f.request);
  await f.ledger.mark_sent("one");
  await f.ledger.mark_unknown("one");
  await assert.rejects(f.ledger.mark_sent("one"), /REQUEST_ALREADY_SENT_OR_UNKNOWN/);
  await assert.rejects(f.ledger.settle("one", { usage_id: null, input_tokens: 0, output_tokens: 0, cost: "0", never_sent: true }), /REFUND_UNPROVEN/);
  await f.ledger.reserve({ ...f.request, request_id: "not-sent" });
  await f.ledger.settle("not-sent", { usage_id: null, input_tokens: 0, output_tokens: 0, cost: "0", never_sent: true });
  assert.equal((await f.ledger.summary()).requests_used, 1);
  assert.equal((await f.ledger.summary()).unknown_requests, 1);
});

test("hard token/cost limits require upper bounds; missing provider cost remains null", async () => {
  const f = setup({ token_limit: 200, cost_limit: "0.15" });
  await assert.rejects(f.ledger.reserve({ ...f.request, reserved_cost: null }), /UNBOUNDED_REQUEST/);
  await f.ledger.reserve(f.request);
  await f.ledger.mark_sent("one");
  const settled = await f.ledger.settle("one", { usage_id: "usage", input_tokens: 10, output_tokens: 20, cost: null });
  assert.equal(settled.settled_usage.cost, null);
  assert.equal((await f.ledger.summary()).tokens_used, 30);
  await assert.rejects(f.ledger.reserve({ ...f.request, request_id: "next" }), /BUDGET_EXHAUSTED/);
});

test("new attempt or group cannot reset a task; grant/deadline recheck happens immediately before send", async () => {
  const f = setup({ model_requests: 1 });
  await f.ledger.reserve(f.request);
  f.state.valid = false;
  await assert.rejects(f.ledger.mark_sent("one"), /GRANT_STALE/);
  f.state.valid = true;
  await assert.rejects(f.ledger.reserve({ ...f.request, request_id: "resume", attempt_id: "fresh-attempt" }), /BUDGET_EXHAUSTED/);
  const changed = new RequestLedger({ ...f.options, budget_scope_id: "new-statistical-group" });
  await assert.rejects(changed.summary(), /BUDGET_SCOPE_MISMATCH/);
  f.state.now = Date.parse("2026-09-16T02:00:00Z");
  await assert.rejects(f.ledger.mark_sent("one"), /DEADLINE_EXCEEDED/);
});

test("every actual direct/proxy/helper/retry send is metered and payload cannot change after reservation", async () => {
  const { MeteredTransport } = await import("../../../runtime/metered-transport.ts");
  const f = setup({ model_requests: 6 });
  const sent = [];
  const transport = new MeteredTransport({ ledger: f.ledger, send: async (payload, context) => {
    sent.push(context);
    return { value: "result", usage: { usage_id: context.request_id, input_tokens: 5, output_tokens: 5, cost: null } };
  } });
  const reasons = ["initial", "retry", "compaction", "schema-repair", "second-view", "helper"];
  for (const reason of reasons) {
    assert.equal(await transport.request({ ...f.request, request_id: reason, reason, route_id: reason === "helper" ? "proxy" : "direct" }, { prompt: "fixture" }), "result");
  }
  assert.equal(sent.length, 6);
  assert.ok(sent.every(context => context.retries === 0));
  assert.equal((await f.ledger.summary()).requests_used, sent.length);
  await assert.rejects(transport.request({ ...f.request, request_id: "extra" }, { prompt: "changed" }), /REQUEST_IDENTITY/);
  await assert.rejects(transport.request({ ...f.request, request_id: "extra" }, { prompt: "fixture" }), /BUDGET_EXHAUSTED/);
  assert.equal(sent.length, 6);
});

test("separate SQLite connections reserve one shared task budget atomically", async () => {
  const { Store } = await import("../src/store/database.ts");
  const { TaskLedgerStore } = await import("../src/store/request-ledger-store.ts");
  const { mkdtempSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = mkdtempSync(join(tmpdir(), "request-budget-"));
  const first = new Store(root), owner = first.claimOwner("scope", "token"), second = new Store(root);
  const f = setup();
  const options = { ...f.options, limits: { ...f.options.limits, model_requests: 1 } };
  const a = new RequestLedger({ ...options, store: new TaskLedgerStore(first, owner, "task") });
  const b = new RequestLedger({ ...options, store: new TaskLedgerStore(second, owner, "task") });
  try {
    const results = await Promise.allSettled([a.reserve(f.request), b.reserve({ ...f.request, request_id: "other" })]);
    assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
    assert.match(results.find(result => result.status === "rejected").reason.message, /BUDGET_EXHAUSTED/);
    const task = first.get("agentcfg-request-ledger-v1", "task");
    assert.equal(Object.values(task.state.request_budgets)[0].requests_used, 1);
    first.revokeOwner(owner);
    await assert.rejects(a.mark_sent("one"), /CONTROL_REVOKED/);
  } finally { first.close(); second.close(); }
});
