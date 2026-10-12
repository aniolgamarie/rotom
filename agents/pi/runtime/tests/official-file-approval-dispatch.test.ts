import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialFileAdmission } from "../official-file-admission.ts";
import { digest } from "../managed-types.ts";

function setup({ approval = "deterministic-policy", ui = false } = {}) {
  const calls = [], state = { config: "a".repeat(64), confirms: 0 }, abort = new AbortController();
  const sessionManager = { getSessionId: () => "session" };
  const snapshot = async () => ({ configIdentity: state.config, projectConstraintsDigest: "b".repeat(64), policyDigest: "c".repeat(64), runtimeIdentity: "d".repeat(64) });
  const ctx = { cwd: "/work", sessionManager, hasUI: ui, ui: { confirm: async () => { state.confirms++; return true; } } };
  let prepared, physical;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (state.rpc) await state.rpc(method, args);
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      const write = ["write", "edit", "rename"].includes(args.tool_name);
      prepared = { schema_version: 1, operation_id: "1".repeat(32), request_id: args.request_id, context: structuredClone(args.context), private_input_ref: "2".repeat(32),
        resolution: { kind: "file", tool_name: args.tool_name, target: { path: "/work/file", destination: args.tool_name === "rename" ? "/work/other" : null },
          read_roots: [{ path: "/work", identity: "3".repeat(64) }], write_roots: write ? [{ path: "/work", identity: "3".repeat(64) }] : [],
          workspace_keys: write ? ["4".repeat(64)] : [], network: "deny", services: [], backend: "guarded-files-v1",
          policy: { generation: 1, policy_digest: "c".repeat(64), ceiling_digest: "5".repeat(64), hard_policy: "allow", approval, requires_human: approval === "human" } } };
      state.mutate?.(prepared); prepared.operation_digest = digest(prepared); state.afterDigest?.(prepared);
      physical = { operation_id: prepared.operation_id, request_digest: prepared.operation_digest, path: "/work/file", write, lease_id: null, state: "prepared" };
      state.prepared = prepared;
      return prepared;
    }
    if (["ordinary_admission_issue", "ordinary_admission_issue_deterministic"].includes(method)) {
      return { schema_version: 1, permit_id: "permit", operation_id: prepared.operation_id, operation_digest: prepared.operation_digest,
        source: state.source ?? (method.endsWith("deterministic") ? "deterministic-policy" : "human"), reviewer_identity: null, context: structuredClone(args.context) };
    }
    if (method === "ordinary_admission_consume") {
      physical = { ...physical, state: "consumed", lease_id: physical.write ? "lease" : "manager" };
      if (state.consumeLost) throw Error("SYNTHETIC_PRIVATE");
      return { ...physical };
    }
    if (method === "ordinary_admission_status") {
      state.onStatus?.();
      return { admission: { operation_id: physical.operation_id, state: physical.state }, execution: state.unknown && physical.state === "consumed" ? { ...physical, state: "unknown" } : { ...physical } };
    }
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    throw Error("SYNTHETIC_PRIVATE");
  } };
  const controller = createOfficialFileAdmission({ supervisor, owner: { manager_activation_id: "manager", runtime_identity: "d".repeat(64) },
    manifest: { profile_id: "pi-base" }, sessionManager, cwd: "/work", configurationSnapshot: snapshot,
    policySnapshot: () => ({ generation: 1, policy_digest: "c".repeat(64) }) });
  return { calls, state, ctx, controller, abort, request: { id: "sdk-id", toolName: "write", input: { path: "file", content: "SYNTHETIC_PRIVATE" }, signal: abort.signal, ctx } };
}
const count = (f, name) => f.calls.filter(call => call.method === name).length;

test("explicit deterministic file approval consumes once headless without UI", async () => {
  const f = setup(); delete f.ctx.ui;
  const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.state, "consumed"); assert.equal(f.state.confirms, 0);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1);
  assert.equal(count(f, "ordinary_admission_issue"), 0); assert.equal(count(f, "ordinary_admission_consume"), 1);
  await f.controller.drain();
});

