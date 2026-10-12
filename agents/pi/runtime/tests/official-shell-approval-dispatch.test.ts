import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialShellAdmission } from "../official-file-admission.ts";
import { digest } from "../managed-types.ts";

const hash = char => char.repeat(64);
function setup({ approval = "deterministic-policy", ui = false, write = true, legacy = false } = {}) {
  const calls = [], state = { config: hash("a"), generation: 1, confirms: 0, wall: 1000, mono: 0 }, abort = new AbortController();
  const sessionManager = { getSessionId: () => "session" };
  const ctx = { cwd: "/work", sessionManager, hasUI: ui, ui: { async confirm() {
    state.confirms++; return state.confirm ? state.confirm() : true;
  } } };
  let prepared, ticket;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (state.rpc) await state.rpc(method, args);
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      prepared = { schema_version: 1, operation_id: "1".repeat(32), request_id: args.request_id,
        context: structuredClone(args.context), private_input_ref: legacy ? "legacy-private-ref" : "2".repeat(32),
        resolution: { kind: "shell-command", tool_name: "bash", backend: "linux-bwrap-v1", network: "deny", services: [],
          target: { command_ref: "tool:build", executable: { path: "/usr/bin/bash", device: 1, inode: 2, uid: 0, sha256: hash("e") }, timeout_ms: 10000 },
          read_roots: [{ path: "/work", identity: hash("b") }], write_roots: write ? [{ path: "/work", identity: hash("b") }] : [],
          workspace_keys: write ? [hash("d")] : [], policy: { generation: 1, policy_digest: hash("c"), ceiling_digest: hash("d"),
            hard_policy: "allow", requires_human: legacy || approval === "human", ...(legacy ? {} : { approval }) } } };
      state.mutate?.(prepared);
      prepared.operation_digest = legacy ? hash("f") : digest(prepared);
      state.afterDigest?.(prepared);
      ticket = { operation_id: prepared.operation_id, lease_id: null, kind: "command", tool_name: "bash", write,
        state: "prepared", timeout_seconds: 10, command_ref: "tool:build", request_digest: prepared.operation_digest };
      state.prepared = prepared;
      return state.response ? state.response(prepared) : prepared;
    }
    if (["ordinary_admission_issue", "ordinary_admission_issue_deterministic"].includes(method)) {
      const permit = { schema_version: 1, permit_id: "permit", operation_id: prepared.operation_id, operation_digest: prepared.operation_digest,
        source: state.source ?? (method.endsWith("deterministic") ? "deterministic-policy" : "human"), reviewer_identity: null,
        context: structuredClone(args.context) };
      state.mutatePermit?.(permit); return permit;
    }
    if (method === "ordinary_admission_consume") {
      ticket = { ...ticket, state: "consumed", lease_id: "3".repeat(32) };
      if (state.lost) throw Error("SYNTHETIC_PRIVATE");
      return { ...ticket };
    }
    if (method === "ordinary_admission_status") {
      state.onStatus?.();
      return { admission: { operation_id: ticket.operation_id, state: ticket.state }, execution:
        state.unknown && ticket.state === "consumed" ? { ...ticket, state: "unknown" } : { ...ticket } };
    }
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    if (method === "inspect") return { lease_id: ticket.lease_id, state: "allocating", spawn_committed: false };
    if (["abort_allocation", "cancel"].includes(method)) return {};
    throw Error("SYNTHETIC_PRIVATE");
  } };
  const controller = createOfficialShellAdmission({ supervisor, owner: { manager_activation_id: "manager", runtime_identity: hash("d") },
    manifest: { profile_id: "pi-base" }, sessionManager, cwd: "/work",
    configurationSnapshot: async () => ({ configIdentity: state.config, runtimeIdentity: hash("d"), projectConstraintsDigest: hash("b"), policyDigest: hash("c") }),
    policySnapshot: () => ({ generation: state.generation, policy_digest: hash("c") }), now: () => state.wall, monotonic: () => state.mono, timeoutMs: 1000 });
  return { calls, state, abort, ctx, controller, request: { id: "shell-sdk-id", toolName: "bash",
    input: { command: "printf '%s' 'SYNTHETIC_PRIVATE' | cat > file\n$(true)", timeout: 10 }, ctx, signal: abort.signal } };
}
const count = (f, method) => f.calls.filter(call => call.method === method).length;
const noIssue = f => {
  for (const name of ["ordinary_admission_issue", "ordinary_admission_issue_deterministic", "ordinary_admission_consume"]) assert.equal(count(f, name), 0);
};
const fails = (promise, expected = "OPERATION_") => assert.rejects(promise, error => {
  if (expected === "OPERATION_") assert.match(error.message, /^OPERATION_/);
  else assert.equal(error.message, expected);
  assert.equal(String(error).includes("SYNTHETIC_PRIVATE"), false);
  assert.equal(error.exitCode, 4);
  assert.equal(error.cause, undefined); return true;
});

