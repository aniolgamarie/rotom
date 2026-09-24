import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { listenMcpCallback, closeMcpListener } from "../mcp-listener.ts";

function fixture({ queued = false, refuseClose = false } = {}) {
  const calls = [], records = new Map(); let executor, deadline;
  class Server extends EventEmitter {
    listening = false;
    listen(port, host, done) { calls.push(["listen", port, host]); this.listening = true; queueMicrotask(done); }
    close(done) { calls.push("close"); if (refuseClose) { done(Error("fixture failure")); return; } this.listening = false; this.emit("close"); done(); }
    closeAllConnections() { calls.push("close-connections"); }
  }
  const manager = {
    spawnWithExecutor(_pi, _ctx, _kind, _prompt, value) {
      executor = value;
      const record = { promise: queued ? Promise.resolve() : Promise.resolve().then(() => value.execute()) };
      records.set(value.manager_run_id, record);
    },
    getRecord(id) { return records.get(id); },
    consumeControlled(id) { calls.push("consume"); }, removeConsumedControlled(id) { records.delete(id); },
    abort() { calls.push("abort"); void executor.cancel().catch(() => {}); },
  };
  const runtime = { instanceRoot: "/fixture/instance", owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: {
    mcp: { callback_max_seconds: 60, servers: { fixture: { authentication: "oauth", oauth: { grant_type: "authorization_code", redirect_uri: "http://localhost:8765/callback" } } } },
  } } };
  return { server: new Server(), calls, runtime, records, options: { serverName: "fixture", host: "127.0.0.1", port: 8765, path: "/callback" },
    dependencies: { runtime, entry: { manager, pi: {}, getContext: () => ({}) }, setTimer(callback) { deadline = callback; return 1; }, clearTimer() {} },
    timeout() { deadline(); }, executor: () => executor };
}

test("OAuth listener obtains the existing manager before binding and consumes only after close", async () => {
  const f = fixture();
  await listenMcpCallback(f.server, f.options, f.dependencies);
  assert.deepEqual(f.calls[0], ["listen", 8765, "127.0.0.1"]); assert.equal(f.records.size, 1);
  await closeMcpListener(f.server);
  assert.equal(f.server.listening, false); assert.equal(f.records.size, 0);
  assert.equal(f.calls.filter(value => value === "consume").length, 1);
});

test("queued cancellation never binds and unsupported endpoints fail before manager work", async () => {
  const f = fixture({ queued: true });
  const started = listenMcpCallback(f.server, f.options, f.dependencies);
  await new Promise(resolve => setImmediate(resolve)); f.timeout();
  await assert.rejects(started, /CANCELED/);
  assert.equal(f.calls.some(value => Array.isArray(value) && value[0] === "listen"), false);
  for (const changed of [{ port: 9999 }, { host: "0.0.0.0" }, { path: "/unselected" }, { serverName: "unselected" }]) {
    const next = fixture();
    await assert.rejects(listenMcpCallback(next.server, { ...next.options, ...changed }, next.dependencies), /CALLBACK_/);
    assert.equal(next.records.size, 0);
  }
});

test("a close error retains ownership instead of claiming listener termination", async () => {
  const f = fixture({ refuseClose: true });
  await listenMcpCallback(f.server, f.options, f.dependencies);
  await assert.rejects(closeMcpListener(f.server), /TERMINATION_UNKNOWN/);
  assert.equal(f.records.size, 1); assert.equal(f.server.listening, true);
  assert.equal(f.calls.includes("consume"), false);
});

test("MCP App listener pair shares one manager record and waits for owned requests", async () => {
  const { listenMcpApps } = await import("../mcp-listener.ts");
  const f = fixture(), proxy = new f.server.constructor();
  f.runtime.manifest.options.mcp.apps = { enabled: true, browser_network: "user-browser", host_port: 8101, proxy_port: 8102 };
  let release, drained = false;
  const pending = new Promise(resolve => { release = resolve; });
  await listenMcpApps(f.server, proxy, { serverName: "fixture", stop() { f.calls.push("stop-app"); },
    async drain() { await pending; drained = true; } }, f.dependencies);
  assert.equal(f.records.size, 1);
  assert.deepEqual(f.calls.filter(Array.isArray), [["listen", 8101, "127.0.0.1"], ["listen", 8102, "127.0.0.1"]]);
  const closed = closeMcpListener(f.server);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.records.size, 1); assert.equal(drained, false);
  release(); await closed;
  assert.equal(f.records.size, 0); assert.equal(drained, true);
  assert.equal(f.server.listening, false); assert.equal(proxy.listening, false);
});

test("MCP App browser origins and permissions must be explicitly selected", async () => {
  const { validateMcpAppResource } = await import("../mcp-listener.ts");
  const f = fixture(), slot = Symbol.for("agentcfg.pi.runtime.v1"); globalThis[slot] = f.runtime;
  f.runtime.manifest.options.mcp.apps = { enabled: true, browser_network: "user-browser", allowed_browser_origins: ["https://assets.invalid"], permissions: ["clipboardWrite"] };
  try {
    validateMcpAppResource("fixture", { meta: { csp: { resourceDomains: ["https://assets.invalid/js"] }, permissions: { clipboardWrite: {} } } });
    for (const meta of [{ csp: { connectDomains: ["https://unselected.invalid"] } }, { permissions: { camera: {} } },
      { csp: { resourceDomains: ["https://assets.invalid/;connect-src *"] } }]) {
      assert.throws(() => validateMcpAppResource("fixture", { meta }), /MCP_APPS_/);
    }
  } finally { delete globalThis[slot]; }
});

test("request cancellation stops queued binding but does not shorten an established session listener", async () => {
  const queued = fixture({ queued: true }), canceled = new AbortController();
  const start = listenMcpCallback(queued.server, { ...queued.options, startupSignal: canceled.signal }, queued.dependencies);
  await new Promise(resolve => setImmediate(resolve)); canceled.abort();
  await assert.rejects(start, /CANCELED/);
  assert.equal(queued.server.listening, false);
  const f = fixture(), request = new AbortController(), session = new AbortController();
  await listenMcpCallback(f.server, { ...f.options, startupSignal: request.signal, signal: session.signal }, f.dependencies);
  request.abort(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.server.listening, true);
  session.abort(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.server.listening, false); assert.equal(f.records.size, 0);
});
