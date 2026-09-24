import assert from "node:assert/strict";
import { test } from "node:test";
import { serviceExtensions, exerciseServices } from "../service-validation.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), managerSlot = Symbol.for("agentcfg.pi.managed.v1");

test("service scopes exclude other service factories and project extensions", () => {
  const manifest = { plugins: ["pi-subagents", "pi-permissions", "pi-mcp", "pi-web"], resource_ids: { extensions: { "gentle-agent-state": "fixture" } } };
  const installed = { resources: { extensions: manifest.plugins.map(id => ({ id, capability_id: id })) } };
  assert.deepEqual(serviceExtensions(manifest, installed, "mcp"), ["pi-mcp", "pi-permissions", "pi-subagents"]);
  assert.deepEqual(serviceExtensions(manifest, installed, "terminal"), ["gentle-agent-state", "pi-permissions", "pi-subagents"]);
  assert.throws(() => serviceExtensions(manifest, installed, "invented"), /SERVICE_VALIDATION_UNKNOWN/);
});

test("MCP validation reconnects selected servers and rejects cache-only discovery", async () => {
  let cached = false; const calls = [];
  const tool = { execute: async (_id, params) => {
    calls.push(params);
    return { details: params.connect ? { mode: "list", server: params.connect, count: 1, cached }
      : { mode: "status", servers: [{ name: "fixture", status: "connected" }] }, content: [{ type: "text", text: "synthetic private service body" }] };
  } };
  const host = { session: { bindExtensions: async () => {}, extensionRunner: { createContext: () => ({}), getToolDefinition: () => tool } } };
  try {
    globalThis[slot] = { supervisor: {}, manifest: { options: { mcp: { servers: { fixture: {} } } } } };
    globalThis[managerSlot] = { manager: { hasRunning: () => false } };
    const facts = await exerciseServices(host, { capability: "mcp" });
    assert.equal(facts.mcp_servers_verified, 1);
    assert.deepEqual(calls, [{ connect: "fixture" }, {}]);
    assert.equal(JSON.stringify(facts).includes("private"), false);
    cached = true;
    await assert.rejects(exerciseServices(host, { capability: "mcp" }), /SERVICE_VALIDATION_MCP_METADATA/);
  } finally { delete globalThis[slot]; delete globalThis[managerSlot]; }
});

test("web validation chooses explicit providers without fallback, curation, or background fetches", async () => {
  const calls = [];
  const host = { session: { bindExtensions: async () => {}, extensionRunner: { createContext: () => ({}), getToolDefinition: name => {
    assert.equal(name, "web_search"); return { execute: async (_id, params) => { calls.push(params); return { details: { successfulQueries: 1, totalResults: 1 } }; } };
  } } } };
  try {
    const web = { providers: ["brave"], services: { brave: {} } };
    globalThis[slot] = { supervisor: {}, manifest: { options: { web } } };
    globalThis[managerSlot] = { manager: { hasRunning: () => false } };
    assert.equal((await exerciseServices(host, { capability: "web" })).web_providers_verified, 1);
    assert.equal(calls[0].provider, "brave"); assert.equal(calls[0].includeContent, false); assert.equal(calls[0].workflow, "none");
    web.providers = ["auto"];
    await assert.rejects(exerciseServices(host, { capability: "web" }), /SERVICE_VALIDATION_WEB_SELECTION/);
  } finally { delete globalThis[slot]; delete globalThis[managerSlot]; }
});

test("terminal validation requires three acknowledged scoped service calls", async () => {
  const states = [];
  const runtime = { owner: { role: "manager" }, manifest: { resource_ids: { extensions: { "gentle-agent-state": "fixture" } }, options: { agent_state: { mode: "service" } } },
    supervisor: { call: async (method, value) => { if (method === "ordinary_service_prepare") states.push(value.state); return {}; } },
    ordinaryOperations: { write: async () => ({ exitCode: 0, truncated: false, terminationConfirmed: true }) } };
  const host = { session: { bindExtensions: async () => {}, extensionRunner: { createContext: () => ({ hasUI: false }) } } };
  try {
    globalThis[slot] = runtime; globalThis[managerSlot] = { manager: { hasRunning: () => false } };
    assert.equal((await exerciseServices(host, { capability: "terminal" })).terminal_reports_acknowledged, 3);
    assert.deepEqual(states, ["working", "blocked", "idle"]);
    runtime.manifest.options.agent_state.mode = "osc";
    await assert.rejects(exerciseServices(host, { capability: "terminal" }), /SERVICE_VALIDATION_TERMINAL_BINDING/);
  } finally { delete globalThis[slot]; delete globalThis[managerSlot]; }
});