for (const write of [false, true]) test(`headless deterministic Shell ${write ? "write" : "readonly"} consumes once without confirmation`, async () => {
  const f = setup({ write }); delete f.ctx.ui;
  const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.state, "consumed"); assert.equal(result.ticket.write, write); assert.ok(Object.isFrozen(result.input));
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(count(f, "ordinary_admission_issue"), 0);
  assert.equal(count(f, "ordinary_admission_consume"), 1); assert.equal(f.state.confirms, 0);
  const issue = f.calls.find(call => call.method === "ordinary_admission_issue_deterministic");
  assert.deepEqual(Object.keys(issue.args).sort(), ["context", "operation_id"]);
  assert.equal(f.calls.some(call => /reviewer|model|ask/.test(call.method)), false);
  await fails(f.controller.admit(f.request), "OPERATION_REQUEST_REPLAY"); await f.controller.drain();
});
for (const approval of ["human", "reviewer", "deterministic-policy"]) test(`Shell ${approval} with UI uses only fixed trusted source`, async () => {
  const f = setup({ approval, ui: true }); const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.state, "consumed"); assert.equal(f.state.confirms, approval === "deterministic-policy" ? 0 : 1);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), approval === "deterministic-policy" ? 1 : 0);
  assert.equal(count(f, "ordinary_admission_issue"), approval === "deterministic-policy" ? 0 : 1);
  assert.equal(f.calls.some(call => /reviewer|model|ask/.test(call.method)), false); await f.controller.drain();
});
for (const approval of ["human", "reviewer"]) for (const shape of ["headless", "no-confirm"]) test(`${approval} ${shape} prepares and cancels its row without issue`, async () => {
  const f = setup({ approval, ui: shape === "no-confirm" }); if (shape === "no-confirm") delete f.ctx.ui.confirm;
  await fails(f.controller.admit(f.request), "OPERATION_ADMISSION_REQUIRED"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_prepare"), 1); assert.equal(count(f, "ordinary_admission_cancel_request"), 1); noIssue(f);
});
for (const approval of ["human", "reviewer"]) for (const answer of [false, null, "true"]) test(`${approval} confirmation ${JSON.stringify(answer)} cannot grant authority`, async () => {
  const f = setup({ approval, ui: true }); f.state.confirm = () => answer;
  await fails(f.controller.admit(f.request), "OPERATION_CANCELED"); await f.controller.drain(); noIssue(f);
});
for (const ui of [false, true]) test(`complete legacy human Shell keeps manual behavior UI=${ui}`, async () => {
  const f = setup({ legacy: true, ui });
  if (ui) {
    assert.equal((await f.controller.admit(f.request)).ticket.state, "consumed"); assert.equal(f.state.confirms, 1);
    assert.equal(count(f, "ordinary_admission_issue"), 1); assert.equal(count(f, "ordinary_admission_issue_deterministic"), 0);
  } else {
    await fails(f.controller.admit(f.request), "OPERATION_ADMISSION_REQUIRED");
    assert.equal(count(f, "ordinary_admission_prepare"), 1); noIssue(f);
  }
  await f.controller.drain();
});
const invalidProjection = {
  unknownGrade: p => p.resolution.policy.approval = "automatic",
  nullGrade: p => p.resolution.policy.approval = null,
  flag: p => p.resolution.policy.requires_human = true,
  missingGradeFalse: p => delete p.resolution.policy.approval,
  deny: p => p.resolution.policy.hard_policy = "deny",
  generation: p => p.resolution.policy.generation++,
  policyDigest: p => p.resolution.policy.policy_digest = hash("9"),
  ceilingDigest: p => p.resolution.policy.ceiling_digest = "invalid",
  policyExtra: p => p.resolution.policy.source = "human",
  resolutionExtra: p => p.resolution.source = "deterministic-policy",
  targetExtra: p => p.resolution.target.command = "SYNTHETIC_PRIVATE",
  preparedExtra: p => p.source = "deterministic-policy",
  network: p => p.resolution.network = "allow",
  service: p => p.resolution.services = ["service"],
  backend: p => p.resolution.backend = "native",
  commandRef: p => p.resolution.target.command_ref = "check:build",
  timeout: p => p.resolution.target.timeout_ms = 10001,
  executableExtra: p => p.resolution.target.executable.argv = ["SYNTHETIC_PRIVATE"],
  executablePath: p => p.resolution.target.executable.path = "/usr/../bin/bash",
  executableIdentity: p => p.resolution.target.executable.uid = -1,
  executableHash: p => p.resolution.target.executable.sha256 = "invalid",
  rootHash: p => p.resolution.read_roots[0].identity = "invalid",
  rootExtra: p => p.resolution.read_roots[0].writable = true,
  rootPath: p => p.resolution.read_roots[0].path = "/work/../escape",
  noReadRoots: p => p.resolution.read_roots = [],
  noWorkspace: p => p.resolution.workspace_keys = [],
  duplicateWorkspace: p => p.resolution.workspace_keys.push(p.resolution.workspace_keys[0]),
  operationId: p => p.operation_id = "not-hex",
  operationIdArray: p => p.operation_id = ["1".repeat(32)],
  privateRef: p => p.private_input_ref = "not-hex",
  privateRefArray: p => p.private_input_ref = ["2".repeat(32)],
  crossContext: p => p.context.session_id = "other",
};
for (const [name, mutate] of Object.entries(invalidProjection)) test(`closed Shell projection ${name} rejects before UI/issue/consume`, async () => {
  const f = setup({ ui: true }); f.state.mutate = mutate;
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f); assert.equal(f.state.confirms, 0);
});
for (const approval of ["human", "reviewer"]) test(`Shell ${approval} rejects inconsistent requires_human`, async () => {
  const f = setup({ approval, ui: true }); f.state.mutate = p => p.resolution.policy.requires_human = approval !== "human";
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f);
});
for (const shape of ["proxy", "accessor", "prototype"]) test(`Shell prepared ${shape} is rejected without invoking callbacks`, async () => {
  const f = setup({ ui: true }); let callbacks = 0;
  f.state.response = p => {
    if (shape === "proxy") return new Proxy(p, { ownKeys() { callbacks++; return Reflect.ownKeys(p); } });
    if (shape === "accessor") Object.defineProperty(p.resolution.policy, "approval", { get() { callbacks++; return "deterministic-policy"; }, enumerable: true });
    else Object.setPrototypeOf(p, { source: "deterministic-policy" });
    return p;
  };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f);
  assert.equal(callbacks, 0);
});
test("Shell keeps its captured prepared grade when transport object mutates before dispatch", async () => {
  const f = setup({ ui: true }); f.state.onStatus = () => {
    f.state.prepared.resolution.policy.approval = "human";
    f.state.prepared.resolution.policy.requires_human = true;
  };
  assert.equal((await f.controller.admit(f.request)).ticket.state, "consumed");
  assert.equal(f.state.confirms, 0); assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1);
  await f.controller.drain();
});
for (const field of ["operation_digest", "resolution", "context", "private_input_ref"]) test(`post-digest Shell ${field} drift cannot issue`, async () => {
  const f = setup({ ui: true }); f.state.afterDigest = p => {
    if (field === "operation_digest") p.operation_digest = hash("9");
    else if (field === "resolution") p.resolution.target.timeout_ms = 20000;
    else if (field === "context") p.context.cwd = "/other";
    else p.private_input_ref = "4".repeat(32);
  };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain(); noIssue(f);
});
for (const source of ["human", "reviewer", "automatic"]) test(`deterministic Shell rejects permit source ${source}`, async () => {
  const f = setup(); f.state.source = source;
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const fault of ["extra", "reviewer", "digest", "context"]) test(`strict Shell permit ${fault} cannot consume`, async () => {
  const f = setup(); f.state.mutatePermit = p => {
    if (fault === "extra") p.approval = "deterministic-policy";
    else if (fault === "reviewer") p.reviewer_identity = hash("9");
    else if (fault === "digest") p.operation_digest = hash("9");
    else p.context.cancel_epoch++;
  };
  await fails(f.controller.admit(f.request), "OPERATION_BINDING_INVALID"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const stage of ["before-issue", "before-consume"]) for (const change of ["config", "policy"]) test(`Shell ${change} drift ${stage} refuses dispatch`, async () => {
  const f = setup();
  const mutate = () => { if (change === "config") f.state.config = hash("9"); else f.state.generation++; };
  if (stage === "before-issue") f.state.onStatus = mutate;
  else f.state.rpc = method => { if (method === "ordinary_admission_issue_deterministic") mutate(); };
  await fails(f.controller.admit(f.request), "OPERATION_CONTEXT_STALE"); await f.controller.drain();
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), stage === "before-issue" ? 0 : 1);
  assert.equal(count(f, "ordinary_admission_consume"), 0);
});
for (const change of ["abort", "retire"]) test(`late deterministic Shell issue after ${change} never consumes`, async () => {
  const f = setup(); let release, reached;
  const entered = new Promise(resolve => reached = resolve), pending = new Promise(resolve => release = resolve);
  f.state.rpc = async method => { if (method === "ordinary_admission_issue_deterministic") { reached(); await pending; } };
  const result = f.controller.admit(f.request); const rejected = fails(result, "OPERATION_CANCELED");
  await entered; if (change === "abort") f.abort.abort(); else f.controller.retire(); release();
  await rejected; await f.controller.drain(); assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1);
  assert.equal(count(f, "ordinary_admission_consume"), 0); assert.equal(count(f, "ordinary_admission_cancel_request"), 1);
});
for (const change of ["abort", "retire"]) test(`late Shell UI reply after ${change} cannot issue`, async () => {
  const f = setup({ approval: "human", ui: true }); let release, reached;
  const entered = new Promise(resolve => reached = resolve), pending = new Promise(resolve => release = resolve);
  f.state.confirm = () => { reached(); return pending; };
  const result = f.controller.admit(f.request); const rejected = fails(result, "OPERATION_CANCELED");
  await entered; if (change === "abort") f.abort.abort(); else f.controller.retire(); release(true);
  await rejected; await f.controller.drain(); noIssue(f);
});
for (const unknown of [false, true]) test(`lost Shell consume receipt is read-only reconciled unknown=${unknown}`, async () => {
  const f = setup(); f.state.lost = true; f.state.unknown = unknown;
  if (unknown) await fails(f.controller.admit(f.request), "OPERATION_CONSUME_UNKNOWN");
  else assert.equal((await f.controller.admit(f.request)).ticket.state, "consumed");
  await f.controller.drain(); assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1);
  assert.equal(count(f, "ordinary_admission_consume"), 1); assert.equal(count(f, "ordinary_admission_status"), 2);
  for (const method of ["inspect", "cancel", "abort_allocation", "ordinary_finish"]) assert.equal(count(f, method), 0);
});
test("Shell fixed source depends on trusted prepared grade, never script wording", async () => {
  const f = setup(); f.request.input.command = "# requires human reviewer\nrm -rf imaginary-name";
  assert.equal((await f.controller.admit(f.request)).input.command, f.request.input.command);
  assert.equal(count(f, "ordinary_admission_issue_deterministic"), 1); await f.controller.drain();
});
