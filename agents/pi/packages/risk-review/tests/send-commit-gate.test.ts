import assert from "node:assert/strict";
import { test as nodeTest } from "node:test";
import { createSingleRequestFetch } from "../src/wire-fetch.ts";
import { createReviewRequestValidator } from "../src/request-wire.ts";
import { createReviewAttempt } from "../src/transport.ts";
import { prepareSharedReviewModel } from "../src/shared-model.ts";

const test = (name, body) => nodeTest(name, { timeout: 2000 }, body);
const endpoint = "https://synthetic.invalid/v1/chat/completions";
const expectedHeaders = () => ({ authorization: "Bearer SYNTHETIC_PRIVATE_GATE_KEY", accept: "application/json", "content-type": "application/json" });
const request = () => ({ method: "POST", headers: expectedHeaders(), body: JSON.stringify({ model: "synthetic-reviewer",
  messages: [{ role: "system", content: "instructions" }, { role: "user", content: "operation" }],
  stream: true, stream_options: { include_usage: true }, temperature: 0, max_tokens: 1024 }) });
const defer = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise(resolve => setImmediate(resolve));
const reject = (promise, code) => assert.rejects(promise, value => value.code === code && value.message === code && value.cause === undefined);
function wireFixture(patch = {}) {
  let sends = 0, gates = 0, sent;
  const control = new AbortController();
  const validate = createReviewRequestValidator({ endpoint, model: "synthetic-reviewer", systemPrompt: "instructions",
    userPrompt: "operation", maxTokens: 1024, expectedHeaders: expectedHeaders() });
  const wire = createSingleRequestFetch({ signal: control.signal, expired: () => false, validate,
    beforeSend: (...args) => { gates++; assert.deepEqual(args, []); return true; },
    send: (input, init) => { sends++; sent = { input, init }; return new Response("ok"); }, ...patch });
  return { wire, control, sends: () => sends, gates: () => gates, sent: () => sent };
}

