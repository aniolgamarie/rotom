import assert from "node:assert/strict";
import { test } from "node:test";
import { ManagedHttpTransport } from "../managed-http-transport.ts";
import { RequestLedger } from "../../packages/task-keeper/src/store/request-ledger.ts";
import { descriptor, fixture } from "./fixtures.ts";
import { digest } from "../managed-types.ts";

function setup({ broken = false, proxy = false, mismatch = false, usage = true } = {}) {
  const f = fixture(), value = descriptor(), calls = [];
  const ledger = new RequestLedger({ store: f.store, task_id: value.task_id, budget_scope_id: value.budget_scope_id,
    limits: { model_requests: 2, model_turns: 2, deadline: value.deadline }, now: () => f.environment.time,
    verify: request => ({ valid: true, route_id: request.route_id, grant_digest: request.grant_digest }) });
  const route = { id: "direct", type: proxy ? "proxy" : "direct", base_url: "https://fixture.invalid/v1", proxy_url: proxy ? "http://proxy.invalid:8080" : null };
  const transport = new ManagedHttpTransport({ descriptor: value, route, ledger, fetchRoute: async (url, options, binding) => {
    calls.push({ url, options, binding });
    const event = { model: mismatch ? "unexpected" : "selected", choices: [], ...(usage ? { usage: { prompt_tokens: 5, completion_tokens: 2 } } : {}) };
    return new Response("data: " + JSON.stringify(event) + "\n\n" + (broken ? "" : "data: [DONE]\n\n"), { headers: { "content-type": "text/event-stream" } });
  } });
  const model = { provider: value.provider_id, id: value.model_id, api: "openai-completions", baseUrl: route.base_url };
  const runtime = { stream: () => {}, streamSimple(m, context, options) {
    calls.push({ sdkOptions: options });
    return options.fetch(route.base_url + "/chat/completions", { method: "POST", headers: { authorization: "Bearer synthetic-secret" },
      body: JSON.stringify({ model: m.id, stream: true, messages: context.messages }) });
  } };
  return { ...f, value, model, route, ledger, transport, runtime, calls };
}

test("actual HTTP boundary meters direct and proxy routes, forces zero retry and preserves unknown cost", async () => {
  for (const proxy of [false, true]) {
    const f = setup({ proxy });
    const binding = await f.transport.bind(f.runtime, { authorize: async () => {} });
    const response = await f.runtime.streamSimple(f.model, { messages: [] }, { maxRetries: 4, fetch: () => { throw Error("bypass"); } });
    await response.text(); await binding.finish(); await binding.close();
    assert.equal(f.calls[0].sdkOptions.maxRetries, 0);
    assert.equal(f.calls[1].options.redirect, "error");
    assert.equal(f.calls[1].binding.type, proxy ? "proxy" : "direct");
    const budget = Object.values(f.store.snapshot().request_budgets)[0], request = Object.values(budget.requests)[0];
    assert.equal(budget.requests_used, 1);
    assert.equal(request.state, "settled");
    assert.equal(request.settled_usage.cost, null);
    assert.equal(JSON.stringify(f.store.snapshot()).includes("synthetic-secret"), false);
    assert.deepEqual(f.transport.observed_model, { provider_id: "fixture", model_id: "selected" });
  }
});

test("early EOF and wrong observed model retain unknown reservation with no fallback request", async () => {
  for (const option of [{ broken: true }, { mismatch: true }]) {
    const f = setup(option), binding = await f.transport.bind(f.runtime, { authorize: async () => {} });
    const response = await f.runtime.streamSimple(f.model, { messages: [] });
    await assert.rejects(response.text(), /TRANSPORT_OUTCOME_UNKNOWN/);
    await assert.rejects(binding.close(), /TRANSPORT_OUTCOME_UNKNOWN/);
    const record = Object.values(Object.values(f.store.snapshot().request_budgets)[0].requests)[0];
    assert.equal(record.state, "unknown");
    assert.equal(f.calls.filter(value => value.url).length, 1);
  }
});

test("SDK cancel after receiving DONE does not convert proved completion into unknown", async () => {
  const f = setup({ usage: false }), binding = await f.transport.bind(f.runtime, { authorize: async () => {} });
  const response = await f.runtime.streamSimple(f.model, { messages: [] });
  const reader = response.body.getReader();
  await reader.read(); await reader.cancel(); await binding.close();
  const record = Object.values(Object.values(f.store.snapshot().request_budgets)[0].requests)[0];
  assert.equal(record.state, "settled");
  assert.equal(record.settled_usage.input_tokens, null);
});

test("budget denial is recorded before transport and never becomes an implicit retry", async () => {
  const f = setup(), reports = [];
  f.ledger.limits.model_requests = 1;
  f.transport.report = async value => { reports.push(value); };
  const binding = await f.transport.bind(f.runtime, { authorize: async () => {} });
  const first = await f.runtime.streamSimple(f.model, { messages: [] });
  await first.text();
  await assert.rejects(f.runtime.streamSimple(f.model, { messages: [] }), /BUDGET_EXHAUSTED/);
  const denied = reports.find(value => value.phase === "request_denied");
  assert.equal(denied.code, "BUDGET_EXHAUSTED");
  assert.equal(denied.ordinal, null);
  assert.equal(f.calls.filter(value => value.url).length, 1);
  await binding.close();
});

test("turn ceiling records an independent denial even when the SDK absorbs the synchronous error", async () => {
  const f = setup(), reports = [];
  f.value.turn_ceiling = 1;
  f.transport.report = async value => { await Promise.resolve(); reports.push(value); };
  const binding = await f.transport.bind(f.runtime, { authorize: async () => {} });
  const response = await f.runtime.streamSimple(f.model, { messages: [] }); await response.text();
  assert.throws(() => f.runtime.streamSimple(f.model, { messages: [] }), /BUDGET_EXHAUSTED/);
  await binding.finish();
  assert.equal(f.transport.budgetExhausted, true);
  assert.equal(reports.filter(row => row.phase === "request_denied" && row.code === "BUDGET_EXHAUSTED").length, 1);
  assert.equal(f.calls.filter(row => row.url).length, 1);
  await binding.close();
});
