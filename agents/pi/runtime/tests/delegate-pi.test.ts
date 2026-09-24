import assert from "node:assert/strict";
import { test } from "node:test";
import { runPiDelegate } from "../delegate-pi.ts";

function fixture(api = "openai-completions") {
  const calls = [], events = [], model = { provider: "fixture", id: "model", api, baseUrl: "https://fixture.invalid/v1" };
  const session = { isStreaming: false, messages: [{ role: "assistant", stopReason: "stop", usage: { input: 10, output: 5 } }],
    getActiveToolNames: () => ["tk_read"], setAutoRetryEnabled: value => calls.push(["retry", value]), setAutoCompactionEnabled() {},
    async prompt() { calls.push(["prompt"]); await modelRuntime.streamSimple(model, {}); this.messages.push({ role: "assistant", stopReason: "stop", usage: { input: 10, output: 5 } }); }, getLastAssistantText: () => "fixture final", async abort() {}, dispose() {} };
  const invoke = async (_model, _context, options) => { const response = await options.fetch(model.baseUrl + (api === "openai-responses" ? "/responses" : api === "openai-codex-responses" ? "/codex/responses" : "/chat/completions"), { method: "POST", body: JSON.stringify({ model: model.id, stream: true }) }); await response.text(); };
  const modelRuntime = { getModel: () => model, stream: invoke, streamSimple: invoke };
  const sdk = { createExtensionRuntime: () => ({}), SettingsManager: { inMemory: value => value },
    async createAgentSession(options) { calls.push(["session", options]); return { session }; } };
  const supervisor = { async call(method, args) { return { valid: true, grant_generation: 1 }; } };
  const input = { request: { backend: "pi", execution_boundary: "agentcfg-tools", execution_mode: "delegate-readonly", mode: "review", requested_model: { provider_id: "fixture", model_id: "model" },
    run_id: "run", lease_id: "lease", grant_generation: 1, cwd: "/fixture/project" }, grant: { expires_at: "2026-09-17T01:00:00Z", allowed_tools: ["tk_read"] }, prompt: "fixture" };
  return { calls, events, session, input, options: { sdk, input, modelRuntime, agentDir: "/fixture/private", sessionManager: { getSessionFile: () => "/fixture/session.jsonl" },
    tools: [{ name: "tk_read", async execute() { return { content: [] }; } }], supervisor, fetchRoute: async () => new Response('data: {"choices":[]}\n\ndata: [DONE]\n\n'),
    report: async value => events.push(value.event), now: () => Date.parse("2026-09-17T00:00:00Z") } };
}

test("Pi delegate uses closed resources and readonly tools, with unknown server identity and cost", async () => {
  const f = fixture(), result = await runPiDelegate(f.options);
  const session = f.calls.find(([name]) => name === "session")[1];
  assert.deepEqual(session.resourceLoader.getExtensions().extensions, []);
  assert.deepEqual(session.resourceLoader.getSkills().skills, []);
  assert.equal(session.settingsManager.retry.provider.maxRetries, 0);
  assert.equal(session.noTools, "builtin");
  assert.equal(result.final, "fixture final"); assert.equal(result.observed_model, null); assert.equal(result.usage.cost, null);
  assert.deepEqual(f.events.map(event => event.seq), [1, 2]);
});

test("Pi backend write and empty or failed final are rejected without fake completion", async () => {
  for (const mutation of [f => { f.input.request.mode = "implement"; }, f => { f.options.tools[0].name = "tk_write"; },
    f => { f.session.getLastAssistantText = () => ""; }, f => { f.options.fetchRoute = async () => new Response('data: {"model":"wrong"}\n\ndata: [DONE]\n\n'); }]) {
    const f = fixture(); mutation(f);
    await assert.rejects(runPiDelegate(f.options));
    assert.equal(f.events.some(event => event.kind === "completed"), false);
  }
});


