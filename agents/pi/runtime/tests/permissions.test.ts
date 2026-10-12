// Base公开CodeMode→真实自有MCP controller/factory/admission组合；不加载SDK或Full服务。
import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialMcpController } from "../official-mcp-controller.ts";
import { digest } from "../managed-types.ts";

const hash = value => value.repeat(64);
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function fixture(approval) {
  const calls = [], tools = new Map(), handlers = new Map(), signal = new AbortController();
  const state = { confirms: 0, body: 0, transports: 0, checks: 0, events: [], issueWait: null, issueReady: null };
  const sessionManager = { getSessionId: () => "own-base-session" };
  const ctx = { cwd: "/work", sessionManager, hasUI: false, ui: { confirm() { state.confirms++; throw Error("unexpected UI"); } } };
  const projection = { schema_version: 1, loaded_config: { servers: [{ name: "docs", scope: "extension", source: "agentcfg:registry/mcp/docs",
    config: { type: "stdio", command: "/own/synthetic-server", args: [], cwd: "/work", env: {}, exposure: "hidden", toolExposure: { query: "codemode" } } }],
    errors: [], autoEnableCodemode: false }, bindings: { docs: { transport: "stdio", command_ref: "own-docs", authentication: "none" } }, allowed_tools: { docs: ["query"] } };
  const manifest = { profile_id: "pi-base", plugins: ["pi-todo", "loop-guard", "colorful-footer"], native_mcp: projection };
  const owner = { manager_activation_id: "own-activation", runtime_identity: hash("d") };
  let prepared, physical;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      prepared = { schema_version: 1, operation_id: "1".repeat(32), request_id: args.request_id, context: structuredClone(args.context), private_input_ref: "2".repeat(32),
        resolution: { kind: "mcp", tool_name: "mcp", backend: "native-mcp-v1", network: "deny", services: ["mcp:docs"],
          target: { server_names: ["docs"], action: "tool", name: "query", binding_digest: hash("e") },
          read_roots: [], write_roots: [], workspace_keys: [],
          policy: { generation: 1, policy_digest: hash("c"), ceiling_digest: hash("e"), hard_policy: "allow", approval, requires_human: approval === "human" } } };
      prepared.operation_digest = digest(prepared); physical = { operation_id: prepared.operation_id, kind: "mcp", state: "prepared" };
      return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status") return { admission: { operation_id: prepared.operation_id, state: physical.state }, execution: { ...physical } };
    if (method === "ordinary_admission_issue_deterministic") {
      state.issueReady?.resolve(); if (state.issueWait) await state.issueWait.promise;
      return { schema_version: 1, permit_id: "own-permit", operation_id: prepared.operation_id, operation_digest: prepared.operation_digest,
        source: "deterministic-policy", reviewer_identity: null, context: structuredClone(args.context) };
    }
    if (method === "ordinary_admission_consume") { physical.state = "consumed"; return { ...physical }; }
    if (method === "ordinary_admission_mcp_dispatch") { assert.equal(physical.state, "consumed"); physical.state = "sending"; return { operation_id: prepared.operation_id, state: "sending" }; }
    if (method === "ordinary_admission_mcp_complete") { physical.state = args.outcome; return { operation_id: prepared.operation_id, state: args.outcome }; }
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    throw Error("unexpected service/process/approval route");
  } };
  const emit = async (name, event) => { state.events.push(event); for (const handler of handlers.get(name) ?? []) await handler(event, ctx); };
  const pi = { registerTool(definition) { tools.set(definition.name, definition); },
    getAllTools: () => [...tools.keys()].map(name => ({ name, sourceInfo: { path: "<inline:rotom-native-mcp>" } })),
    on(name, handler) { const rows = handlers.get(name) ?? []; rows.push(handler); handlers.set(name, rows); },
    getMcpServers() { throw Error("ambient server discovery"); } };
  const details = { original: "own-public-outer-details" }, content = [{ type: "text", text: "own outer content" }];
  const sdk = new Proxy({
    createMcpExtension(options) {
      state.native = options;
      return view => view.on("session_start", () => view.registerTool({ name: "mcp__docs__query", label: "docs/query", description: "own fake query", parameters: {},
        namespace: { name: "mcp__docs" }, exposure: "codemode", async execute(_id, input) {
          state.body++; state.input = input; return { content: [{ type: "text", text: "own child result" }] };
        } }));
    },
    createCodemodeExtension(options) {
      state.codemode = options;
      return view => view.registerTool({ name: "codemode", label: "CodeMode", description: "own public event fixture", parameters: {},
        async execute(id, input, abortSignal, update, context) {
          let child;
          try { child = await tools.get("mcp__docs__query").execute(id + "/child", input.arguments, abortSignal, update, context); }
          catch { child = { isError: true, content: [{ type: "text", text: "own child rejected" }] }; }
          await emit("tool_result", { toolName: "mcp__docs__query", toolCallId: id + "/child", parentToolCallId: id, ...child });
          return { content, details };
        } });
    },
  }, { get(target, key, receiver) { if (!Object.hasOwn(target, key)) throw Error("unselected SDK/Full capability"); return Reflect.get(target, key, receiver); } });
  const runtime = { manifest, owner, supervisor, get manager() { throw Error("Full manager probe"); }, get readseek() { throw Error("Full service probe"); } };
  const admissionOptions = { supervisor, owner, manifest, cwd: ctx.cwd, sessionManager,
    configurationSnapshot: async () => ({ configIdentity: hash("a"), runtimeIdentity: hash("d"), projectConstraintsDigest: hash("b"), policyDigest: hash("c") }),
    policySnapshot: () => ({ generation: 1, policy_digest: hash("c") }) };
  const controller = await createOfficialMcpController({ sdk, runtime, admissionOptions, checkDeployment: () => { state.checks++; },
    stdioFactory() { state.transports++; throw Error("unrequested transport startup"); } });
  await controller.extensionFactories[0].factory(pi); await emit("session_start", {});
  const call = input => tools.get("codemode").execute("root", { arguments: input }, signal.signal, undefined, ctx);
  return { state, calls, signal, controller, call, details, content, manifest };
}
const count = (f, method) => f.calls.filter(row => row.method === method).length;

