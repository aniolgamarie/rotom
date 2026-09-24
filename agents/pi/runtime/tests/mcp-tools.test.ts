import assert from "node:assert/strict";
import { test } from "node:test";
import { captureMcpToolOwner, registerMcpTool, registerMcpNamespace, unregisterMcpTool, isBoundMcpTool } from "../mcp-tools.ts";
import { OrdinaryOperations } from "../ordinary-operations.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  return { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: { mcp: { servers: {
    docs: { direct_tools: { enabled: true, tools: ["search"] } }, other: { direct_tools: { enabled: true } }, grouped: { direct_tools: { enabled: false } },
  } } } } };
}

test("MCP direct tools require registered ownership, exact selection and main role", async () => {
  const runtime = fixture(); globalThis[slot] = runtime; let calls = 0;
  try {
    const owner = captureMcpToolOwner();
    const execute = registerMcpTool("docs_search", "docs", "search", async () => ++calls, owner);
    const ops = new OrdinaryOperations({}, runtime);
    assert.deepEqual(await ops.preflight({ toolName: "docs_search" }, {}, {}, "main"), { kind: "service", tool_name: "docs_search" });
    await assert.rejects(ops.preflight({ toolName: "docs_search" }, {}, {}, "reviewer"), /ROLE_CEILING/);
    await assert.rejects(ops.preflight({ toolName: "mcp__invented" }, {}, {}, "main"), /ORDINARY_TOOL_NOT_BOUND/);
    assert.equal(await execute(), 1);
    assert.throws(() => registerMcpTool("docs_write", "docs", "write", () => {}), /UNSELECTED/);
    assert.throws(() => registerMcpTool("bash", "other", "bash", () => {}), /TOOL_NAME/);
    assert.throws(() => registerMcpTool("readSeek_write", "other", "write", () => {}), /TOOL_NAME/);
    assert.throws(() => registerMcpTool("docs_search", "other", "search", () => {}), /CONFLICT/);
    unregisterMcpTool("docs_search", owner);
    assert.equal(isBoundMcpTool(runtime, "docs_search"), false);
    await assert.rejects(execute(), /STALE/); assert.equal(calls, 1);
  } finally { delete globalThis[slot]; }
});

test("namespace proxies keep their selected service and old registrations cannot survive replacement", async () => {
  const runtime = fixture(); globalThis[slot] = runtime;
  try {
    const old = registerMcpNamespace("mcp__grouped", "grouped", async () => "old");
    const current = registerMcpNamespace("mcp__grouped", "grouped", async () => "current");
    await assert.rejects(old(), /STALE/); assert.equal(await current(), "current");
    runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    await assert.rejects(current(), /UNMETERED_PARENT_HELPER/);
    delete runtime.managedRequestScope; delete runtime.manifest.options.mcp.servers.grouped;
    await assert.rejects(current(), /UNSELECTED/);
  } finally { delete globalThis[slot]; }
});


test("old adapter cleanup cannot unregister another runtime or adapter generation", async () => {
  const first = fixture(); globalThis[slot] = first;
  try {
    const owner = captureMcpToolOwner();
    const old = registerMcpTool("docs_search", "docs", "search", async () => "old", owner);
    unregisterMcpTool("docs_search", owner);
    const nextOwner = captureMcpToolOwner();
    const next = registerMcpTool("docs_search", "docs", "search", async () => "next", nextOwner);
    unregisterMcpTool("docs_search", owner);
    assert.equal(await next(), "next"); await assert.rejects(old(), /STALE/);
    const second = fixture(); globalThis[slot] = second;
    const current = registerMcpTool("docs_search", "docs", "search", async () => "current");
    unregisterMcpTool("docs_search", nextOwner);
    assert.equal(await current(), "current");
    await assert.rejects(next(), /STALE/);
  } finally { delete globalThis[slot]; }
});
