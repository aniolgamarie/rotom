import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialMcpAdmission } from "../official-file-admission.ts";
import { digest } from "../managed-types.ts";

const hash = c => c.repeat(64);
export function setup({ approval = "deterministic-policy", hasUI = false, timeoutMs = 1000 } = {}) {
  const calls = [], state = { config: hash("a"), generation: 1, confirms: 0, executions: 0 };
  const abort = new AbortController(), sessionManager = { getSessionId: () => "session" };
  const ctx = { cwd: "/work", sessionManager, hasUI, ui: { async confirm(title, summary) {
    state.confirms++; state.dialog = { title, summary }; return state.confirm ? state.confirm() : true;
  } } };
  const manifest = { profile_id: "pi-base", native_mcp: {
    bindings: { docs: { transport: "streamable-http" } }, allowed_tools: { docs: ["query"] } } };
  let prepared, physical;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (state.rpc) await state.rpc(method, args);
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      prepared = { schema_version: 1, operation_id: "1".repeat(32), request_id: args.request_id,
        context: structuredClone(args.context), private_input_ref: "2".repeat(32), resolution: {
          kind: "mcp", tool_name: "mcp", backend: "native-mcp-v1", network: "managed-route",
          target: { server_names: ["docs"], action: args.input.action, name: args.input.name, binding_digest: hash("e") },
          read_roots: [], write_roots: [], workspace_keys: [], services: ["mcp:docs"],
          policy: { generation: 1, policy_digest: hash("c"), ceiling_digest: hash("e"), hard_policy: "allow", approval, requires_human: approval === "human" } } };
      state.changePrepared?.(prepared); prepared.operation_digest = digest(prepared); state.afterDigest?.(prepared);
      physical = { operation_id: prepared.operation_id, kind: "mcp", state: "prepared" };
      return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status") {
      const execution = { ...physical }; state.changeTicket?.(execution);
      return { admission: { operation_id: prepared.operation_id, state: physical.state === "prepared" ? "prepared" : "consumed" }, execution };
    }
    if (["ordinary_admission_issue", "ordinary_admission_issue_deterministic"].includes(method)) return {
      schema_version: 1, permit_id: "permit", operation_id: prepared.operation_id, operation_digest: prepared.operation_digest,
      source: method.endsWith("deterministic") ? "deterministic-policy" : "human", reviewer_identity: null, context: structuredClone(args.context) };
    if (method === "ordinary_admission_consume") {
      physical.state = "consumed"; state.afterConsume?.();
      if (state.consumeLost) throw Error("SYNTHETIC_PRIVATE");
      return { ...physical };
    }
    if (method === "ordinary_admission_mcp_dispatch") {
      assert.equal(physical.state, "consumed"); physical.state = "sending"; state.afterDispatch?.();
      if (state.dispatchLost) throw Error("SYNTHETIC_PRIVATE");
      return { operation_id: prepared.operation_id, state: "sending" };
    }
    if (method === "ordinary_admission_mcp_complete") {
      physical.state = physical.state === "cancelled" ? "unknown" : args.outcome;
      if (state.completeLost) throw Error("SYNTHETIC_PRIVATE");
      return { operation_id: prepared.operation_id, state: physical.state };
    }
    if (method === "ordinary_admission_cancel_request") {
      if (physical && ["consumed", "sending"].includes(physical.state)) physical.state = "cancelled";
      return { request_id: args.request_id, state: "canceled" };
    }
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    throw Error("SYNTHETIC_PRIVATE");
  } };
  const admissionOptions = { supervisor, owner: { manager_activation_id: "manager", runtime_identity: hash("d") }, manifest,
    cwd: "/work", sessionManager, timeoutMs,
    configurationSnapshot: async () => ({ configIdentity: state.config, runtimeIdentity: hash("d"), projectConstraintsDigest: hash("b"), policyDigest: hash("c") }),
    policySnapshot: () => ({ generation: state.generation, policy_digest: hash("c") }) };
  const controller = createOfficialMcpAdmission(admissionOptions);
  const request = { id: "sdk-id", server_name: "docs", action: "tool", name: "query", input: { q: "SYNTHETIC_PRIVATE", weight: 0.25 }, signal: abort.signal, ctx };
  const execute = async input => { state.executions++; state.executed = input; return state.execute ? state.execute(input) : { content: [{ type: "text", text: "answer" }] }; };
  return { calls, state, abort, ctx, manifest, controller, admissionOptions, request, execute, physical: () => physical };
}
const count = (f, name) => f.calls.filter(row => row.method === name).length;
const fails = (promise, code = "OPERATION_") => assert.rejects(promise, error => {
  assert.match(error.message, new RegExp(code)); assert.ok(!String(error).includes("SYNTHETIC_PRIVATE")); return true;
});

