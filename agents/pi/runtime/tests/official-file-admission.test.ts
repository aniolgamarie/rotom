import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialFileAdmission } from "../official-file-admission.ts";
import { ProtocolError } from "../managed-types.ts";

function setup({ timeoutMs = 1000 } = {}) {
  const calls = [], state = { config: "a".repeat(64), wall: 1000, mono: 0, confirms: 0 }, abort = new AbortController();
  const sessionManager = Object.freeze({ getSessionId: () => "session" });
  const snapshot = async () => ({ configIdentity: state.config, projectConstraintsDigest: "b".repeat(64), policyDigest: "c".repeat(64), runtimeIdentity: state.runtimeIdentity ?? "d".repeat(64) });
  const owner = { manager_activation_id: "manager", runtime_identity: "d".repeat(64) };
  const ctx = { cwd: "/work", sessionManager, hasUI: true, ui: { async confirm(title, message, options) {
    state.confirms++; state.dialog = { title, message, options }; return state.confirm ? state.confirm() : true;
  } } };
  let prepared, permit, physical;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (state.rpc) await state.rpc(method, args);
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      physical = { operation_id: "physical", request_digest: "e".repeat(64), path: "/work/file", write: args.tool_name === "write", lease_id: null, state: "prepared" };
      prepared = { schema_version: 1, operation_id: "prepared", request_id: args.request_id, context: structuredClone(args.context), private_input_ref: "nonce",
        operation_digest: "f".repeat(64), resolution: { kind: "file", tool_name: args.tool_name, target: { path: "/work/file", destination: null },
          read_roots: [{ path: "/work", identity: "a".repeat(64) }],
          write_roots: physical.write ? [{ path: "/work", identity: "a".repeat(64) }] : [], workspace_keys: physical.write ? ["b".repeat(64)] : [],
          network: "deny", services: [], backend: "guarded-files-v1", policy: { generation: 1,
            policy_digest: "c".repeat(64), ceiling_digest: "a".repeat(64), hard_policy: "allow", requires_human: true } } };
      return structuredClone(prepared);
    }
    if (method === "ordinary_admission_issue") {
      permit = { schema_version: 1, permit_id: "permit", operation_id: "prepared", operation_digest: prepared.operation_digest, source: "human", reviewer_identity: null, context: args.context };
      return structuredClone(permit);
    }
    if (method === "ordinary_admission_consume") {
      physical = { ...physical, lease_id: physical.write ? "lease" : "manager", state: "consumed" };
      state.afterConsume?.();
      if (state.consumeLost) throw new Error("private transport marker");
      return { ...physical };
    }
    if (method === "ordinary_admission_status") return { admission: { operation_id: "prepared", state: physical?.state ?? "prepared" }, execution: state.statusOverride ?? { ...physical } };
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    if (method === "ordinary_finish") return { finished: true };
    if (method === "inspect") return { lease_id: "lease", state: "allocating", spawn_committed: state.spawnCommitted === true };
    if (["abort_allocation", "cancel"].includes(method)) return {};
    throw new Error("unexpected fake RPC");
  } };
  const controller = createOfficialFileAdmission({ supervisor, owner, manifest: { profile_id: "pi-base" }, sessionManager, cwd: "/work", configurationSnapshot: snapshot,
    policySnapshot: () => ({ generation: 1, policy_digest: "c".repeat(64) }), timeoutMs, now: () => state.wall, monotonic: () => state.mono });
  const request = { id: "native-id", toolName: "write", input: { path: "file", content: "synthetic-private-body" }, signal: abort.signal, ctx };
  return { controller, request, calls, state, abort, ctx };
}


test("known policy rejection is a deny with zero confirmation or permit consumption", async () => {
  const f = setup();
  f.state.rpc = method => { if (method === "ordinary_admission_prepare") throw new ProtocolError("PERMISSION_DENIED", 4); };
  await assert.rejects(f.controller.admit(f.request), error => error.code === "PERMISSION_DENIED");
  assert.equal(f.state.confirms, 0);
  assert.equal(f.calls.some(row => row.method === "ordinary_admission_issue" || row.method === "ordinary_admission_consume"), false);
  await f.controller.drain();
});

for (const fault of ["transport", "unbranded", "wrong-exit"]) test("unconfirmed " + fault + " cannot masquerade as a policy deny", async () => {
  const f = setup();
  f.state.rpc = method => {
    if (method !== "ordinary_admission_prepare") return;
    if (fault === "unbranded") throw new Error("PERMISSION_DENIED");
    if (fault === "wrong-exit") throw new ProtocolError("PERMISSION_DENIED", 5);
    throw new Error("private synthetic transport marker");
  };
  await assert.rejects(f.controller.admit(f.request), error => error.code === "OPERATION_CONTROL_UNAVAILABLE"
    && !String(error).includes("private synthetic transport marker"));
  assert.equal(f.state.confirms, 0);
  assert.equal(f.calls.some(row => row.method === "ordinary_admission_issue" || row.method === "ordinary_admission_consume"), false);
  await f.controller.drain();
});
const methods = f => f.calls.map(row => row.method);