test("strict wire, original commit ack, then exactly one platform entry", async () => {
  const f = wireFixture();
  const init = request();
  assert.equal(await (await f.wire.fetch(endpoint, init)).text(), "ok");
  assert.equal(f.gates(), 1); assert.equal(f.sends(), 1);
  assert.equal(f.sent().init.redirect, "manual"); assert.notEqual(f.sent().init.signal, init.signal);
  assert.equal(init.redirect, undefined);
  assert.deepEqual(f.wire.snapshot(), { invocations: 1, requests: 1, response_bytes: 2, body_complete: true,
    redirect_blocked: false, second_request_blocked: false, failure_code: null, gate_attempted: true, gate_acknowledged: true });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_INVALID");
  assert.equal(f.gates(), 1); assert.equal(f.sends(), 1);
});
for (const answer of [false, undefined, 1, {}, "true"]) test("non-ack commit has zero platform entries " + String(answer), async () => {
  let gates = 0;
  const f = wireFixture({ beforeSend: () => { gates++; return answer; } });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_COMMIT_FAILED");
  assert.equal(gates, 1); assert.equal(f.sends(), 0);
  assert.equal(f.wire.snapshot().gate_attempted, true); assert.equal(f.wire.snapshot().gate_acknowledged, false);
});
for (const kind of ["throw", "reject", "false-promise"]) test("failed or unknown commit is sanitized " + kind, async () => {
  const f = wireFixture({ beforeSend: () => {
    if (kind === "throw") throw new Error("SYNTHETIC_PRIVATE_COMMIT_ERROR");
    return kind === "reject" ? Promise.reject(new Error("SYNTHETIC_PRIVATE_COMMIT_ERROR")) : Promise.resolve(false);
  } });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_COMMIT_FAILED");
  assert.equal(f.sends(), 0); assert.equal(f.wire.snapshot().requests, 0);
  assert.equal(JSON.stringify(f.wire.snapshot()).includes("SYNTHETIC_PRIVATE"), false);
});
test("thenable and proxy are not awaited or read", async () => {
  let reads = 0;
  for (const value of [{ get then() { reads++; throw new Error("private"); } }, new Proxy({}, { get() { reads++; throw new Error("private"); } })]) {
    const f = wireFixture({ beforeSend: () => value });
    await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_COMMIT_FAILED"); assert.equal(f.sends(), 0);
  }
  assert.equal(reads, 0);
});
test("native promise own then getter is not evaluated", async () => {
  let reads = 0;
  const promise = Promise.resolve(true);
  Object.defineProperty(promise, "then", { get() { reads++; throw new Error("private"); } });
  const f = wireFixture({ beforeSend: () => promise });
  assert.equal(await (await f.wire.fetch(endpoint, request())).text(), "ok"); assert.equal(reads, 0);
});
test("promise constructor getter is rejected without evaluating it", async () => {
  let reads = 0;
  const promise = Promise.resolve(true);
  Object.defineProperty(promise, "constructor", { get() { reads++; throw new Error("private"); } });
  const f = wireFixture({ beforeSend: () => promise });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_COMMIT_FAILED"); assert.equal(reads, 0); assert.equal(f.sends(), 0);
});
for (const headersKind of ["plain", "Headers"]) test("gate waiting captures original header/body values " + headersKind, async () => {
  const pending = defer(), entered = defer();
  const f = wireFixture({ beforeSend: () => { entered.resolve(); return pending.promise; } });
  const init = request();
  if (headersKind === "Headers") init.headers = new Headers(init.headers);
  const originalBody = init.body;
  const running = f.wire.fetch(endpoint, init);
  await entered.promise;
  init.method = "DELETE"; init.body = "SYNTHETIC_PRIVATE_CHANGED_BODY";
  if (headersKind === "Headers") init.headers.set("authorization", "Bearer CHANGED");
  else init.headers.authorization = "Bearer CHANGED";
  pending.resolve(true);
  await (await running).text();
  assert.equal(f.sent().init.method, "POST"); assert.equal(f.sent().init.body, originalBody);
  assert.equal(f.sent().init.headers.authorization, "Bearer SYNTHETIC_PRIVATE_GATE_KEY");
});
for (const fault of ["body", "headers", "method", "extra", "signal", "getter", "proxy"]) test("invalid final wire never reaches gate " + fault, async () => {
  const f = wireFixture(); let reads = 0; let init = request();
  if (fault === "body") init.body = "{invalid";
  if (fault === "headers") init.headers.authorization = "Bearer changed";
  if (fault === "method") init.method = "GET";
  if (fault === "extra") init.redirect = "follow";
  if (fault === "signal") init.signal = {};
  if (fault === "getter") Object.defineProperty(init, "body", { enumerable: true, get() { reads++; throw new Error("private"); } });
  if (fault === "proxy") init = new Proxy(init, { get() { reads++; throw new Error("private"); } });
  await reject(f.wire.fetch(endpoint, init), "PI_RISK_FETCH_INVALID");
  assert.equal(f.gates(), 0); assert.equal(f.sends(), 0); assert.equal(reads, 0); assert.equal(f.wire.snapshot().gate_attempted, false);
});
test("captured wire is checked before gate and after ack using original schema", async () => {
  const shapes = [];
  const f = wireFixture({ validate: (input, init) => {
    shapes.push(Object.keys(init).sort());
    return !Object.hasOwn(init, "redirect") && init.method === "POST";
  } });
  await (await f.wire.fetch(endpoint, request())).text();
  assert.equal(shapes.length, 3); assert.ok(shapes.every(keys => !keys.includes("redirect")));
});
for (const failedCheck of [2, 3]) test("copy validation failure has zero send, gate position " + failedCheck, async () => {
  let checks = 0;
  const f = wireFixture({ validate: () => ++checks !== failedCheck });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_INVALID");
  assert.equal(f.gates(), failedCheck === 2 ? 0 : 1); assert.equal(f.sends(), 0);
});
for (const failedCheck of [1, 2, 3]) test("async rejected validator is observed without authorizing gate " + failedCheck, async () => {
  let checks = 0;
  const f = wireFixture({ validate: () => ++checks !== failedCheck ? true : Promise.reject(new Error("private")) });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_INVALID"); await tick();
  assert.equal(f.gates(), failedCheck < 3 ? 0 : 1); assert.equal(f.sends(), 0);
});
test("commit ack followed by cancellation keeps ack but zero local send", async () => {
  const controller = new AbortController();
  const f = wireFixture({ signal: controller.signal, beforeSend: () => { controller.abort("private"); return true; } });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_CANCELED");
  assert.equal(f.wire.snapshot().gate_acknowledged, true); assert.equal(f.sends(), 0);
});
for (const late of ["resolve", "reject"]) test("cancel wakes stalled gate; late receipt does not send " + late, async () => {
  const pending = defer(), entered = defer();
  const f = wireFixture({ beforeSend: () => { entered.resolve(); return pending.promise; } });
  const running = f.wire.fetch(endpoint, request()); await entered.promise;
  f.control.abort("private"); await reject(running, "PI_RISK_FETCH_CANCELED");
  if (late === "resolve") pending.resolve(true); else pending.reject(new Error("private"));
  await tick();
  assert.equal(f.sends(), 0); assert.equal(f.wire.snapshot().requests, 0);
  assert.equal(f.wire.snapshot().gate_acknowledged, late === "resolve");
});
test("expiry polling cancels uncooperative gate without its physical cancellation", async () => {
  let expired = false;
  const entered = defer();
  const f = wireFixture({ expired: () => expired, beforeSend: () => { entered.resolve(); return new Promise(() => {}); } });
  const running = f.wire.fetch(endpoint, request()); await entered.promise; expired = true;
  await reject(running, "PI_RISK_FETCH_CANCELED"); assert.equal(f.sends(), 0);
});
test("original SDK signal cancels gate wait", async () => {
  const sdk = new AbortController(), entered = defer();
  const f = wireFixture({ beforeSend: () => { entered.resolve(); return new Promise(() => {}); } });
  const init = { ...request(), signal: sdk.signal };
  const running = f.wire.fetch(endpoint, init); await entered.promise; sdk.abort();
  await reject(running, "PI_RISK_FETCH_CANCELED"); assert.equal(f.sends(), 0);
});
test("platform synchronous throw counts one local entry after ack", async () => {
  let sends = 0;
  const f = wireFixture({ send: () => { sends++; throw new Error("private"); } });
  await reject(f.wire.fetch(endpoint, request()), "PI_RISK_FETCH_FAILED");
  assert.equal(sends, 1); assert.equal(f.wire.snapshot().requests, 1); assert.equal(f.wire.snapshot().gate_acknowledged, true);
});