test("MCP dispatch and completion use original admission once and exact finite input", async () => {
  const f = setup(), value = await f.controller.invoke(f.request, f.execute);
  assert.equal(value.content[0].text, "answer"); assert.equal(f.state.executions, 1); assert.equal(f.state.confirms, 0);
  for (const name of ["consume", "mcp_dispatch", "mcp_complete"]) assert.equal(count(f, "ordinary_admission_" + name), 1);
  assert.deepEqual(f.state.executed, f.request.input); assert.ok(Object.isFrozen(f.state.executed));
  assert.equal(f.physical().state, "succeeded");
  await fails(f.controller.invoke(f.request, f.execute), "OPERATION_REQUEST_REPLAY"); await f.controller.drain();
  assert.equal(f.state.executions, 1);
});
for (const approval of ["human", "reviewer"]) test(approval + " remains trusted human confirmation while AUTO OFF", async () => {
  const f = setup({ approval, hasUI: true });
  const original = structuredClone(f.request.input);
  f.state.confirm = () => { f.request.input.weight = 99; return true; };
  await f.controller.invoke(f.request, f.execute);
  assert.equal(f.state.dialog.title, "Approve MCP operation"); assert.ok(f.state.dialog.summary.includes(JSON.stringify(original)));
  assert.deepEqual(f.state.executed, original); assert.equal(f.state.confirms, 1);
  assert.equal(count(f, "ordinary_admission_issue"), 1); await f.controller.drain();
});
for (const fault of ["no-ui", "deny", "truthy"]) test("human " + fault + " sends no service call", async () => {
  const f = setup({ approval: "human", hasUI: fault !== "no-ui" });
  f.state.confirm = () => fault === "truthy" ? "yes" : false;
  await fails(f.controller.invoke(f.request, f.execute)); await f.controller.drain();
  assert.equal(f.state.executions, 0); assert.equal(count(f, "ordinary_admission_mcp_dispatch"), 0);
});
const faults = {
  backend: p => p.resolution.backend = "sdk-default",
  root: p => p.resolution.write_roots = [{ path: "/work", identity: hash("b") }],
  services: p => p.resolution.services = ["mcp:other"],
  network: p => p.resolution.network = "deny",
  server: p => p.resolution.target.server_names = ["other"],
  action: p => p.resolution.target.action = "read_resource",
  name: p => p.resolution.target.name = "other",
  hash: p => p.resolution.target.binding_digest = "bad",
  extra: p => p.resolution.target.arguments = { secret: true },
  policy: p => p.resolution.policy.hard_policy = "deny",
};
for (const [name, mutate] of Object.entries(faults)) test("foreign resolution " + name + " cannot consume or execute", async () => {
  const f = setup(); f.state.changePrepared = mutate;
  await fails(f.controller.invoke(f.request, f.execute), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  assert.equal(f.state.executions, 0); assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const fault of ["operation_id", "kind", "lease_id", "state"]) test("foreign MCP ticket " + fault + " rejects", async () => {
  const f = setup(); f.state.changeTicket = ticket => ticket[fault] = "foreign";
  await fails(f.controller.invoke(f.request, f.execute)); await f.controller.drain(); assert.equal(f.state.executions, 0);
});
test("lost consume receipt reconciles once; lost dispatch ACK never invokes or resends", async () => {
  const f = setup(); f.state.consumeLost = true;
  await f.controller.invoke(f.request, f.execute); assert.equal(f.state.executions, 1); assert.equal(count(f, "ordinary_admission_consume"), 1);
  const g = setup(); g.state.dispatchLost = true;
  await fails(g.controller.invoke(g.request, g.execute)); await g.controller.drain();
  assert.equal(g.state.executions, 0); assert.equal(count(g, "ordinary_admission_mcp_dispatch"), 1);
});
test("lost completion ACK does not publish result or retry", async () => {
  const f = setup(); f.state.completeLost = true;
  await fails(f.controller.invoke(f.request, f.execute)); await f.controller.drain();
  assert.equal(f.state.executions, 1); assert.equal(count(f, "ordinary_admission_mcp_complete"), 1);
});
test("failed execute sanitizes original error and completes failed once", async () => {
  const f = setup(); f.state.execute = async () => { throw Error("SYNTHETIC_PRIVATE"); };
  await fails(f.controller.invoke(f.request, f.execute), "OPERATION_ADMISSION_FAILED"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_mcp_complete"), 1);
  assert.equal(f.calls.find(row => row.method === "ordinary_admission_mcp_complete").args.outcome, "failed");
});
test("native tool isError is recorded as failed without changing its result", async () => {
  const f = setup(); f.state.execute = async () => ({ isError: true, content: [] });
  assert.equal((await f.controller.invoke(f.request, f.execute)).isError, true); assert.equal(f.physical().state, "failed");
});
for (const change of ["cancel", "retire", "config"]) test(change + " during execute cannot publish a late successful result", async () => {
  const f = setup(); let resolve;
  f.state.execute = () => new Promise(done => { resolve = done; });
  const pending = f.controller.invoke(f.request, f.execute);
  while (!resolve) await new Promise(done => setImmediate(done));
  if (change === "cancel") f.abort.abort();
  else if (change === "retire") f.controller.retire();
  else f.state.config = hash("9");
  resolve({ content: [{ type: "text", text: "late" }] });
  await fails(pending); await f.controller.drain();
  assert.equal(f.state.executions, 1); assert.equal(count(f, "ordinary_admission_mcp_complete"), 1);
  assert.notEqual(f.physical().state, "succeeded");
});
test("deadline expires in execute and ignores later rejection", async () => {
  const f = setup({ timeoutMs: 80 }); let reject;
  f.state.execute = () => new Promise((_, fail) => { reject = fail; });
  const pending = f.controller.invoke(f.request, f.execute);
  await fails(pending, "OPERATION_EXPIRED"); reject?.(Error("SYNTHETIC_PRIVATE")); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_mcp_complete"), 1); assert.equal(f.state.executions, 1);
  assert.equal(f.calls.find(row => row.method === "ordinary_admission_mcp_complete").args.outcome, "unknown");
});
test("canceled before dispatch response never reaches execute", async () => {
  const f = setup(); f.state.afterDispatch = () => f.abort.abort();
  await fails(f.controller.invoke(f.request, f.execute), "OPERATION_CANCELED"); await f.controller.drain();
  assert.equal(f.state.executions, 0);
});
for (const action of ["list_resources", "list_templates", "tool_search", "read_resource"]) test(action + " binds the selected resource action", async () => {
  const f = setup(), names = { list_resources: "list_mcp_resources", list_templates: "list_mcp_resource_templates", tool_search: "tool_search", read_resource: "read_mcp_resource" };
  f.request.action = action; f.request.name = names[action]; f.request.server_name = action === "read_resource" ? "docs" : null;
  await f.controller.invoke(f.request, f.execute); assert.equal(f.state.executions, 1);
});
