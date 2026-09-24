import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { AsyncLocalStorage } from "node:async_hooks";
import { createWebCuratorServer, listenWebCurator, closeWebCurator, webCuratorAsset } from "../web-listener.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture({ refuseClose = false } = {}) {
  const calls = [], records = new Map(); let request;
  class Server extends EventEmitter {
    listening = false;
    address() { return { port: 8321 }; }
    listen(port, host, done) { calls.push(["listen", port, host]); this.listening = true; queueMicrotask(done); }
    close(done) { calls.push("close"); if (refuseClose) { done(Error("fixture close failure")); return; } this.listening = false; queueMicrotask(() => done()); }
    closeAllConnections() { calls.push("close-connections"); }
  }
  const runtime = { instanceRoot: "/fixture/instance", owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {
    web: { curator: { enabled: true, browser_network: "user-browser", max_seconds: 60 } },
  } }, web: { scope: new AsyncLocalStorage(), async run(label, signal, callback) { calls.push([label, signal]); return callback(signal); } } };
  const manager = {
    spawnWithExecutor(_pi, _ctx, _kind, _prompt, executor) {
      records.set(executor.manager_run_id, { executor, promise: Promise.resolve().then(() => executor.execute()) });
    }, getRecord: id => records.get(id), consumeControlled() { calls.push("consume"); }, removeConsumedControlled: id => records.delete(id),
    abort(id) { calls.push("abort"); void records.get(id)?.executor.cancel().catch(() => {}); },
  };
  globalThis[slot] = runtime;
  const dependencies = { runtime, entry: { manager, pi: {}, getContext: () => ({}) }, setTimer: () => 1, clearTimer() {} };
  const make = handler => createWebCuratorServer(handler, { runtime, script: () => "fixture browser bundle", serverFactory(callback) { request = callback; return new Server(); } });
  const send = async (server, headers = {}) => {
    const req = new EventEmitter(); req.headers = { host: "127.0.0.1:8321", ...headers };
    const res = new EventEmitter(); res.headers = {}; res.writableEnded = false; res.headersSent = false;
    res.setHeader = (name, value) => { res.headers[name] = value; };
    res.writeHead = status => { res.status = status; res.headersSent = true; };
    res.end = text => { res.body = text; res.writableEnded = true; };
    res.destroy = () => { res.emit("close"); };
    request(req, res); await new Promise(resolve => setImmediate(resolve)); return { req, res };
  };
  return { calls, records, runtime, dependencies, make, send };
}
test("curator uses selected loopback listener and rejects foreign browser origins before handlers", async () => {
  const f = fixture(); let requests = 0;
  const server = f.make(async (_req, res) => { requests++; res.end("fixture page"); });
  try {
    await listenWebCurator(server, undefined, f.dependencies);
    assert.deepEqual(f.calls[0], ["listen", 0, "127.0.0.1"]); assert.equal(f.records.size, 1);
    assert.equal(webCuratorAsset(server), "fixture browser bundle");
    const normal = await f.send(server); assert.equal(normal.res.body, "fixture page");
    assert.equal(normal.res.headers["Referrer-Policy"], "no-referrer");
    const foreign = await f.send(server, { origin: "https://unselected.invalid" });
    assert.equal(foreign.res.status, 403); assert.equal(requests, 1);
    const host = await f.send(server, { host: "unselected.invalid:8321" }); assert.equal(host.res.status, 403);
    await closeWebCurator(server); assert.equal(f.records.size, 0);
  } finally { delete globalThis[slot]; }
});
test("listener shutdown aborts requests and retains ownership until request work settles", async () => {
  const f = fixture(); let resolveRequest;
  const server = f.make(() => new Promise(resolve => { resolveRequest = resolve; }));
  try {
    await listenWebCurator(server, undefined, f.dependencies); await f.send(server);
    const close = closeWebCurator(server); await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.find(row => Array.isArray(row) && row[0] === "curator-request")[1].aborted, true);
    assert.equal(f.records.size, 1);
    resolveRequest(); await close; assert.equal(f.records.size, 0);
  } finally { delete globalThis[slot]; }
});
test("curator cannot bind when unselected or report success for unknown close", async () => {
  const f = fixture({ refuseClose: true });
  try {
    f.runtime.manifest.options.web.curator.enabled = false;
    assert.throws(() => f.make(async () => {}), /NOT_SELECTED/);
    f.runtime.manifest.options.web.curator.enabled = true;
    const server = f.make(async () => {}); await listenWebCurator(server, undefined, f.dependencies);
    await assert.rejects(closeWebCurator(server), /TERMINATION_UNKNOWN/);
    assert.equal(f.records.size, 1); assert.equal(server.listening, true);
    assert.equal(f.calls.includes("consume"), false);
  } finally { delete globalThis[slot]; }
});

test("remote curator requires an explicit advertised origin and keeps exact Host/Origin checks", async () => {
  const f = fixture();
  f.runtime.manifest.options.web.curator.bind = "0.0.0.0";
  try {
    assert.throws(() => f.make(async () => {}), /BINDING_INVALID/);
    f.runtime.manifest.options.web.curator.advertised_origin = "https://curator.example.invalid";
    const server = f.make(async (_req, res) => { res.end("remote fixture page"); });
    await listenWebCurator(server, undefined, f.dependencies);
    assert.deepEqual(f.calls[0], ["listen", 0, "0.0.0.0"]);
    const { webCuratorUrl, webCuratorLinkAllowed } = await import("../web-listener.ts");
    const url = webCuratorUrl(server, "fixture-session");
    assert.equal(url, "https://curator.example.invalid/?session=fixture-session"); assert.equal(webCuratorLinkAllowed(url), true);
    assert.equal(webCuratorLinkAllowed("https://unselected.invalid/?session=fixture-session"), false);
    assert.equal((await f.send(server, { host: "curator.example.invalid", origin: "https://curator.example.invalid" })).res.body, "remote fixture page");
    assert.equal((await f.send(server, { host: "127.0.0.1:8321" })).res.status, 403);
    await closeWebCurator(server); assert.equal(webCuratorLinkAllowed(url), false);
  } finally { delete globalThis[slot]; }
});
