import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { cursorDelegateTransport } from "../cursor-delegate.ts";

// 最小事件流替身；不导入 Pi 宿主或连接 HTTP/2。
function createStream() {
  const events = [], waiting = []; let done = false;
  return { push(value) { if (waiting.length) waiting.shift()({ value, done: false }); else events.push(value); },
    end() { done = true; for (const resolve of waiting.splice(0)) resolve({ done: true }); },
    async *[Symbol.asyncIterator]() { while (true) { if (events.length) yield events.shift(); else if (done) return; else { const next = await new Promise(resolve => waiting.push(resolve)); if (next.done) return; yield next.value; } } } };
}

async function setup() {
  const calls = [], endpoint = "https://agentn.us.api5.cursor.sh", token = "synthetic-selected";
  const http2 = { connect(authority) {
    calls.push("connect"); const client = new EventEmitter();
    client.request = headers => { calls.push("request"); const stream = new EventEmitter(); queueMicrotask(() => { stream.emit("response", { ":status": 200 }); stream.emit("data", Buffer.from("fixture frame")); }); return stream; };
    client.destroy = () => { calls.push("destroy"); queueMicrotask(() => client.emit("close")); };
    return client;
  } };
  const original = http2.connect, modelRuntime = { registerProvider(id, definition) { calls.push("register"); assert.equal(id, "cursor"); assert.equal(definition.models.length, 1); assert.equal(definition.oauth, undefined); assert.equal(definition.refreshModels, undefined); } };
  const transport = await cursorDelegateTransport({ plugin: async pi => {
    pi.on("session_shutdown", () => calls.push("cleanup")); pi.registerCommand("must-not-register", {});
    pi.registerProvider("cursor", { api: "cursor-native", baseUrl: endpoint, models: [{ id: "selected" }, { id: "other" }], oauth: {}, refreshModels() { throw Error("network discovery forbidden"); }, streamSimple() {} });
  }, modelRuntime, http2, createStream, selected: { provider_id: "cursor", model_id: "selected" }, endpoint, accessToken: token });
  return { calls, http2, original, transport, endpoint, headers: { ":method": "POST", ":path": "/agent.v1.AgentService/Run", authorization: "Bearer " + token } };
}

test("Cursor delegates register one model and require authorized real transport observations", async () => {
  const f = await setup(), observations = [];
  assert.throws(() => f.http2.connect(f.endpoint), /CURSOR_ROUTE_UNBOUND/);
  const output = f.transport.invoke(() => {
    f.http2.connect(f.endpoint).request(f.headers);
    const stream = createStream(); queueMicrotask(() => { stream.push({ type: "done", message: { content: [] } }); stream.end(); }); return stream;
  }, {}, {}, {}, async () => f.calls.push("authorized"), observations);
  for await (const _ of output) {}
  f.transport.verify();
  assert.ok(f.calls.indexOf("authorized") < f.calls.indexOf("connect"));
  assert.deepEqual(observations, [{ done: true, failed: false, model: null }]);
  await f.transport.close({}); assert.equal(f.http2.connect, f.original); assert.ok(f.calls.includes("destroy"));
});

test("Cursor no-network fake completion, wrong destination, extra request and revoked grant cannot verify", async () => {
  for (const mode of ["no-wire", "wrong-host", "extra-request", "revoked"]) {
    const f = await setup(), observations = [];
    try {
      const output = f.transport.invoke(() => {
        if (mode !== "no-wire") {
          const client = f.http2.connect(mode === "wrong-host" ? "https://unselected.invalid" : f.endpoint);
          client.request(f.headers);
          if (mode === "extra-request") client.request(f.headers);
        }
        const stream = createStream(); stream.push({ type: "done", message: {} }); stream.end(); return stream;
      }, {}, {}, {}, async () => { if (mode === "revoked") throw Error("private authorization detail"); }, observations);
      const events = []; for await (const event of output) events.push(event);
      assert.throws(() => f.transport.verify(), /CURSOR_EXECUTION_UNVERIFIED/);
      assert.ok(!JSON.stringify(events).includes("private authorization detail"));
      if (mode === "revoked") assert.equal(f.calls.includes("connect"), false);
    } finally { await f.transport.close({}); }
  }
});

test("Cursor adapter is wired into the actual readonly delegation flow and closes its transport", async () => {
  const { runPiDelegate } = await import("../delegate-pi.ts");
  const f = await setup(), model = { provider: "cursor", id: "selected", api: "cursor-native", baseUrl: f.endpoint };
  const stream = () => {
    f.http2.connect(f.endpoint).request(f.headers);
    const result = createStream(); queueMicrotask(() => { result.push({ type: "done", message: {} }); result.end(); }); return result;
  };
  const runtime = { getModel: () => model, stream, streamSimple: stream, fetchDeferred() { throw Error("must be gated"); } };
  let routeClosed = false;
  const session = { isStreaming: false, messages: [], getActiveToolNames: () => ["tk_read"], setAutoCompactionEnabled() {}, setAutoRetryEnabled() {},
    async prompt() {
      assert.throws(() => runtime.fetchDeferred(), /DELEGATE_HELPER_DISABLED/);
      for await (const _ of runtime.streamSimple(model, {})) {}
      this.messages.push({ role: "assistant", stopReason: "stop", usage: { input: 1, output: 1 } });
    }, getLastAssistantText: () => "completed readonly review", dispose() {} };
  const result = await runPiDelegate({ sdk: { createExtensionRuntime: () => ({}), SettingsManager: { inMemory: value => value }, createAgentSession: async () => ({ session }) },
    input: { request: { backend: "pi", execution_boundary: "agentcfg-tools", execution_mode: "delegate-readonly", mode: "review", requested_model: { provider_id: "cursor", model_id: "selected" }, run_id: "run", lease_id: "lease", grant_generation: 1 },
      grant: { allowed_tools: ["tk_read"], expires_at: new Date(Date.now() + 60000).toISOString() } }, modelRuntime: runtime,
    agentDir: "/fixture", sessionManager: { getSessionFile: () => null }, tools: [{ name: "tk_read" }], supervisor: { call: async () => ({ valid: true, grant_generation: 1 }) },
    nativeTransport: f.transport, auth: { provider_id: "cursor", apiKey: "synthetic-selected", expires_at_ms: Date.now() + 60000 },
    fetchRoute: Object.assign(() => { throw Error("Cursor must not use OpenAI endpoint"); }, { close() { routeClosed = true; } }), report: async () => {} });
  assert.equal(result.host_completed, true); assert.equal(result.observed_model, null); assert.equal(result.usage.cost, null);
  assert.equal(f.http2.connect, f.original); assert.equal(routeClosed, true);
});
