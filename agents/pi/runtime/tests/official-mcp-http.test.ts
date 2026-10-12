import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialMcpHttpTransport } from "../official-mcp-http.ts";

function setup() {
  const state = { checks: 0, connects: 0, requests: 0, fetchCloses: 0, closes: 0 };
  const headers = { Authorization: "" }, entry = { name: "docs", config: { type: "http", url: "https://mcp.invalid", headers } };
  const runtime = { manifest: { native_mcp: { bindings: { docs: { transport: "streamable-http", authentication: "none" } } } } };
  const check = () => { state.checks++; if (state.stale) throw Error("PRIVATE"); };
  class Http {
    constructor(options) { state.options = options; state.handlers = {}; }
    onMessage(fn) { state.handlers.message = fn; return () => {}; }
    onError(fn) { state.handlers.error = fn; return () => {}; }
    onClose(fn) { state.handlers.close = fn; return () => {}; }
    async start() { state.connects++; }
    async send(message) { await state.options.fetch("https://mcp.invalid", { body: JSON.stringify(message) }); }
    setProtocolVersion(value) { state.version = value; }
    async close() { state.closes++; state.handlers.close(); }
  }
  const fetch = async () => { state.requests++; if (state.afterFetch) await state.afterFetch(); return new Response("{}"); };
  fetch.close = () => state.fetchCloses++;
  const fetchFactory = async () => { if (state.prepare) await state.prepare(); return fetch; };
  const options = { runtime, serverName: "docs", entry, mcpModule: { StreamableHttpTransport: Http }, check, fetchFactory };
  return { state, options, transport: createOfficialMcpHttpTransport(options) };
}
test("HTTP is lazy, uses original controlled fetch and explicit bounded public options", async () => {
  const f = setup(); assert.equal(f.state.connects, 0); assert.equal(f.state.options, undefined);
  f.transport.setProtocolVersion("2025-03-26"); await f.transport.start();
  assert.equal(f.state.version, "2025-03-26");
  assert.equal(f.state.options.openGetStream, false); assert.equal(f.state.options.maxMessageBytes, 1048576);
  assert.deepEqual(f.state.options.reconnect, { maxRetries: 0 }); assert.equal(f.state.options.authProvider, undefined);
  await f.transport.send({ jsonrpc: "2.0", id: 1, method: "initialize" }); assert.equal(f.state.requests, 1);
  await f.transport.close(); await f.transport.close(); assert.equal(f.state.closes, 1);
  await assert.rejects(f.transport.send({}), /MCP_/);
});
test("only subscribed public callbacks run and raw errors are sanitized", async () => {
  const f = setup(), messages = [], errors = [], closes = [];
  const off = f.transport.onMessage(value => messages.push(value));
  f.transport.onError(error => errors.push(error.message)); f.transport.onClose(() => closes.push(true));
  await f.transport.start(); f.state.handlers.message({ value: 1 }); off(); f.state.handlers.message({ value: 2 });
  f.state.handlers.error(Error("PRIVATE"));
  assert.deepEqual(messages, [{ value: 1 }]); assert.deepEqual(errors, ["MCP_HTTP_TRANSPORT_FAILED"]);
  await f.transport.close(); assert.equal(closes.length, 1); f.state.handlers.message({ value: 3 }); assert.equal(messages.length, 1);
});
test("close while controlled fetch initializes closes its late result without connecting", async () => {
  const f = setup(); let done;
  f.state.prepare = () => new Promise(resolve => { done = resolve; });
  const start = f.transport.start(), failure = assert.rejects(start, /MCP_/);
  const close = f.transport.close(); done(); await failure; await close;
  assert.equal(f.state.connects, 0); assert.ok(f.state.fetchCloses > 0);
});
test("context changes during fetch prevent result acceptance", async () => {
  const f = setup(); await f.transport.start(); f.state.afterFetch = () => { f.state.stale = true; };
  await assert.rejects(f.transport.send({ jsonrpc: "2.0" }), error => { assert.equal(error.message, "MCP_HTTP_TRANSPORT_FAILED"); return true; });
  await f.transport.close(); assert.equal(f.state.closes, 1);
});
for (const fault of ["sse", "oauth", "name", "constructor"]) test("unsupported " + fault + " fails before setup IO", () => {
  const f = setup();
  if (fault === "sse") f.options.runtime.manifest.native_mcp.bindings.docs.transport = "sse";
  else if (fault === "oauth") f.options.runtime.manifest.native_mcp.bindings.docs.authentication = "oauth";
  else if (fault === "name") f.options.entry.name = "other";
  else f.options.mcpModule = {};
  assert.throws(() => createOfficialMcpHttpTransport(f.options), /MCP_HTTP_TRANSPORT_UNAVAILABLE/);
  assert.equal(f.state.options, undefined); assert.equal(f.state.requests, 0);
});
