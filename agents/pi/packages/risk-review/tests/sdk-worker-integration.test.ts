// 默认OS隔离runner内仅运行自有假包和自有Worker，不加载官方SDK/宿主/账号。
import assert from "node:assert/strict";
import { test } from "node:test";
import { Worker } from "node:worker_threads";
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createIsolatedReviewSdk } from "../src/sdk-worker.ts";
import { createReviewAttempt } from "../src/transport.ts";

const binding = () => ({ request_id: "1".repeat(32), operation_digest: "a".repeat(64),
  context_digest: "b".repeat(64), reviewer_identity: "c".repeat(64) });
const answer = () => JSON.stringify({ schema_version: 1, ...binding(), decision: "allow", reason_code: "authorized-in-scope" });
const defer = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

function ownSdk(t, mode = "valid") {
  const directory = mkdtempSync(join(tmpdir(), "rotom-own-review-worker-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const slice = join(directory, "slice"), anchor = join(slice, "package.json"), marker = join(directory, "own-import-marker");
  const pkg = join(slice, "node_modules/@earendil-works/pi-ai");
  for (const path of [slice, join(pkg, "api"), join(pkg, "utils")]) mkdirSync(path, { recursive: true, mode: 0o700 });
  writeFileSync(anchor, JSON.stringify({ name: "own-synthetic-slice", type: "module" }), { mode: 0o600 });
  writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "@earendil-works/pi-ai", version: "0.0.0-test",
    type: "module", exports: { "./api/*": { import: "./api/*.mjs" }, "./utils/*": { import: "./utils/*.mjs" } } }), { mode: 0o600 });
  writeFileSync(join(pkg, "brand.mjs"), "export const contexts = new WeakSet();\n", { mode: 0o600 });
  writeFileSync(join(pkg, "utils/transcript.mjs"), `import { contexts } from "../brand.mjs";
    export function normalizeContext(value) { contexts.add(value); return value; }
  `, { mode: 0o600 });
  const fixtureMode = JSON.stringify(mode), markerPath = JSON.stringify(marker);
  writeFileSync(join(pkg, "api/openai-completions.mjs"), `
    import { writeFileSync } from "node:fs";
    import { contexts } from "../brand.mjs";
    const mode = ${fixtureMode};
    writeFileSync(${markerPath}, "own fixture imported", { mode: 0o600 });
    if (Object.keys(process.env).sort().join(",") !== "OPENAI_LOG" || process.env.OPENAI_LOG !== "off")
      throw new Error("synthetic inherited environment");
    console.log("OWN_SDK_STDOUT_DROP_SENTINEL");
    console.error("OWN_SDK_STDERR_DROP_SENTINEL");
    export async function* streamSimple(model, context, options) {
      if (!contexts.has(context)) throw new Error("synthetic unbranded context");
      if (mode === "error") throw new Error("synthetic-private-key-and-prompt");
      const messages = [];
      if (context.systemPrompt) messages.push({ role: "system", content: context.systemPrompt });
      messages.push({ role: "user", content: context.messages[0].content });
      const body = { model: model.id, messages, stream: true, stream_options: { include_usage: true },
        max_tokens: options.maxTokens, temperature: 0 };
      if (mode === "extra-tool") body.tools = [];
      const response = await options.fetch(model.baseUrl + "/chat/completions", { method: "POST",
        headers: new Headers({ authorization: "Bearer " + options.apiKey, accept: "application/json", "content-type": "application/json" }),
        body: JSON.stringify(body), signal: options.signal });
      await response.text();
      await options.onProviderStreamEvent({ model: model.id,
        ...(mode === "missing-usage" ? {} : { usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 } }) });
      if (mode === "two-metadata") await options.onProviderStreamEvent({ model: model.id,
        usage: { prompt_tokens: 5, completion_tokens: 4, total_tokens: 9 } });
      yield { type: "done", message: { api: model.api, provider: model.provider, model: model.id, stopReason: "stop",
        content: [{ type: "text", text: context.messages[0].content }], usage: { totalTokens: 0, cost: { total: 0 } } } };
    }
  `, { mode: 0o600 });
  return { directory, slice, anchor, marker };
}

