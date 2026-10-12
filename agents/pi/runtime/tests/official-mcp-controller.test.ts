import assert from "node:assert/strict";
import { test } from "node:test";
import { setup } from "./official-mcp-admission.test.ts";
import { createOfficialMcpController } from "../official-mcp-controller.ts";

async function fixture(approval = "deterministic-policy", hasUI = false) {
  const f = setup({ approval, hasUI }), tools = new Map(), handlers = new Map(), state = { transports: 0, starts: 0, sends: 0, closes: 0, checks: 0 };
  const projection = { schema_version: 1,
    loaded_config: { servers: [{ name: "docs", scope: "extension", source: "agentcfg:registry/mcp/docs",
      config: { type: "http", url: "https://mcp.invalid/service", headers: { Authorization: "" }, exposure: "hidden", toolExposure: { query: "codemode" } } }], errors: [], autoEnableCodemode: false },
    bindings: { docs: { transport: "streamable-http", network_route: "docs-route", authentication: "none" } }, allowed_tools: { docs: ["query"] } };
  f.manifest.native_mcp = projection;
  const runtime = { owner: { ...f.admissionOptions.owner, role: "manager" }, manifest: f.manifest, supervisor: f.admissionOptions.supervisor };
  const pi = { registerTool(definition) { tools.set(definition.name, definition); },
    getAllTools: () => [...tools.keys()].map(name => ({ name, sourceInfo: { path: "<inline:rotom-native-mcp>" } })),
    on(event, fn) { const rows = handlers.get(event) ?? []; rows.push(fn); handlers.set(event, rows); } };
  const definition = name => ({ name, label: name, description: "fake", parameters: {}, execute: async () => ({ content: [] }) });
  const sdk = { createMcpExtension(options) {
    state.native = options;
    return view => {
      for (const name of ["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource", "tool_search"]) view.registerTool(definition(name));
      view.on("session_start", () => {
        view.registerTool({ ...definition("mcp__docs__query"), label: "docs/query", namespace: { name: "mcp__docs" }, exposure: "codemode",
          execute: async (...args) => { state.nativeCalls = (state.nativeCalls ?? 0) + 1; state.input = args[1]; return f.execute(args[1]); } });
      });
    };
  }, createCodemodeExtension(options) { state.codemode = options; return view => view.registerTool(definition("codemode")); } };
  const httpFactory = options => {
    state.transports++; state.transportOptions = options;
    return { async start() { state.starts++; }, async send() { state.sends++; }, async close() { state.closes++; },
      onMessage: () => () => {}, onError: () => () => {}, onClose: () => () => {} };
  };
  const mcp = await createOfficialMcpController({ sdk, runtime, admissionOptions: f.admissionOptions, mcpModule: {},
    checkDeployment: () => { state.checks++; if (state.stale) throw Error("PRIVATE"); }, httpFactory });
  await mcp.extensionFactories[0].factory(pi);
  for (const fn of handlers.get("session_start")) await fn({}, f.ctx);
  const call = id => tools.get("mcp__docs__query").execute(id, f.request.input, f.abort.signal, undefined, f.ctx);
  return { ...f, mcp, state, rpcState: f.state, tools, call };
}
test("real self-owned MCP factory and admission compose without old plugins or implicit transport", async () => {
  const f = await fixture();
  assert.equal(f.manifest.plugins, undefined); assert.equal(f.state.transports, 0);
  assert.equal(f.state.native.loadConfig(f.ctx).servers[0].config.enabled, false);
  assert.deepEqual(f.state.codemode, { models: false });
  assert.equal((await f.call("integration")).content[0].text, "answer");
  assert.equal(f.state.nativeCalls, 1); assert.equal(f.state.input.weight, 0.25);
  assert.deepEqual(f.calls.filter(row => row.method.includes("mcp_")).map(row => row.method), ["ordinary_admission_mcp_dispatch", "ordinary_admission_mcp_complete"]);
  await f.mcp.close(); await assert.rejects(f.call("late"), /PI_MCP_/);
});
test("headless human and explicit denial never reach native execute", async () => {
  for (const hasUI of [false, true]) {
    const f = await fixture("human", hasUI); f.rpcState.confirm = () => false;
    await assert.rejects(f.call("denied"), /PI_MCP_OPERATION_REJECTED/);
    assert.equal(f.state.nativeCalls, undefined); await f.mcp.close();
  }
});
test("session-only Enable uses the fixed public HTTP backend and closes after retirement", async () => {
  const f = await fixture(), entry = structuredClone(f.state.native.loadConfig(f.ctx).servers[0]); entry.config.enabled = true;
  const transport = f.state.native.createTransport(entry, f.ctx.cwd);
  assert.equal(f.state.transports, 1); assert.equal(f.state.transportOptions.serverName, "docs");
  await transport.start(); await transport.send({ jsonrpc: "2.0", id: 1, method: "initialize" });
  f.mcp.retire(); await f.mcp.close(); await f.mcp.close(); assert.equal(f.state.closes, 1);
  await assert.rejects(transport.send({}), /PI_MCP_/);
});
test("deployment drift blocks both native call and transport creation before IO", async () => {
  const f = await fixture(), entry = structuredClone(f.state.native.loadConfig(f.ctx).servers[0]); entry.config.enabled = true;
  f.state.stale = true;
  await assert.rejects(f.call("stale"), /PI_MCP_/);
  assert.throws(() => f.state.native.createTransport(entry, f.ctx.cwd), /PI_MCP_/);
  assert.equal(f.state.nativeCalls, undefined); assert.equal(f.state.transports, 0); await f.mcp.close();
});