test("Base nested deterministic operation shares original policy authority without UI or Full capability", async () => {
  const symbol = Symbol.for("agentcfg.pi.managed.v1"), prior = Object.getOwnPropertyDescriptor(globalThis, symbol);
  let f, probes = 0;
  Object.defineProperty(globalThis, symbol, { configurable: true, get() { probes++; throw Error("Full global probe"); } });
  try {
    f = await fixture("deterministic-policy");
    const result = await f.call({ query: "own", source: "human", approval: "reviewer" });
    assert.equal(result.isError, undefined); assert.equal(result.details, f.details); assert.equal(result.content, f.content);
    assert.equal(f.state.body, 1); assert.equal(f.state.confirms, 0); assert.equal(f.state.transports, 0);
    assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(count(f, "ordinary_admission_issue"), 0);
    for (const method of ["ordinary_admission_consume", "ordinary_admission_mcp_dispatch", "ordinary_admission_mcp_complete"]) assert.equal(count(f, method), 1);
    assert.equal(f.calls.find(row => row.method === "ordinary_admission_prepare").args.context.policy_generation, 1);
    assert.deepEqual(f.state.codemode, { models: false }); assert(!f.manifest.plugins.includes("pi-subagents"));
    assert.equal(probes, 0);
  } finally {
    try { await f?.controller.close(); }
    finally { if (prior) Object.defineProperty(globalThis, symbol, prior); else delete globalThis[symbol]; }
  }
});

test("headless human child rejects model-reported source and marks outer failure without replacing public content/details", async () => {
  const f = await fixture("human");
  try {
    const result = await f.call({ query: "own", source: "deterministic-policy", approval: "deterministic-policy" });
    assert.equal(result.isError, true); assert.equal(result.details, f.details); assert.equal(result.content, f.content);
    assert.equal(f.state.body, 0); assert.equal(f.state.confirms, 0); assert.equal(f.state.transports, 0);
    for (const method of ["ordinary_admission_issue", "ordinary_admission_issue_deterministic", "ordinary_admission_consume", "ordinary_admission_mcp_dispatch"]) assert.equal(count(f, method), 0);
    assert(f.state.events.some(event => event.parentToolCallId === "root" && event.toolCallId === "root/child" && event.isError === true));
  } finally { await f.controller.close(); }
});

test("nested cancellation before late deterministic permit cannot consume or publish successful outer result", async () => {
  const f = await fixture("deterministic-policy");
  try {
    f.state.issueReady = deferred(); f.state.issueWait = deferred();
    const pending = f.call({ query: "own" }), rejected = assert.rejects(pending, /PI_MCP_OPERATION_REJECTED/);
    await f.state.issueReady.promise; f.signal.abort(); f.state.issueWait.resolve(); await rejected;
    assert.equal(f.state.body, 0); assert.equal(f.state.confirms, 0); assert.equal(f.state.transports, 0);
    assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1);
    assert.equal(count(f, "ordinary_admission_consume"), 0); assert.equal(count(f, "ordinary_admission_mcp_dispatch"), 0);
    assert.equal(count(f, "ordinary_admission_cancel_request"), 1);
    assert(f.state.events.some(event => event.parentToolCallId === "root" && event.isError === true));
  } finally { await f.controller.close(); }
});