function combination(t, mode = "valid", overrides = {}) {
  const files = ownSdk(t, mode);
  const workers = [], output = [];
  const adapter = createIsolatedReviewSdk({ anchor: overrides.anchor ?? files.anchor, workerFactory(url, settings) {
    const worker = new Worker(url, settings); workers.push(worker);
    // 只观察自有固定fixture的有界输出，生产adapter仍自行drain/drop。
    for (const stream of [worker.stdout, worker.stderr]) stream.on("data", chunk => {
      if (output.length < 8) output.push(chunk.toString("utf8").slice(0, 256));
    });
    return worker;
  } });
  t.after(() => adapter.close());
  let sends = 0;
  const cfg = {
    binding: binding(), route: { identity: "c".repeat(64), pricing_identity: "d".repeat(64), currency: "USD",
      provider: "synthetic-provider", model: "synthetic-reviewer", base_url: "https://own-review.invalid/v1",
      context_window: 32000, max_output_tokens: 1024, cost: { input: 1, output: 2, cacheRead: 1, cacheWrite: 1 } },
    input: { system_prompt: "own synthetic policy", user_prompt: answer() },
    qualification: { profile: "pi-full", enabled: true, hard_policy_allowed: true, role_allows: true,
      requires_human: false, automatic_risk_allowed: true },
    apiKey: "own-synthetic-private-key", expectedHeaders: { authorization: "Bearer own-synthetic-private-key",
      accept: "application/json", "content-type": "application/json" },
    sdk: adapter.sdk, isCurrent: () => true, deadlineMs: Date.now() + 10000, maxDurationMs: 5000,
    send: async (url, init) => { sends++; assert.equal(init.redirect, "manual");
      return overrides.send ? overrides.send(url, init) : new Response("own-synthetic-response"); },
    ...overrides.config,
  };
  return { files, adapter, cfg, workers, output, sends: () => sends, create: () => createReviewAttempt(cfg) };
}

test("own real Worker: import-only exports, clean env, transferred stream and transport agree", { timeout: 10000 }, async t => {
  // runner提供固定临时env，以下只放合成污染，不读取或保存原认证环境。
  process.env.OPENAI_CUSTOM_HEADERS = "X-Own-Synthetic: should-not-inherit";
  process.env.ROTOM_WORKER_SYNTHETIC_SENTINEL = "should-not-inherit";
  t.after(() => { delete process.env.OPENAI_CUSTOM_HEADERS; delete process.env.ROTOM_WORKER_SYNTHETIC_SENTINEL; });
  const f = combination(t);
  const attempt = f.create(); assert.equal(f.workers.length, 0);
  const result = await attempt.run();
  assert.equal(result.outcome, "valid"); assert.equal(result.candidate.decision, "allow");
  assert.equal(result.remote_model_verified, true); assert.equal(result.usage.total_tokens, 8);
  assert.equal(result.requests, 1); assert.equal(f.sends(), 1); assert.equal(f.workers.length, 1);
  assert.equal(existsSync(f.files.marker), true); assert.ok(result.wire.response_bytes > 0);
  await f.adapter.close();
  assert.equal(f.adapter.snapshot().worker_terminated, true); assert.equal(f.adapter.snapshot().failure_code, null);
  assert.equal(f.output.join("").includes("OWN_SDK_STDOUT_DROP_SENTINEL"), true);
  assert.equal(f.output.join("").includes("OWN_SDK_STDERR_DROP_SENTINEL"), true);
  assert.equal(result.product_gate, false);
});

for (const [name, qualification, outcome] of [
  ["Base", { profile: "pi-base" }, "not-called"], ["off", { enabled: false }, "not-called"],
  ["hard deny", { hard_policy_allowed: false }, "policy-blocked"], ["human", { requires_human: true }, "human-required"],
]) test("own Worker combination: " + name + " creates no worker or SDK import", async t => {
  const f = combination(t); Object.assign(f.cfg.qualification, qualification);
  const result = await f.create().run();
  assert.equal(result.outcome, outcome); assert.equal(result.requests, 0); assert.equal(f.sends(), 0);
  assert.equal(f.workers.length, 0); assert.equal(existsSync(f.files.marker), false);
});

test("own Worker maximum API key survives Bearer prefix through every header boundary", { timeout: 10000 }, async t => {
  const apiKey = "k".repeat(8192);
  const f = combination(t, "valid", { config: { apiKey, expectedHeaders: {
    authorization: "Bearer " + apiKey, accept: "application/json", "content-type": "application/json",
  } } });
  const result = await f.create().run();
  assert.equal(result.outcome, "valid"); assert.equal(result.candidate.decision, "allow");
  assert.equal(result.requests, 1); assert.equal(f.sends(), 1); assert.equal(f.workers.length, 1);
  await f.adapter.close(); assert.equal(f.adapter.snapshot().worker_terminated, true);
});