test("final execute obtains human response before issuing and consuming with private frozen input", async () => {
  const f = setup(), result = await f.controller.admit(f.request);
  assert.deepEqual(methods(f).slice(0, 5), ["ordinary_admission_open", "ordinary_admission_prepare", "ordinary_admission_status", "ordinary_admission_issue", "ordinary_admission_consume"]);
  assert.equal(result.ticket.state, "consumed"); assert.equal(result.ticket.lease_id, "lease");
  assert.equal(Object.isFrozen(result.input), true);
  assert.equal(f.state.dialog.message.includes("synthetic-private-body"), false);
  assert.equal(f.state.dialog.message.includes("/work/file"), true);
  assert.equal(f.state.dialog.options.signal instanceof AbortSignal, true);
  f.request.input.content = "changed"; assert.equal(result.input.content, "synthetic-private-body");
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/);
});
for (const fault of ["no-ui", "no-confirm", "false", "truthy", "preabort", "foreign-session", "foreign-cwd", "no-signal"]) test("refuses " + fault + " without issuing permission", async () => {
  const f = setup();
  if (fault === "no-ui") f.ctx.hasUI = false;
  if (fault === "no-confirm") delete f.ctx.ui.confirm;
  if (fault === "false") f.state.confirm = () => false;
  if (fault === "truthy") f.state.confirm = () => "yes";
  if (fault === "preabort") f.abort.abort();
  if (fault === "foreign-session") f.ctx.sessionManager = { getSessionId: () => "foreign" };
  if (fault === "foreign-cwd") f.ctx.cwd = "/elsewhere";
  if (fault === "no-signal") delete f.request.signal;
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/);
  assert.equal(methods(f).includes("ordinary_admission_issue"), false);
  assert.equal(methods(f).includes("ordinary_admission_consume"), false);
  await f.controller.drain();
});
for (const change of ["abort", "retire", "config", "wall-timeout", "mono-timeout"]) test("late confirmation after " + change + " never consumes", async () => {
  const f = setup(); let confirm; f.state.confirm = () => new Promise(resolve => { confirm = resolve; });
  const pending = f.controller.admit(f.request);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(f.state.confirms, 1);
  if (change === "abort") f.abort.abort();
  if (change === "retire") f.controller.retire();
  if (change === "config") f.state.config = "9".repeat(64);
  if (change === "wall-timeout") f.state.wall += 1001;
  if (change === "mono-timeout") f.state.mono += 1001;
  confirm(true);
  await assert.rejects(pending, /OPERATION_/);
  await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_issue"), false);
  assert.equal(methods(f).includes("ordinary_admission_consume"), false);
  assert.equal(methods(f).includes("ordinary_admission_cancel_request"), true);
});
test("lost consume reply only reads status and accepts exact consumed binding", async () => {
  const f = setup(); f.state.consumeLost = true;
  const result = await f.controller.admit(f.request);
  assert.equal(result.ticket.lease_id, "lease");
  assert.equal(methods(f).filter(method => method === "ordinary_admission_consume").length, 1);
  assert.equal(methods(f).filter(method => method === "ordinary_admission_status").length, 2);
});
for (const fault of ["unknown", "foreign-path", "foreign-lease", "extra"]) test("lost consume " + fault + " cannot release or deliver unknown Writer", async () => {
  const f = setup(); f.state.consumeLost = true;
  f.state.rpc = method => {
    if (method !== "ordinary_admission_consume") return;
    f.state.statusOverride = { operation_id: "physical", request_digest: "e".repeat(64), path: "/work/file", write: true, lease_id: "lease", state: "consumed" };
    if (fault === "unknown") f.state.statusOverride.state = "unknown";
    if (fault === "foreign-path") f.state.statusOverride.path = "/elsewhere";
    if (fault === "foreign-lease") f.state.statusOverride.lease_id = "";
    if (fault === "extra") f.state.statusOverride.skip = true;
  };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/);
  await f.controller.drain();
  for (const method of ["ordinary_finish", "inspect", "abort_allocation", "cancel", "start"]) assert.equal(methods(f).includes(method), false);
});
test("retire is synchronous and tombstones a pending open before its reply", async () => {
  const f = setup(); let opened;
  f.state.rpc = method => method === "ordinary_admission_open" ? new Promise(resolve => { opened = resolve; }) : undefined;
  const pending = f.controller.admit(f.request);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.controller.retire(), undefined);
  opened(); await assert.rejects(pending, /OPERATION_/); await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_retire"), true);
  assert.equal(methods(f).includes("ordinary_admission_prepare"), false);
});


