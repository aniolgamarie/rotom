import assert from "node:assert/strict";
import { test } from "node:test";
import { addressPolicy } from "../web-address.ts";
import { createWebFetch } from "../web-http.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture(mode = "direct", type = "public") {
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: { network: { routes: {
    route: { mode, service_ids: ["web:fixture"], ...(mode === "proxy" ? { proxy_url: "http://127.0.0.1:8123" } : {}) },
  } } }, web_services: { fixture: { type, network_route: "route", ...(type === "api" ? { origins: ["https://api.example.invalid"] } : {}) } } } };
  globalThis[slot] = runtime;
  const calls = [], dispatchers = []; let destroyed = 0;
  return { runtime, calls, dispatchers, destroyed: () => destroyed, options: {
    lookup: async () => [{ address: "93.184.216.34", family: 4 }],
    dispatcherFactory: async options => { dispatchers.push(options); return { async destroy() { destroyed++; } }; },
    fetchImpl: async (url, options) => { calls.push({ url, options }); return new Response("synthetic public content"); },
  } };
}

test("public web requests pin checked DNS addresses and preserve Host/TLS identity through a selected proxy", async () => {
  const f = fixture("proxy"); let fetch;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", f.options);
    const response = await fetch("https://docs.example.invalid/path", { headers: { authorization: "must not forward", cookie: "must not forward" } });
    assert.equal(await response.text(), "synthetic public content");
    assert.equal(f.calls[0].url, "https://93.184.216.34/path");
    assert.equal(f.calls[0].options.headers.host, "docs.example.invalid");
    assert.equal(f.calls[0].options.headers.authorization, undefined);
    assert.equal(f.calls[0].options.headers.cookie, undefined);
    assert.equal(f.dispatchers[0].servername, "docs.example.invalid");
    assert.equal(f.dispatchers[0].route.mode, "proxy");
    assert.equal(response.url, "https://docs.example.invalid/path");
    assert.equal(f.destroyed(), 1);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});

test("private, rebinding and mapped/NAT64 private addresses are rejected before network dispatch", async () => {
  const check = addressPolicy();
  for (const address of ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "::127.0.0.1"]) {
    assert.throws(() => check(address), /PRIVATE_ADDRESS/);
  }
  addressPolicy(["198.18.0.0/15"])("198.18.1.2");
  assert.throws(() => addressPolicy(["0.0.0.0/0"]), /POLICY_INVALID/);
  const f = fixture(); let fetch;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", { ...f.options, lookup: async () => [
      { address: "93.184.216.34", family: 4 }, { address: "127.0.0.1", family: 4 }] });
    await assert.rejects(fetch("https://mixed.example.invalid"), /PRIVATE_ADDRESS/);
    assert.equal(f.calls.length, 0); assert.equal(f.dispatchers.length, 0);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});

test("proxy failures latch, never fall back to ambient fetch, and request-supplied dispatchers are refused", async () => {
  const f = fixture("proxy"); let fetch;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", { ...f.options, fetchImpl: async (...args) => {
      f.calls.push(args); throw new Error("synthetic private proxy diagnostic");
    } });
    await assert.rejects(fetch("https://docs.example.invalid"), /^Error: WEB_PROXY_FAILED$/);
    await assert.rejects(fetch("https://second.example.invalid"), /WEB_PROXY_FAILED/);
    assert.equal(f.calls.length, 1); assert.equal(f.destroyed(), 1);
    await assert.rejects(fetch("https://docs.example.invalid", { __proxy: "" }), /OVERRIDE_UNBOUND/);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});

test("API requests keep credentials only on declared origins and public redirects recheck their destination", async () => {
  const f = fixture("direct", "api"); let fetch;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", f.options);
    await assert.rejects(fetch("https://unselected.example.invalid", { headers: { authorization: "synthetic" } }), /ORIGIN_DENIED/);
    assert.equal(f.calls.length, 0);
    assert.equal(await (await fetch("https://api.example.invalid/search", { headers: { authorization: "synthetic" } })).text(), "synthetic public content");
    assert.equal(f.calls[0].options.headers.authorization, "synthetic");
  } finally { await fetch?.close(); delete globalThis[slot]; }
  const next = fixture();
  try {
    fetch = await createWebFetch(next.runtime, "fixture", { ...next.options, fetchImpl: async (...args) => {
      next.calls.push(args); return new Response(null, { status: 302, headers: { location: "http://127.0.0.1/private" } });
    } });
    await assert.rejects(fetch("https://docs.example.invalid"), /PRIVATE_ADDRESS/);
    assert.equal(next.calls.length, 1);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});

test("response limits and close settle the owned dispatcher, and late DNS cannot send after close", async () => {
  const f = fixture(); f.runtime.manifest.web_services.fixture.max_response_bytes = 4; let fetch;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", f.options);
    await assert.rejects((await fetch("https://docs.example.invalid")).text(), /BODY_FAILED/);
    assert.equal(f.destroyed(), 1);
  } finally { await fetch?.close(); delete globalThis[slot]; }
  const next = fixture(); let release, entered;
  const pending = new Promise(resolve => { entered = resolve; });
  try {
    fetch = await createWebFetch(next.runtime, "fixture", { ...next.options, lookup: async () => {
      entered(); await new Promise(resolve => { release = resolve; }); return [{ address: "93.184.216.34", family: 4 }];
    } });
    const result = fetch("https://docs.example.invalid"); await pending; await fetch.close(); release();
    await assert.rejects(result, /CLOSED|ABORTED/); assert.equal(next.calls.length, 0);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});

test("canceling during DNS rejects promptly and never dispatches the later result", async () => {
  const f = fixture(); const abort = new AbortController(); let fetch, release;
  try {
    fetch = await createWebFetch(f.runtime, "fixture", { ...f.options, lookup: () => new Promise(resolve => { release = resolve; }) });
    const pending = fetch("https://docs.example.invalid", { signal: abort.signal });
    abort.abort(); await assert.rejects(pending, /ABORTED/);
    release([{ address: "93.184.216.34", family: 4 }]);
    assert.equal(f.calls.length, 0); assert.equal(f.dispatchers.length, 0);
  } finally { await fetch?.close(); delete globalThis[slot]; }
});
