import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { mcpHttpFetch } from "../mcp-http.ts";

test("MCP HTTP uses only its explicit proxy/origin and cannot turn redirects or failures into direct calls", async () => {
  const calls = [], runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"],
    options: { mcp: { servers: { fixture: { transport: "streamable-http", network_route: "bound" } } },
      network: { routes: { bound: { mode: "proxy", proxy_url: "http://proxy.invalid:8123", provider_ids: [], service_ids: ["mcp:fixture"] } } } },
    mcp_config: { mcpServers: { fixture: { url: "https://mcp.invalid/service", auth: false } } } } };
  let status = 200, failure = false, agentClosed = false;
  const agent = { destroy() { agentClosed = true; } };
  const fetch = await mcpHttpFetch(runtime, "fixture", {
    proxyAgent: async (url, protocol) => { assert.equal(url, "http://proxy.invalid:8123"); assert.equal(protocol, "https:"); return agent; },
    httpRequest: () => assert.fail("direct fallback forbidden"),
    httpsRequest(url, options, done) {
      calls.push({ url, options });
      const request = new EventEmitter(); request.destroy = () => request.emit("close");
      request.end = body => {
        calls.at(-1).body = body.toString();
        if (failure) { request.emit("error", Error("synthetic secret")); return; }
        const response = new PassThrough(); response.statusCode = status; response.headers = {};
        done(response); response.end(status === 204 ? undefined : "fixture response");
      };
      return request;
    },
  });
  try {
    const result = await fetch("https://mcp.invalid/service", { method: "POST", body: "{}", headers: { authorization: "unselected" } });
    assert.equal(await result.text(), "fixture response");
    assert.equal(calls[0].options.agent, agent);
    assert.equal(calls[0].options.headers.authorization, undefined);
    await assert.rejects(fetch("https://different.invalid/service"), /ROUTE_MISMATCH/);
    status = 302; await assert.rejects(fetch("https://mcp.invalid/service"), /REDIRECT_FORBIDDEN/);
    status = 204; assert.equal((await fetch("https://mcp.invalid/service", { method: "DELETE" })).status, 204);
    failure = true; await assert.rejects(fetch("https://mcp.invalid/service"), /^Error: MCP_HTTP_TRANSPORT_FAILED$/);
  } finally { fetch.close(); }
  assert.equal(agentClosed, true); assert.equal(calls.length, 4);
  await assert.rejects(fetch("https://mcp.invalid/service"), /ROUTE_MISMATCH/);
});

test("Base native MCP uses its own capability and never observes Full manager", async () => {
  const slot = Symbol.for("agentcfg.pi.managed.v1"), original = Object.getOwnPropertyDescriptor(globalThis, slot);
  Object.defineProperty(globalThis, slot, { configurable: true, get() { assert.fail("Base inspected Full manager"); } });
  const runtime = { owner: { role: "manager" }, manifest: { profile_id: "pi-base", plugins: [], native_mcp: { schema_version: 1 },
    options: { mcp: { servers: { fixture: { transport: "streamable-http", network_route: "bound" } } },
      network: { routes: { bound: { mode: "direct", provider_ids: [], service_ids: ["mcp:fixture"] } } } },
    mcp_config: { mcpServers: { fixture: { url: "https://mcp.invalid/service", auth: false } } } } };
  try {
    const fetch = await mcpHttpFetch(runtime, "fixture", { httpsRequest: () => assert.fail("default test opened network") });
    fetch.close();
  } finally { if (original) Object.defineProperty(globalThis, slot, original); else delete globalThis[slot]; }
});

test("MCP bounds streaming uploads before dispatch and close cancels an unfinished body", async () => {
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"],
    options: { mcp: { servers: { fixture: { transport: "streamable-http", network_route: "bound" } } },
      network: { routes: { bound: { mode: "direct", provider_ids: [], service_ids: ["mcp:fixture"] } } } },
    mcp_config: { mcpServers: { fixture: { url: "https://mcp.invalid/service", auth: false } } } } };
  const fetch = await mcpHttpFetch(runtime, "fixture", { httpsRequest: () => assert.fail("body never admitted") });
  let pulls = 0, cancelled = false;
  const large = new ReadableStream({
    pull(controller) { pulls++; controller.enqueue(new Uint8Array(512 * 1024)); },
    cancel() { cancelled = true; },
  });
  await assert.rejects(fetch("https://mcp.invalid/service", { method: "POST", body: large, duplex: "half" }), /MCP_REQUEST_OVERSIZE/);
  assert.equal(cancelled, true); assert.ok(pulls <= 4);
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const waiting = new ReadableStream({ pull() { started(); return new Promise(() => {}); }, cancel() { cancelled = true; } });
  cancelled = false;
  const pending = fetch("https://mcp.invalid/service", { method: "POST", body: waiting, duplex: "half" });
  await ready;
  fetch.close();
  await assert.rejects(pending, /MCP_REQUEST_ABORTED/);
  assert.equal(cancelled, true);
});