function transportFixture(patch = {}) {
  const binding = { request_id: "1".repeat(32), operation_digest: "a".repeat(64), context_digest: "b".repeat(64), reviewer_identity: "c".repeat(64) };
  let sdkCalls = 0, sends = 0, gates = 0;
  const config = { binding, route: { identity: binding.reviewer_identity, pricing_identity: "d".repeat(64), currency: "USD",
    provider: "synthetic-provider", model: "synthetic-reviewer", base_url: "https://synthetic.invalid/v1", context_window: 32000,
    max_output_tokens: 1024, cost: { input: 1, output: 2, cacheRead: 1, cacheWrite: 1 } },
    input: { system_prompt: "instructions", user_prompt: "operation" }, qualification: { profile: "pi-full", enabled: true,
      hard_policy_allowed: true, role_allows: true, requires_human: false, automatic_risk_allowed: true },
    apiKey: "SYNTHETIC_PRIVATE_GATE_KEY", expectedHeaders: expectedHeaders(), deadlineMs: Date.now() + 10000,
    maxDurationMs: 1000, isCurrent: () => true, beforeSend: () => { gates++; return true; },
    send: () => { sends++; return new Response("synthetic-sse"); },
    sdk: { normalizeContext: value => structuredClone(value), streamSimple(model, context, options) {
      sdkCalls++;
      return (async function* () {
        const init = request();
        if (model.reasoning) init.body = JSON.stringify({ ...JSON.parse(init.body), thinking: { type: "disabled" } });
        await (await options.fetch(endpoint, init)).text();
        options.onProviderStreamEvent({ model: model.id, usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 } });
        yield { type: "done", message: { api: model.api, provider: model.provider, model: model.id, stopReason: "stop",
          content: [{ type: "text", text: JSON.stringify({ schema_version: 1, ...binding, decision: "allow", reason_code: "authorized-in-scope" }) }] } };
      })();
    } }, ...patch };
  return { config, run: () => createReviewAttempt(config).run(), sends: () => sends, gates: () => gates, sdkCalls: () => sdkCalls };
}
test("transport passes private gate and remains a candidate without product permit", async () => {
  const f = transportFixture(), result = await f.run();
  assert.equal(result.outcome, "valid"); assert.equal(result.candidate.decision, "allow"); assert.equal(result.product_gate, false);
  assert.equal(f.sdkCalls(), 1); assert.equal(f.gates(), 1); assert.equal(f.sends(), 1); assert.equal(result.wire.gate_acknowledged, true);
});
for (const qualified of [false, undefined]) test("shared unqualified input does not enter commit, SDK or send " + String(qualified), async () => {
  const f = transportFixture(), route = { logical_provider: "synthetic-provider", native_route: "synthetic-provider",
    model_id: "synthetic-reviewer", auth_kind: "api-key", owner: "pi-environment", api: "openai-completions", base_url: "https://synthetic.invalid/v1" };
  const configuration_identity = "a".repeat(64);
  const prepared = prepareSharedReviewModel({ route, configuration_identity, token_limits: { input_tokens: 12000, output_tokens: 1024 },
    descriptor: { id: route.model_id, provider: route.native_route, api: route.api, name: "Shared Synthetic", baseUrl: route.base_url,
      reasoning: true, input: ["text"], cost: { input: 1, output: 2, cacheRead: 1, cacheWrite: 1 }, contextWindow: 32000,
      maxTokens: 16384, compat: { thinkingFormat: "deepseek" }, thinkingLevelMap: { low: "low", high: "high" } } });
  f.config.sharedModel = { prepared, route, configuration_identity };
  f.config.route.identity = prepared.model_identity; f.config.binding.reviewer_identity = prepared.model_identity;
  if (qualified !== undefined) f.config.inputQualification = () => qualified;
  const result = await f.run();
  assert.equal(f.sdkCalls(), 0); assert.equal(f.gates(), 0); assert.equal(f.sends(), 0); assert.equal(result.usage.status, "not-sent");
  assert.equal(result.outcome, "transport-failure"); assert.ok(result.records.some(row => row.event === "input-unqualified"));
});
test("current change after commit ack never enters platform and keeps unknown usage", async () => {
  let current = true;
  const f = transportFixture({ isCurrent: () => current, beforeSend: () => { current = false; return true; } });
  const result = await f.run();
  assert.equal(result.outcome, "discarded"); assert.equal(result.requests, 0); assert.equal(f.sends(), 0);
  assert.equal(result.wire.gate_acknowledged, true); assert.equal(result.usage.status, "unknown");
});
for (const stage of ["Base", "off", "hard", "human"]) test("early policy gate has zero commit, SDK and platform " + stage, async () => {
  const f = transportFixture();
  if (stage === "Base") f.config.qualification.profile = "pi-base";
  if (stage === "off") f.config.qualification.enabled = false;
  if (stage === "hard") f.config.qualification.hard_policy_allowed = false;
  if (stage === "human") f.config.qualification.requires_human = true;
  const result = await f.run();
  assert.equal(f.sdkCalls(), 0); assert.equal(f.gates(), 0); assert.equal(f.sends(), 0); assert.equal(result.usage.status, "not-sent");
});
for (const kind of ["failed", "ack-canceled"]) test("transport zero local send after commit attempt has unknown usage " + kind, async () => {
  const controller = new AbortController();
  const f = transportFixture({ signal: controller.signal, beforeSend: () => {
    if (kind === "failed") return Promise.reject(new Error("private"));
    controller.abort("private"); return true;
  } });
  const result = await f.run();
  assert.equal(result.candidate, null); assert.equal(result.requests, 0); assert.equal(f.sends(), 0);
  assert.equal(result.usage.status, "unknown"); assert.equal(result.usage.total_tokens, null);
  assert.equal(result.wire.gate_attempted, true); assert.equal(result.wire.gate_acknowledged, kind === "ack-canceled");
});
test("successful gate snapshot omits prompt/body/auth and any raw error", async () => {
  const f = transportFixture(), raw = JSON.stringify(await f.run());
  for (const marker of ["SYNTHETIC_PRIVATE_GATE_KEY", "instructions", "operation\"", "authorization", "Bearer", "synthetic-sse"]) assert.equal(raw.includes(marker), false);
});
