import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { cliProxyTarget, connectCliTarget } from "../web-cli-proxy.ts";
function runtime() { return { manifest: { web_services: { public: { type: "public" }, github: { type: "api", origins: ["https://github.com"] } } } }; }
test("CLI tunnel targets are declared HTTPS destinations with checked public DNS", async () => {
  const r = runtime();
  const target = await cliProxyTarget(r, "public", "example.invalid:443", { lookup: async () => [{ address: "8.8.8.8", family: 4 }] });
  assert.equal(target.address, "8.8.8.8"); assert.equal(target.hostname, "example.invalid");
  await assert.rejects(cliProxyTarget(r, "public", "example.invalid:443", { lookup: async () => [{ address: "127.0.0.1", family: 4 }] }), /ADDRESS/);
  for (const authority of ["user:secret@example.invalid", "example.invalid:22", "example.invalid/path"]) {
    await assert.rejects(cliProxyTarget(r, "public", authority), /INVALID/);
  }
  await assert.rejects(cliProxyTarget(r, "github", "unselected.invalid:443"), /ORIGIN_DENIED/);
});
test("CLI tunnel proxy authentication stays on the selected proxy and failure never connects directly", async () => {
  const calls = [], controller = new AbortController();
  class Socket extends EventEmitter {
    constructor() { super(); queueMicrotask(() => this.emit("connect")); }
    write(value) { calls.push(value); queueMicrotask(() => this.emit("data", Buffer.from("HTTP/1.1 407 Rejected\r\n\r\n"))); }
    destroy() { this.destroyed = true; }
    pause() {}
  }
  await assert.rejects(connectCliTarget({ address: "8.8.8.8", port: 443 }, { mode: "proxy", proxy_url: "http://127.0.0.1:8123" },
    { signal: controller.signal, authorization: "Basic synthetic", connect(options) { calls.push(options); return new Socket(); } }), /PROXY_FAILED/);
  assert.equal(calls.filter(value => typeof value === "object").length, 1);
  assert.deepEqual(calls[0], { host: "127.0.0.1", port: 8123 }); assert.match(calls[1], /CONNECT 8\.8\.8\.8:443/);
  assert.match(calls[1], /Proxy-Authorization: Basic synthetic/);
});
test("canceling a CLI destination lookup prevents a late DNS result from authorizing a connection", async () => {
  const controller = new AbortController(); let resolve;
  const request = cliProxyTarget(runtime(), "public", "example.invalid", { signal: controller.signal, lookup: () => new Promise(done => { resolve = done; }) });
  controller.abort(); await assert.rejects(request, /ABORTED/); resolve([{ address: "8.8.8.8", family: 4 }]);
});

test("successful upstream CONNECT preserves binary bytes following the response headers", async () => {
  const bytes = Buffer.alloc(40000, 0x16);
  class Socket extends EventEmitter {
    constructor() { super(); queueMicrotask(() => this.emit("connect")); }
    write() { queueMicrotask(() => this.emit("data", Buffer.concat([Buffer.from("HTTP/1.1 200 Connection Established\r\n\r\n"), bytes]))); }
    destroy() { this.destroyed = true; }
    pause() { this.paused = true; }
    unshift(value) { assert.equal(this.paused, true); this.remaining = value; }
  }
  const socket = await connectCliTarget({ address: "8.8.8.8", port: 443 }, { mode: "proxy", proxy_url: "http://127.0.0.1:8123" },
    { signal: new AbortController().signal, connect: () => new Socket() });
  assert.deepEqual(socket.remaining, bytes); assert.notEqual(socket.destroyed, true);
});

test("owned CLI proxy authenticates before connection and is reclaimed by the Web operation", async () => {
  const { createCliProxy } = await import("../web-cli-proxy.ts");
  const slot = Symbol.for("agentcfg.pi.runtime.v1"), operation = { id: "fixture-operation", controller: new AbortController(), transports: new Map() };
  const r = runtime(); r.owner = { role: "manager" }; r.manifest.plugins = ["pi-web"];
  r.manifest.options = { network: { routes: { selected: { mode: "proxy", proxy_url: "http://127.0.0.1:8123", service_ids: ["web:public"] } } } };
  r.manifest.web_services.public.network_route = "selected"; r.web = { current: () => operation };
  const calls = []; let server;
  class Socket extends EventEmitter {
    writes = [];
    write(value) { this.writes.push(value); }
    pipe() {}
    resume() {}
    destroy() { if (!this.destroyed) { this.destroyed = true; this.emit("close"); } }
  }
  class Server extends EventEmitter {
    listen(_path, done) { queueMicrotask(done); }
    close(done) { done(); }
  }
  globalThis[slot] = r;
  try {
    const proxy = await createCliProxy(r, "public", "/fixture/private.sock", { authorize: async () => true, validateSocketPath: async () => {},
      lookup: async () => [{ address: "8.8.8.8", family: 4 }], serverFactory() { return server = new Server(); },
      connector: async (...args) => { calls.push(args); return new Socket(); } });
    const invalid = new Socket(); server.emit("connect", { url: "example.invalid:443", headers: {} }, invalid, Buffer.alloc(0));
    await new Promise(resolve => setImmediate(resolve)); assert.equal(calls.length, 0); assert.equal(invalid.destroyed, true);
    const client = new Socket();
    server.emit("connect", { url: "example.invalid:443", headers: { "proxy-authorization": "Basic " + Buffer.from("agentcfg:" + proxy.token).toString("base64") } }, client, Buffer.alloc(0));
    await new Promise(resolve => setImmediate(resolve)); assert.equal(calls.length, 1); assert.match(client.writes[0], /200 Connection Established/);
    assert.equal(operation.transports.size, 1);
    await (await [...operation.transports.values()][0]).close(); assert.equal(client.destroyed, true);
  } finally { delete globalThis[slot]; }
});