test("own Worker extra tool field rejected at parent before physical send", { timeout: 10000 }, async t => {
  const f = combination(t, "extra-tool"), result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.candidate, null);
  assert.equal(result.requests, 0); assert.equal(f.sends(), 0);
  assert.equal(f.adapter.snapshot().fetch_requests, 1); // 进入父fetch接缝，不等于物理send。
  await f.adapter.close(); assert.equal(f.adapter.snapshot().worker_terminated, true);
});

test("own Worker missing provider usage remains unknown despite SDK zero", { timeout: 10000 }, async t => {
  const f = combination(t, "missing-usage"), result = await f.create().run();
  assert.equal(result.outcome, "valid"); assert.equal(result.requests, 1); assert.equal(result.usage.status, "unknown");
  assert.equal(result.usage.total_tokens, null); await f.adapter.close();
});

test("own Worker transferred body limit fails without retry", { timeout: 10000 }, async t => {
  const f = combination(t, "valid", { send: () => new Response("x".repeat(128)), config: { responseLimit: 32 } });
  const result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.candidate, null); assert.equal(result.requests, 1);
  assert.equal(f.sends(), 1); assert.equal(result.wire.failure_code, "PI_RISK_FETCH_LIMIT");
  assert.equal(result.wire.response_bytes, 0); await f.adapter.close();
});

test("own Worker in-flight cancel preserves request and waits separate termination", { timeout: 10000 }, async t => {
  const abort = new AbortController();
  const f = combination(t, "valid", { config: { signal: abort.signal }, send() {
    queueMicrotask(() => abort.abort()); return new Response("own-synthetic-response");
  } });
  const result = await f.create().run();
  assert.equal(result.outcome, "canceled"); assert.equal(result.requests, 1); assert.equal(result.candidate, null);
  assert.equal(result.usage.status, "unknown"); assert.equal(f.sends(), 1);
  await f.adapter.close(); assert.equal(f.adapter.snapshot().worker_terminated, true);
});

test("own Worker raw callbacks remain backpressured through real IPC", { timeout: 10000 }, async t => {
  const f = combination(t, "two-metadata");
  const first = defer(), release = defer(); let count = 0;
  const original = f.adapter.sdk;
  const sdk = { normalizeContext: original.normalizeContext, streamSimple(model, context, options) {
    return original.streamSimple(model, context, { ...options, async onProviderStreamEvent(value) {
      count++; if (count === 1) { first.resolve(); await release.promise; }
      options.onProviderStreamEvent(value);
    } });
  } };
  f.cfg.sdk = sdk; const promise = f.create().run();
  await first.promise; assert.equal(count, 1);
  await new Promise(resolve => setTimeout(resolve, 20)); assert.equal(count, 1);
  release.resolve(); const result = await promise;
  assert.equal(result.outcome, "valid"); assert.equal(count, 2); assert.equal(result.usage.total_tokens, 9);
  await f.adapter.close();
});

test("own Worker provider exception is fixed and never discloses SDK raw error", { timeout: 10000 }, async t => {
  const f = combination(t, "error"), result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.requests, 0); assert.equal(result.candidate, null);
  const metadata = JSON.stringify({ result, worker: f.adapter.snapshot() });
  for (const value of ["synthetic-private-key-and-prompt", f.cfg.apiKey, f.cfg.input.system_prompt, f.files.anchor])
    assert.equal(metadata.includes(value), false);
  await f.adapter.close();
});

test("own Worker missing slice package cannot borrow ancestor public exports", { timeout: 10000 }, async t => {
  const f = combination(t);
  const missing = join(f.files.slice, "isolated-missing"); mkdirSync(missing, { mode: 0o700 });
  const anchor = join(missing, "package.json"); writeFileSync(anchor, "{}", { mode: 0o600 });
  await f.adapter.close();
  const adapter = createIsolatedReviewSdk({ anchor }); t.after(() => adapter.close());
  f.cfg.sdk = adapter.sdk;
  const result = await f.create().run();
  assert.equal(result.outcome, "transport-failure"); assert.equal(result.requests, 0); assert.equal(f.sends(), 0);
  assert.equal(existsSync(f.files.marker), false); await adapter.close();
});
