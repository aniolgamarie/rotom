import assert from "node:assert/strict";
import { test } from "node:test";
import { createReviewAttempt } from "../src/transport.ts";

const bind = () => ({ request_id: "1".repeat(32), operation_digest: "a".repeat(64), context_digest: "b".repeat(64), reviewer_identity: "c".repeat(64) });
const answer = (decision = "allow", reason = "authorized-in-scope") => JSON.stringify({ schema_version: 1, ...bind(), decision, reason_code: reason });
const meta = () => ({ model: "synthetic-reviewer", usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 } });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function fixture(overrides = {}) {
  let sends = 0, invocations = 0, capture;
  const cfg = {
    binding: bind(), route: { identity: "c".repeat(64), pricing_identity: "d".repeat(64), currency: "USD", provider: "synthetic-provider",
      model: "synthetic-reviewer", base_url: "https://review.invalid/v1", context_window: 32000, max_output_tokens: 1024,
      cost: { input: 1, output: 2, cacheRead: 1, cacheWrite: 1 } },
    input: { system_prompt: "synthetic instructions", user_prompt: "synthetic operation" },
    qualification: { profile: "pi-full", enabled: true, hard_policy_allowed: true, role_allows: true, requires_human: false, automatic_risk_allowed: true },
    apiKey: "synthetic-key", expectedHeaders: { authorization: "Bearer synthetic-key", accept: "application/json", "content-type": "application/json" },
    deadlineMs: Date.now() + 10000, maxDurationMs: 2000, isCurrent: () => true,
    send: async () => { sends++; return new Response("synthetic-sse"); },
    sdk: {
      normalizeContext: value => structuredClone(value),
      streamSimple(model, context, options) {
        invocations++; capture = { model, context, options };
        return (async function* () {
          const messages = [];
          if (context.systemPrompt) messages.push({ role: "system", content: context.systemPrompt });
          messages.push({ role: "user", content: context.messages[0].content });
          const body = { model: model.id, messages, stream: true, stream_options: { include_usage: true }, max_tokens: options.maxTokens, temperature: 0 };
          const response = await options.fetch(model.baseUrl + "/chat/completions", { method: "POST", body: JSON.stringify(body), headers: cfg.expectedHeaders });
          await response.text();
          if (overrides.onFetched) await overrides.onFetched(capture);
          if (overrides.raw !== false) options.onProviderStreamEvent(overrides.raw ?? meta(), model);
          yield overrides.event ?? { type: "done", message: { api: model.api, provider: model.provider, model: model.id,
            stopReason: "stop", usage: { input: 0, output: 0, totalTokens: 0, cost: { total: 0 } },
            content: [{ type: "text", text: overrides.answer ?? answer() }] } };
        })();
      },
    },
  };
  if (overrides.config) Object.assign(cfg, overrides.config);
  return { cfg, create: () => createReviewAttempt(cfg), sends: () => sends, invocations: () => invocations, capture: () => capture };
}
test("valid one attempt is reused and does not grant product permission", async () => {
  const f = fixture(), attempt = f.create();
  assert.equal(f.sends(), 0); assert.equal(attempt.snapshot().phase, "prepared");
  const first = attempt.run(); assert.equal(attempt.run(), first);
  const result = await first;
  assert.equal(result.outcome, "valid"); assert.equal(result.candidate.decision, "allow");
  assert.equal(f.sends(), 1); assert.equal(f.invocations(), 1); assert.equal(result.requests, 1);
  assert.equal(result.remote_model_verified, true); assert.equal(result.usage.status, "reported");
  assert.equal(result.usage.total_tokens, 8); assert.equal(result.usage.cache_read_tokens, null);
  assert.equal(result.product_gate, false); assert.equal(Object.isFrozen(result), true);
  assert.equal(result.model_wait_ms + result.local_ms, result.elapsed_ms);
  assert.equal(await attempt.run(), result);
});
for (const [decision, reason] of [["ask", "needs-human"], ["deny", "outside-user-scope"]])
  test("valid " + decision + " is returned once without retry/fallback", async () => {
    const f = fixture({ answer: answer(decision, reason) });
    const result = await f.create().run(); assert.equal(result.outcome, "valid"); assert.equal(result.candidate.decision, decision);
    assert.equal(f.sends(), 1); assert.equal(f.invocations(), 1);
  });