test("Responses API uses its exact endpoint and completed event; incomplete or mismatched streams fail", async () => {
  const f = fixture("openai-responses");
  f.options.fetchRoute = async url => {
    assert.equal(url, "https://fixture.invalid/v1/responses");
    return new Response('data: {"type":"response.completed","response":{"status":"completed","model":"model"}}\n\n');
  };
  assert.deepEqual((await runPiDelegate(f.options)).observed_model, { provider_id: "fixture", model_id: "model" });
  for (const event of [
    { type: "response.incomplete", response: { status: "incomplete", model: "model" } },
    { type: "response.completed", response: { status: "completed", model: "other" } },
    { type: "response.created", response: { status: "in_progress", model: "model" } },
  ]) {
    const g = fixture("openai-responses");
    g.options.fetchRoute = async () => new Response("data: " + JSON.stringify(event) + "\n\n");
    await assert.rejects(runPiDelegate(g.options));
    assert.equal(g.events.some(row => row.kind === "completed"), false);
  }
});

test("standalone readonly request retries are bounded, reauthorize each send and do not retry a run", async () => {
  const f = fixture(); f.input.retry_limit = 1;
  let sends = 0, authorized = 0;
  f.options.supervisor.call = async () => { authorized++; return { valid: true, grant_generation: 1 }; };
  f.options.fetchRoute = async () => ++sends === 1 ? new Response("busy", { status: 503 }) : new Response("data: [DONE]\n\n");
  f.options.modelRuntime.streamSimple = async (model, _context, options) => {
    assert.equal(options.maxRetries, 1);
    for (let attempt = 0; attempt <= options.maxRetries; attempt++) {
      const response = await options.fetch(model.baseUrl + "/chat/completions", { method: "POST", body: JSON.stringify({ model: model.id }) });
      if (response.ok) { await response.text(); return; }
    }
    throw new Error("fixture retry exhausted");
  };
  assert.equal((await runPiDelegate(f.options)).host_completed, true);
  assert.equal(sends, 2); assert.equal(authorized, 3);
  assert.equal(f.calls.filter(([name]) => name === "session").length, 1);
});


test("selected Pi OAuth access uses the explicit route, bounded decompression and no hidden refresh", async () => {
  const { zstdCompressSync } = await import("node:zlib");
  const f = fixture("openai-codex-responses"), model = f.options.modelRuntime.getModel();
  model.provider = "openai-codex"; f.input.request.requested_model.provider_id = "openai-codex";
  f.options.auth = { provider_id: "openai-codex", apiKey: "synthetic-access", expires_at_ms: Date.parse("2026-09-17T02:00:00Z") };
  f.options.modelRuntime.streamSimple = async (selected, _context, options) => {
    assert.equal(options.apiKey, "synthetic-access"); assert.equal(options.transport, "sse");
    const body = zstdCompressSync(JSON.stringify({ model: selected.id, stream: true }));
    const response = await options.fetch(selected.baseUrl + "/codex/responses", { method: "POST", headers: { "content-encoding": "zstd" }, body });
    await response.text();
  };
  let sends = 0;
  f.options.fetchRoute = async (url, options) => {
    sends++; assert.equal(url, "https://fixture.invalid/v1/codex/responses");
    assert.equal(options.headers.has("content-encoding"), false); assert.equal(JSON.parse(options.body).model, "model");
    return new Response('data: {"type":"response.done","response":{"model":"model"}}\n\ndata: [DONE]\n\n');
  };
  assert.equal((await runPiDelegate(f.options)).host_completed, true); assert.equal(sends, 1);
  f.options.auth.expires_at_ms = 0;
  await assert.rejects(runPiDelegate(f.options), /DELEGATE_CREDENTIAL_EXPIRED/); assert.equal(sends, 1);
});

test("a resumed session's old assistant answer cannot substitute for a new empty turn", async () => {
  const f = fixture();
  f.session.prompt = async () => { await f.options.modelRuntime.streamSimple(f.options.modelRuntime.getModel(), {}); };
  await assert.rejects(runPiDelegate(f.options), /DELEGATE_RESULT_EMPTY/);
  assert.equal(f.events.some(event => event.kind === "completed"), false);
});

test("Pi delegate refuses a native execution boundary before creating an SDK session", async () => {
  const f = fixture();
  f.input.request.execution_boundary = "native-sandbox";
  await assert.rejects(() => runPiDelegate(f.options), /DELEGATE_TOOL_READONLY/);
  assert.equal(f.calls.some(([name]) => name === "session"), false);
});
