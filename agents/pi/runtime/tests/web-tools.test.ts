import assert from "node:assert/strict";
import { test } from "node:test";
import { bindWebTools, isBoundWebTool } from "../web-tools.ts";
import { registerMcpTool, unregisterMcpTool, captureMcpToolOwner } from "../mcp-tools.ts";
import { OrdinaryOperations } from "../ordinary-operations.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const tools = new Map(), calls = [], controller = new AbortController();
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web", "pi-mcp"], options: {
    mcp: { servers: { docs: { direct_tools: { enabled: true } } } },
  } }, web: { async run(name, signal, callback) { calls.push({ name, signal }); return callback(controller.signal); } } };
  globalThis[slot] = runtime;
  const binding = bindWebTools({ registerTool(tool) { tools.set(tool.name, tool); } });
  return { tools, runtime, calls, controller, binding };
}
const definition = (name, execute = async () => "result") => ({ name, parameters: { type: "object" }, execute });
test("registered web tools require main role, manager ownership and a closed parameter schema", async () => {
  const f = fixture(); let observed;
  try {
    f.binding.registerTool(definition("web_search", async (_id, _params, signal) => { observed = signal; return "ok"; }));
    const tool = f.tools.get("web_search"), ops = new OrdinaryOperations({}, f.runtime);
    assert.equal(tool.parameters.additionalProperties, false);
    assert.deepEqual(await ops.preflight({ toolName: "web_search" }, {}, {}, "main"), { kind: "service", tool_name: "web_search" });
    await assert.rejects(ops.preflight({ toolName: "web_search" }, {}, {}, "reviewer"), /ROLE_CEILING/);
    await assert.rejects(ops.preflight({ toolName: "web_unregistered" }, {}, {}, "main"), /NOT_BOUND/);
    assert.equal(await tool.execute("id", {}, undefined), "ok"); assert.equal(observed, f.controller.signal);
    f.binding.close(); assert.equal(isBoundWebTool(f.runtime, "web_search"), false);
    await assert.rejects(tool.execute("id", {}), /STALE/);
  } finally { delete globalThis[slot]; }
});
test("web and MCP custom names cannot shadow another plugin or a native tool", async () => {
  const f = fixture();
  try {
    f.binding.registerTool(definition("custom_search"));
    assert.throws(() => registerMcpTool("custom_search", "docs", "search", () => {}), /CONFLICT/);
    assert.throws(() => registerMcpTool("web_search", "docs", "search", () => {}), /TOOL_NAME/);
    assert.throws(() => f.binding.registerTool(definition("read")), /TOOL_NAME/);
    const owner = captureMcpToolOwner();
    registerMcpTool("docs_search", "docs", "search", () => {}, owner);
    assert.throws(() => f.binding.registerTool(definition("docs_search")), /CONFLICT/);
    unregisterMcpTool("docs_search", owner);
    f.binding.registerTool(definition("docs_search"));
    unregisterMcpTool("docs_search", owner);
    assert.equal(await f.tools.get("docs_search").execute("id", {}), "result");
  } finally { f.binding.close(); delete globalThis[slot]; }
});
test("web results cannot publish after runtime replacement or managed-work scope changes", async () => {
  const f = fixture();
  try {
    f.binding.registerTool(definition("web_search", async () => { globalThis[slot] = {}; return "stale"; }));
    await assert.rejects(f.tools.get("web_search").execute("id", {}), /STALE/);
    globalThis[slot] = f.runtime;
    f.binding.registerTool(definition("fetch_content", async () => { f.runtime.managedRequestScope = { getStore: () => ({}) }; return "blocked"; }));
    await assert.rejects(f.tools.get("fetch_content").execute("id", {}), /UNMETERED_PARENT_HELPER/);
  } finally { f.binding.close(); delete globalThis[slot]; }
});
test("failed native registration releases its claim", () => {
  const f = fixture();
  try {
    const broken = bindWebTools({ registerTool() { throw new Error("fixture native failure"); } });
    assert.throws(() => broken.registerTool(definition("custom_search")), /native failure/);
    f.binding.registerTool(definition("custom_search"));
  } finally { f.binding.close(); delete globalThis[slot]; }
});

test("commands and shortcuts share owned operation scope and shutdown closes captured runtime", async () => {
  const f = fixture(), commands = new Map(), shortcuts = new Map(); let closed = 0;
  f.runtime.web.close = async () => { closed++; };
  const binding = bindWebTools({ registerCommand(name, value) { commands.set(name, value); }, registerShortcut(key, value) { shortcuts.set(key, value); } });
  try {
    binding.registerCommand("search", { handler: async args => args });
    binding.registerShortcut("ctrl+w", { handler: async () => "shortcut" });
    assert.equal(await commands.get("search").handler("query", {}), "query");
    assert.equal(await shortcuts.get("ctrl+w").handler({}), "shortcut");
    assert.deepEqual(f.calls.map(row => row.name), ["command:search", "shortcut:ctrl+w"]);
    await binding.reset(); assert.equal(closed, 1);
    assert.equal(await commands.get("search").handler("after-reset", {}), "after-reset");
    globalThis[slot] = {}; await binding.close(); assert.equal(closed, 2);
    await assert.rejects(commands.get("search").handler("stale", {}), /STALE/);
  } finally { delete globalThis[slot]; }
});