for (const toolName of ["read", "write"]) test("cancellation after known consumed " + toolName + " uses actual lease safely", async () => {
  const f = setup(); f.request.toolName = toolName;
  f.state.afterConsume = () => f.abort.abort();
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/);
  await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_consume"), true);
  if (toolName === "read") {
    assert.equal(methods(f).includes("ordinary_finish"), true);
    assert.equal(methods(f).includes("cancel"), false); assert.equal(methods(f).includes("inspect"), false);
  } else {
    assert.equal(methods(f).includes("inspect"), true); assert.equal(methods(f).includes("abort_allocation"), true);
    assert.equal(methods(f).includes("ordinary_finish"), false);
  }
});
test("configuration changes during consume stop delivery and cancel only the known Writer", async () => {
  const f = setup(); f.state.afterConsume = () => { f.state.config = "9".repeat(64); };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CONTEXT_STALE/);
  await f.controller.drain();
  assert.equal(methods(f).includes("inspect"), true); assert.equal(methods(f).includes("abort_allocation"), true);
  assert.equal(methods(f).includes("ordinary_finish"), false);
});
test("runtime identity drift cannot open a control channel", async () => {
  const f = setup(); f.state.runtimeIdentity = "9".repeat(64);
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CONTEXT_STALE/);
  await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_open"), false);
});
test("arbitrary upstream OPERATION error text is never echoed", async () => {
  const f = setup(); f.state.confirm = () => { throw new Error("OPERATION_SYNTHETIC_PRIVATE_MARKER"); };
  await assert.rejects(f.controller.admit(f.request), error => error.message === "OPERATION_ADMISSION_FAILED");
  await f.controller.drain();
});
test("real dialog deadline aborts its signal even if the UI ignores cancellation", async () => {
  const f = setup({ timeoutMs: 10 }); f.state.confirm = () => new Promise(() => {});
  await assert.rejects(f.controller.admit(f.request), /OPERATION_EXPIRED/);
  await f.controller.drain();
  assert.equal(f.state.dialog.options.signal.aborted, true);
  assert.equal(methods(f).includes("ordinary_admission_issue"), false);
});
test("failed cleanup is reported by drain, never described as successful", async () => {
  const f = setup(); f.state.confirm = () => false;
  f.state.rpc = method => { if (method === "ordinary_admission_cancel_request") throw new Error("private cleanup error"); };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/);
  await assert.rejects(f.controller.drain(), error => error.message === "OPERATION_CONTROL_UNAVAILABLE");
});
test("one lazy open is reused across distinct native requests, and same id with changed arguments is rejected", async () => {
  const f = setup(); await f.controller.admit(f.request);
  await f.controller.admit({ ...f.request, id: "second" });
  assert.equal(methods(f).filter(method => method === "ordinary_admission_open").length, 1);
  await assert.rejects(f.controller.admit({ ...f.request, input: { path: "other", content: "new" } }), /OPERATION_REQUEST_REPLAY/);
});


test("4096 native ids exhaust capacity without forgetting old approvals", async () => {
  const f = setup();
  for (let index = 0; index < 4096; index++) await f.controller.admit({ ...f.request, id: "bounded-" + index });
  const before = f.calls.length;
  await assert.rejects(f.controller.admit({ ...f.request, id: "overflow" }), /OPERATION_CAPACITY/);
  assert.equal(f.calls.length, before);
  await assert.rejects(f.controller.admit({ ...f.request, id: "bounded-0" }), /OPERATION_REQUEST_REPLAY/);
});
test("32MiB private budget rejects before prepare and never emits body text", async () => {
  const f = setup(), input = { path: "file", content: "x".repeat(1024 * 1024 - 28) };
  assert.equal(Buffer.byteLength(JSON.stringify(input)), 1024 * 1024);
  for (let index = 0; index < 32; index++) await f.controller.admit({ ...f.request, id: "large-" + index, input });
  const before = f.calls.length;
  await assert.rejects(f.controller.admit({ ...f.request, id: "large-overflow", input }), error => error.message === "OPERATION_CAPACITY");
  assert.equal(f.calls.length, before);
});


for (const timeoutMs of [0, -1, true, 1.5, 300001]) test("invalid bounded timeout " + String(timeoutMs), () => {
  assert.throws(() => setup({ timeoutMs }), /OPERATION_CONTROL_INVALID/);
});
test("canceled consumed Writer with spawn committed uses cancel rather than allocation abort", async () => {
  const f = setup(); f.state.spawnCommitted = true; f.state.afterConsume = () => f.abort.abort();
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/);
  await f.controller.drain();
  assert.equal(methods(f).includes("cancel"), true); assert.equal(methods(f).includes("abort_allocation"), false);
  assert.equal(methods(f).includes("ordinary_finish"), false);
});
test("cancel tombstone is sent even while prepare response is pending", async () => {
  const f = setup(); let release;
  f.state.rpc = method => method === "ordinary_admission_prepare" ? new Promise(resolve => { release = resolve; }) : undefined;
  const pending = f.controller.admit(f.request);
  await new Promise(resolve => setImmediate(resolve)); f.abort.abort();
  await assert.rejects(pending, /OPERATION_CANCELED/);
  release(); await f.controller.drain();
  const sent = f.calls.find(row => row.method === "ordinary_admission_prepare");
  const cancel = f.calls.find(row => row.method === "ordinary_admission_cancel_request");
  assert.equal(cancel.args.request_id, sent.args.request_id); assert.equal(cancel.args.control_id, sent.args.control_id);
  assert.equal(methods(f).includes("ordinary_admission_issue"), false);
});