const noIssue = f => {
  assert.equal(count(f, "ordinary_admission_issue"), 0);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 0);
  assert.equal(count(f, "ordinary_admission_consume"), 0);
};
const fails = (promise, expected = "OPERATION_") => assert.rejects(promise, error => {
  assert.match(error.message, new RegExp(expected));
  assert.equal(String(error).includes("SYNTHETIC_PRIVATE"), false);
  assert.equal(error.cause, undefined); return true;
});
for (const approval of ["human", "reviewer", "deterministic-policy"]) test(`explicit ${approval} dispatches only its fixed trusted route`, async () => {
  const f = setup({ approval, ui: true });
  const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.state, "consumed"); assert.equal(Object.isFrozen(result.input), true);
  assert.equal(f.state.confirms, approval === "deterministic-policy" ? 0 : 1);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), approval === "deterministic-policy" ? 1 : 0);
  assert.equal(count(f, "ordinary_admission_issue"), approval === "deterministic-policy" ? 0 : 1);
  assert.equal(count(f, "ordinary_admission_consume"), 1);
  assert.equal(f.calls.some(call => call.method.includes("reviewer")), false);
  await f.controller.drain();
});
for (const approval of ["human", "reviewer"]) for (const uiShape of ["false", "no-confirm"]) test(`${approval} without ${uiShape} UI prepares then cancels without issue`, async () => {
  const f = setup({ approval, ui: uiShape !== "false" });
  if (uiShape === "no-confirm") delete f.ctx.ui.confirm;
  await fails(f.controller.admit(f.request), "OPERATION_ADMISSION_REQUIRED"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_prepare"), 1); noIssue(f);
  assert.equal(count(f, "ordinary_admission_cancel_request"), 1);
});
for (const toolName of ["read", "write", "edit", "rename", "ls", "find", "grep"]) test(`deterministic ${toolName} uses once-consume without confirmation`, async () => {
  const f = setup(); f.request.toolName = toolName;
  const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.write, ["write", "edit", "rename"].includes(toolName));
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(f.state.confirms, 0);
  await fails(f.controller.admit(f.request), "OPERATION_REQUEST_REPLAY");
  assert.equal(count(f, "ordinary_admission_consume"), 1); await f.controller.drain();
});
const badProjection = {
  unknownGrade: p => p.resolution.policy.approval = "automatic",
  nullGrade: p => p.resolution.policy.approval = null,
  flag: p => p.resolution.policy.requires_human = true,
  deny: p => p.resolution.policy.hard_policy = "deny",
  network: p => p.resolution.network = "allow",
  backend: p => p.resolution.backend = "native",
  service: p => p.resolution.services = ["shell"],
  generation: p => p.resolution.policy.generation = 2,
  policyDigest: p => p.resolution.policy.policy_digest = "9".repeat(64),
  ceilingDigest: p => p.resolution.policy.ceiling_digest = "bad",
  targetEscape: p => p.resolution.target.path = "/outside/file",
  rootEscape: p => p.resolution.write_roots[0].path = "/work-other",
  rootHash: p => p.resolution.read_roots[0].identity = "bad",
  rootDuplicate: p => p.resolution.write_roots.push({ ...p.resolution.write_roots[0] }),
  emptyWorkspace: p => p.resolution.workspace_keys = [],
  resolutionExtra: p => p.resolution.source = "deterministic-policy",
  policyExtra: p => p.resolution.policy.allow = true,
  operationId: p => p.operation_id = "not-hex",
  privateRef: p => p.private_input_ref = "not-hex",
  privateRefArray: p => p.private_input_ref = ["2".repeat(32)],
  noGradeFalse: p => delete p.resolution.policy.approval,
};
for (const [name, mutate] of Object.entries(badProjection)) test(`invalid bound projection ${name} cannot issue or consume`, async () => {
  const f = setup({ ui: true }); f.state.mutate = mutate;
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  noIssue(f); assert.equal(f.state.confirms, 0);
});
for (const field of ["operation_digest", "resolution", "context"]) test(`post-digest ${field} drift cannot issue`, async () => {
  const f = setup(); f.state.afterDigest = p => {
    if (field === "operation_digest") p.operation_digest = "9".repeat(64);
    else if (field === "resolution") p.resolution.policy.approval = "reviewer";
    else p.context.config_identity = "9".repeat(64);
  };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f);
});
test("complete old no-approval human projection remains UI-only", async () => {
  const f = setup({ approval: "human", ui: true }); f.state.mutate = p => delete p.resolution.policy.approval;
  assert.equal((await f.controller.admit(f.request)).ticket.state, "consumed");
  assert.equal(f.state.confirms, 1); assert.equal(count(f, "ordinary_admission_issue"), 1);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 0); await f.controller.drain();
});
test("business input cannot choose source or override human policy", async () => {
  const f = setup({ approval: "human", ui: true });
  f.request.input.approval = "deterministic-policy"; f.request.input.source = "reviewer";
  await f.controller.admit(f.request);
  assert.equal(f.state.confirms, 1); assert.equal(count(f, "ordinary_admission_issue"), 1);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 0); await f.controller.drain();
});
test("mutable supervisor cannot change captured approval after prepare", async () => {
  const f = setup(); f.state.onStatus = () => {
    f.state.prepared.resolution.policy.approval = "human";
    f.state.prepared.resolution.policy.requires_human = true;
    f.state.prepared.resolution.target.path = "/outside/file";
  };
  await f.controller.admit(f.request);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(f.state.confirms, 0);
  await f.controller.drain();
});
for (const change of ["abort", "retire", "config"]) test(`deterministic issue late reply after ${change} never consumes`, async () => {
  const f = setup(); let release, entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  f.state.rpc = method => method === "ordinary_admission_issue_deterministic" ? new Promise(resolve => { release = resolve; entered(); }) : undefined;
  const pending = f.controller.admit(f.request), rejected = fails(pending);
  await waiting;
  if (change === "abort") f.abort.abort();
  if (change === "retire") f.controller.retire();
  if (change === "config") f.state.config = "9".repeat(64);
  release(); await rejected; await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const source of ["human", "reviewer", "unknown"]) test(`deterministic permit source ${source} mismatch cannot consume`, async () => {
  const f = setup(); f.state.source = source;
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const unknown of [false, true]) test(`consume lost reply reads status only, unknown=${unknown}`, async () => {
  const f = setup(); f.state.consumeLost = true; f.state.unknown = unknown;
  if (unknown) await fails(f.controller.admit(f.request), "OPERATION_");
  else assert.equal((await f.controller.admit(f.request)).ticket.lease_id, "lease");
  await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_consume"), 1); assert.equal(count(f, "ordinary_admission_status"), 2);
  for (const method of ["ordinary_finish", "inspect", "abort_allocation", "cancel", "start"]) assert.equal(count(f, method), 0);
});
test("raw deterministic RPC error never propagates private body", async () => {
  const f = setup(); f.state.rpc = method => { if (method === "ordinary_admission_issue_deterministic") throw Error("SYNTHETIC_PRIVATE"); };
  await fails(f.controller.admit(f.request)); await f.controller.drain(); assert.equal(count(f, "ordinary_admission_consume"), 0);
});

test("legacy human policy cannot smuggle an unknown source into approval", async () => {
  const f = setup({ approval: "human", ui: true });
  f.state.mutate = p => { delete p.resolution.policy.approval; p.resolution.policy.source = "human"; };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  noIssue(f); assert.equal(f.state.confirms, 0);
});

for (const change of ["deny", "generation", "hash", "network", "resolution-extra"]) test(`legacy human ${change} remains fully validated`, async () => {
  const f = setup({ approval: "human", ui: true });
  f.state.mutate = p => {
    delete p.resolution.policy.approval;
    if (change === "deny") p.resolution.policy.hard_policy = "deny";
    if (change === "generation") p.resolution.policy.generation++;
    if (change === "hash") p.resolution.policy.policy_digest = "9".repeat(64);
    if (change === "network") p.resolution.network = "allow";
    if (change === "resolution-extra") p.resolution.source = "human";
  };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f);
  assert.equal(f.state.confirms, 0);
});