for (const [name, patch, expected] of [
  ["Base", { profile: "pi-base" }, "not-called"], ["disabled", { enabled: false }, "not-called"],
  ["hard deny", { hard_policy_allowed: false }, "policy-blocked"], ["role ceiling", { role_allows: false }, "policy-blocked"],
  ["human required", { requires_human: true }, "human-required"], ["risk not automatic", { automatic_risk_allowed: false }, "human-required"],
]) test(name + " has zero SDK/send calls", async () => {
  const f = fixture(); Object.assign(f.cfg.qualification, patch); const result = await f.create().run();
  assert.equal(result.outcome, expected); assert.equal(result.requests, 0); assert.equal(result.candidate, null);
  assert.equal(result.usage.status, "not-sent"); assert.equal(f.sends(), 0); assert.equal(f.invocations(), 0);
});
test("closed fixed SDK options have no tools, routing, sampling or arbitrary callbacks", async () => {
  const f = fixture(); await f.create().run(); const { model, context, options } = f.capture();
  assert.equal(model.reasoning, false); assert.equal(Object.hasOwn(model, "headers"), false);
  assert.deepEqual(model.compat, { supportsStore: false, supportsDeveloperRole: false, supportsUsageInStreaming: true, maxTokensField: "max_tokens" });
  assert.equal(Object.hasOwn(context, "tools"), false); assert.deepEqual(context.messages.map(row => row.role), ["user"]);
  assert.deepEqual(Object.keys(options).sort(), ["apiKey", "signal", "fetch", "maxRetries", "maxTokens", "temperature", "timeoutMs", "onProviderStreamEvent"].sort());
  assert.equal(options.maxRetries, 0); assert.equal(options.temperature, 0);
});
test("constructor captures binding route input and qualification copies", async () => {
  const f = fixture(), attempt = f.create();
  f.cfg.binding.context_digest = "e".repeat(64); f.cfg.route.model = "changed"; f.cfg.route.cost.output = 9;
  f.cfg.input.user_prompt = "changed"; f.cfg.qualification.hard_policy_allowed = false;
  const result = await attempt.run(); assert.equal(result.outcome, "valid");
  assert.equal(result.binding.context_digest, "b".repeat(64)); assert.equal(f.capture().context.messages[0].content, "synthetic operation");
  assert.equal(f.capture().model.cost.output, 2);
});
for (const [name, config, expected] of [
  ["past deadline", { deadlineMs: 0 }, "timeout"], ["stale binding", { isCurrent: () => false }, "discarded"],
  ["current query error", { isCurrent: () => { throw new Error("private-query"); } }, "transport-failure"],
]) test(name + " before send is counted zero", async () => {
  const f = fixture({ config }), result = await f.create().run(); assert.equal(result.outcome, expected);
  assert.equal(result.requests, 0); assert.equal(f.invocations(), 0); assert.equal(result.candidate, null);
});
test("already aborted signal prevents request", async () => {
  const control = new AbortController(); control.abort("private-reason");
  const f = fixture({ config: { signal: control.signal } }), result = await f.create().run();
  assert.equal(result.outcome, "canceled"); assert.equal(f.sends(), 0); assert.equal(f.invocations(), 0);
});
test("null signal is rejected by the fixed constructor error without raw TypeError", () => {
  const f = fixture({ config: { signal: null } });
  assert.throws(f.create, error => error.code === "PI_RISK_REVIEW_TRANSPORT_INVALID"
    && error.message === "PI_RISK_REVIEW_TRANSPORT_INVALID" && error.cause === undefined);
});
test("abort between construction and run preserves null latency and zero calls", async () => {
  const control = new AbortController(), f = fixture({ config: { signal: control.signal } }), attempt = f.create();
  control.abort(); await tick(); const result = await attempt.run();
  assert.equal(result.outcome, "canceled"); assert.equal(result.requests, 0);
  assert.equal(result.elapsed_ms, null); assert.equal(result.model_wait_ms, null); assert.equal(result.local_ms, null);
});
test("full attempt timer terminates stalled SDK iterator before any fetch", async () => {
  const f = fixture({ config: { maxDurationMs: 10 } });
  f.cfg.sdk.streamSimple = () => ({ [Symbol.asyncIterator]() { return { next: () => new Promise(() => {}) }; } });
  const result = await f.create().run(); assert.equal(result.outcome, "timeout"); assert.equal(result.requests, 0);
});
test("in-flight abort keeps actual request, late usage is minimal and never allow", async () => {
  const control = new AbortController(); let release;
  const pause = new Promise(resolve => { release = resolve; });
  const f = fixture({ config: { signal: control.signal }, onFetched: async () => { control.abort("private-cancel"); await pause; } });
  const attempt = f.create(), result = await attempt.run();
  assert.equal(result.outcome, "canceled"); assert.equal(result.requests, 1); assert.equal(result.usage.status, "unknown");
  release(); await tick(); const late = attempt.snapshot();
  assert.equal(late.outcome, "canceled"); assert.equal(late.candidate, null); assert.equal(late.requests, 1);
  assert.equal(late.usage.status, "reported"); assert.equal(late.usage_late, true);
  assert.equal(JSON.stringify(late).includes("private-cancel"), false);
});
test("binding change after physical send discards late allow without erasing request", async () => {
  let current = true;
  const f = fixture({ config: { isCurrent: () => current }, onFetched: async () => { current = false; } });
  const result = await f.create().run(); assert.equal(result.outcome, "discarded"); assert.equal(result.requests, 1); assert.equal(result.candidate, null);
});
for (const raw of [false, { model: "synthetic-reviewer" }, { model: "synthetic-reviewer", usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 1 } }])
  test("missing or invalid raw usage is unknown and never SDK default zero " + JSON.stringify(raw), async () => {
    const f = fixture({ raw }), result = await f.create().run();
    assert.equal(result.usage.status, "unknown"); assert.equal(result.usage.total_tokens, null);
    assert.equal(result.outcome, raw === false ? "transport-failure" : "valid");
  });