test("OAuth discovery uses only declared origins and never forwards a service bearer across origins", async () => {
  const calls = [];
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: {
    mcp: { servers: { fixture: { transport: "streamable-http", authentication: "oauth", network_route: "bound",
      oauth: { allowed_origins: ["https://auth.invalid"] } } } },
    network: { routes: { bound: { mode: "direct", provider_ids: [], service_ids: ["mcp:fixture"] } } },
  }, mcp_config: { mcpServers: { fixture: { url: "https://mcp.invalid/service", auth: "oauth" } } } } };
  const fetch = await mcpHttpFetch(runtime, "fixture", { httpsRequest(url, options, done) {
    calls.push({ url, options });
    const request = new EventEmitter(); request.destroy = () => request.emit("close");
    request.end = () => { const response = new PassThrough(); response.statusCode = 200; response.headers = {}; done(response); response.end("{}"); };
    return request;
  } });
  try {
    await (await fetch("https://mcp.invalid/service", { headers: { authorization: "Bearer fixture-service" } })).text();
    await (await fetch("https://auth.invalid/metadata", { headers: { authorization: "Bearer fixture-service" } })).text();
    await (await fetch("https://auth.invalid/token", { method: "POST", headers: { authorization: "Basic fixture-client" }, body: "grant_type=client_credentials" })).text();
    await assert.rejects(fetch("https://unselected.invalid/token"), /ROUTE_MISMATCH/);
    assert.equal(calls[0].options.headers.authorization, "Bearer fixture-service");
    assert.equal(calls[1].options.headers.authorization, undefined);
    assert.equal(calls[2].options.headers.authorization, "Basic fixture-client");
    assert.equal(calls.length, 3);
  } finally { fetch.close(); }
});

test("Base bearer fetch injects only its selected private slot and rejects missing credentials before dispatch", async () => {
  const variable = "AGENTCFG_PI_CREDENTIAL_SYNTHETIC_MCP", foreign = "AGENTCFG_PI_CREDENTIAL_FOREIGN_MCP";
  const previous = process.env[variable], previousForeign = process.env[foreign], calls = [];
  const runtime = { owner: { role: "manager" }, manifest: { profile_id: "pi-base", plugins: [], native_mcp: { schema_version: 1 },
    options: { mcp: { servers: { fixture: { transport: "streamable-http", authentication: "bearer", network_route: "bound" } } },
      network: { routes: { bound: { mode: "direct", provider_ids: [], service_ids: ["mcp:fixture"] } } } },
    mcp_config: { mcpServers: { fixture: { url: "https://mcp.invalid/service", auth: "bearer", bearerTokenEnv: variable } } } } };
  process.env[variable] = "SYNTHETIC-SELECTED-TOKEN";
  process.env[foreign] = "SYNTHETIC-FOREIGN-TOKEN";
  const fetch = await mcpHttpFetch(runtime, "fixture", {
    httpRequest: () => assert.fail("bearer transport changed protocol"),
    httpsRequest(url, options, done) {
      calls.push({ url, options });
      const request = new EventEmitter(); request.destroy = () => request.emit("close");
      request.end = () => {
        const response = new PassThrough(); response.statusCode = 200; response.headers = {};
        done(response); response.end("{}");
      };
      return request;
    },
  });
  try {
    await (await fetch("https://mcp.invalid/service", { headers: { authorization: "Bearer MODEL-PROVIDED", "proxy-authorization": "UNSELECTED" } })).text();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.headers.authorization, "Bearer SYNTHETIC-SELECTED-TOKEN");
    assert.equal(calls[0].options.headers["proxy-authorization"], undefined);
    assert.equal(calls[0].options.agent, false);
    await assert.rejects(fetch("https://foreign.invalid/service"), error => error.code === "MCP_HTTP_ROUTE_MISMATCH");
    delete process.env[variable];
    await assert.rejects(fetch("https://mcp.invalid/service"), error => error.code === "MCP_CREDENTIAL_REQUIRED" && error.exitCode === 3 && !error.message.includes("TOKEN"));
    process.env[variable] = "SYNTHETIC\r\nINVALID";
    await assert.rejects(fetch("https://mcp.invalid/service"), error => error.code === "MCP_CREDENTIAL_REQUIRED");
    assert.equal(calls.length, 1);
    runtime.manifest.options.network.routes.bound.service_ids = ["mcp:foreign"];
    await assert.rejects(mcpHttpFetch(runtime, "fixture"), error => error.code === "MCP_HTTP_BINDING_REQUIRED");
  } finally {
    fetch.close();
    if (previous === undefined) delete process.env[variable]; else process.env[variable] = previous;
    if (previousForeign === undefined) delete process.env[foreign]; else process.env[foreign] = previousForeign;
  }
});