test("wire model echo alone is not a remote model observation", async () => {
  const f = fixture({ raw: { model: "different-remote-model" } }), result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.remote_model_verified, false);
  assert.equal(result.requests, 1); assert.equal(JSON.stringify(result).includes("different-remote-model"), false);
});
for (const bad of ["not-json", answer().replace('"decision":"allow"', '"decision":"allow","source":"human"'), answer().replace('"context_digest":"' + "b".repeat(64), '"context_digest":"' + "e".repeat(64))])
  test("invalid candidate stays protocol failure with actual count", async () => {
    const f = fixture({ answer: bad }), result = await f.create().run();
    assert.equal(result.outcome, "protocol-failure"); assert.equal(result.candidate, null); assert.equal(result.requests, 1);
  });
test("returned tool call is rejected with no dispatcher callback", async () => {
  const f = fixture({ event: { type: "toolcall_start", toolCall: { name: "execute" } } }), result = await f.create().run();
  assert.equal(result.outcome, "protocol-failure"); assert.equal(result.candidate, null); assert.equal(result.requests, 1);
});
test("HTTP failure does not expose provider text or retry", async () => {
  const f = fixture(); let calls = 0; f.cfg.send = async () => { calls++; return new Response("private-failure", { status: 500 }); };
  const result = await f.create().run(); assert.equal(result.outcome, "transport-failure"); assert.equal(result.requests, 1); assert.equal(calls, 1);
  assert.equal(JSON.stringify(result).includes("private-failure"), false);
});
test("metadata contains no API key or prompt body or their hashes", async () => {
  const f = fixture(), result = await f.create().run(), raw = JSON.stringify(result);
  for (const marker of ["synthetic-key", "synthetic instructions", "synthetic operation"]) assert.equal(raw.includes(marker), false);
  assert.equal(Object.hasOwn(result, "input_digest"), false); assert.equal(Object.hasOwn(result, "cost"), false);
});
test("a proxy header config must be rejected without invoking traps", () => {
  const f = fixture();
  f.cfg.expectedHeaders = new Proxy({}, { ownKeys() { assert.fail("proxy trap executed"); }, getOwnPropertyDescriptor() { assert.fail("proxy trap executed"); } });
  assert.throws(f.create, error => error.code === "PI_RISK_REVIEW_TRANSPORT_INVALID");
});
test("content array getters cannot execute during candidate validation", async () => {
  let reads = 0;
  const f = fixture();
  const content = []; Object.defineProperty(content, "0", { get() { reads++; return { type: "text", text: answer() }; }, enumerable: true });
  f.cfg.sdk.streamSimple = function(model, context, options) {
    return (async function* () {
      const response = await options.fetch("https://review.invalid/v1/chat/completions", { method: "POST", headers: f.cfg.expectedHeaders,
        body: JSON.stringify({ model: model.id, messages: [{ role: "system", content: context.systemPrompt }, { role: "user", content: context.messages[0].content }], stream: true, stream_options: { include_usage: true }, max_tokens: 1024, temperature: 0 }) });
      await response.text();
      options.onProviderStreamEvent(meta(), model);
      yield { type: "done", message: { api: model.api, provider: model.provider, model: model.id, stopReason: "stop", content } };
    })();
  };
  const result = await f.create().run(); assert.equal(reads, 0); assert.equal(result.outcome, "protocol-failure");
});
test("raw callback before a response was consumed cannot verify remote model or usage", async () => {
  const f = fixture();
  f.cfg.sdk.streamSimple = function(model, context, options) {
    return (async function* () {
      options.onProviderStreamEvent(meta(), model);
      yield { type: "done", message: { api: model.api, provider: model.provider, model: model.id, stopReason: "stop", content: [{ type: "text", text: answer() }] } };
    })();
  };
  const result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.remote_model_verified, false);
  assert.equal(result.requests, 0); assert.equal(result.usage.status, "not-sent"); assert.equal(f.sends(), 0);
});
test("ambient header override is rejected before physical send", async () => {
  const f = fixture(), attempt = f.create(); f.cfg.expectedHeaders.authorization = "Bearer different-private-key";
  const result = await attempt.run(); assert.equal(result.outcome, "transport-failure");
  assert.equal(result.requests, 0); assert.equal(f.sends(), 0); assert.equal(result.wire.invocations, 1);
  assert.equal(JSON.stringify(result).includes("different-private-key"), false);
});
test("monotonic deadline cannot be extended by wall clock rollback", async () => {
  let wall = 100, mono = 0;
  const f = fixture({ config: { deadlineMs: 200, clocks: { wall: () => wall, monotonic: () => mono } },
    onFetched: async () => { wall = -100000; mono = 101; } });
  const result = await f.create().run(); assert.equal(result.outcome, "timeout"); assert.equal(result.requests, 1);
  assert.equal(result.candidate, null);
});
test("wall clock deadline also invalidates response before monotonic ceiling", async () => {
  let wall = 100, mono = 0;
  const f = fixture({ config: { deadlineMs: 200, clocks: { wall: () => wall, monotonic: () => mono } },
    onFetched: async () => { wall = 201; mono = 1; } });
  const result = await f.create().run(); assert.equal(result.outcome, "timeout"); assert.equal(result.requests, 1);
});
test("monotonic regression fails with unknown latency instead of invented zero", async () => {
  let mono = 10;
  const f = fixture({ config: { clocks: { wall: () => Date.now(), monotonic: () => mono } }, onFetched: async () => { mono = 9; } });
  const result = await f.create().run(); assert.equal(result.outcome, "transport-failure"); assert.equal(result.elapsed_ms, null);
});
test("byte cap rejects provider stream flood without retry", async () => {
  const f = fixture({ config: { responseLimit: 8, send: async () => new Response("too-many-stream-bytes") } });
  const result = await f.create().run(); assert.equal(result.outcome, "transport-failure");
  assert.equal(result.requests, 1); assert.equal(result.wire.failure_code, "PI_RISK_FETCH_LIMIT"); assert.equal(result.candidate, null);
});
test("second SDK fetch blocked at seam prevents a valid first response becoming a decision", async () => {
  const f = fixture({ onFetched: async ({ model, options }) => {
    try { await options.fetch(model.baseUrl + "/chat/completions", {}); } catch {}
  } });
  const result = await f.create().run(); assert.equal(result.outcome, "transport-failure"); assert.equal(result.requests, 1);
  assert.equal(result.wire.second_request_blocked, true); assert.equal(result.candidate, null); assert.equal(f.sends(), 1);
});
test("SDK exception is a fixed failure without raw credentials or input", async () => {
  const f = fixture(); f.cfg.sdk.streamSimple = () => { throw new Error("synthetic-key private-sdk-error"); };
  const result = await f.create().run(); assert.equal(result.outcome, "transport-failure"); assert.equal(result.requests, 0);
  assert.equal(JSON.stringify(result).includes("synthetic-key"), false); assert.equal(JSON.stringify(result).includes("private-sdk-error"), false);
});
