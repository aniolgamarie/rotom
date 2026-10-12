import assert from "node:assert/strict";
import { test } from "node:test";
import * as admission from "../official-file-admission.ts";

const hash = character => character.repeat(64);
function setup(write = true, { timeoutMs = 1000 } = {}) {
  const calls = [], state = { wall: 1000, mono: 0, config: hash("a"), generation: 1 }, abort = new AbortController();
  const sessionManager = { getSessionId: () => "session" };
  const ctx = { cwd: "/work", sessionManager, hasUI: true, ui: { async confirm(title, message) {
    state.dialog = { title, message }; return state.confirm ? state.confirm() : true;
  } } };
  let prepared, ticket;
  const supervisor = { async call(method, args) {
    calls.push({ method, args });
    if (state.rpc) await state.rpc(method, args);
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_prepare") {
      prepared = { schema_version: 1, operation_id: "1".repeat(32), request_id: args.request_id, context: structuredClone(args.context), private_input_ref: "private-ref", operation_digest: hash("f"),
        resolution: { kind: "shell-command", tool_name: "bash", backend: "linux-bwrap-v1", network: "deny", services: [],
          target: { command_ref: "tool:build", executable: { path: "/usr/bin/bash", device: 1, inode: 2, uid: 0, sha256: hash("e") }, timeout_ms: 10000 },
          read_roots: [{ path: "/work", identity: hash("b") }], write_roots: write ? [{ path: "/work", identity: hash("b") }] : [], workspace_keys: write ? [hash("d")] : [],
          policy: { generation: 1, policy_digest: hash("c"), ceiling_digest: hash("d"), hard_policy: "allow", requires_human: true } } };
      state.changePrepared?.(prepared);
      ticket = { operation_id: prepared.operation_id, lease_id: null, kind: "command", tool_name: "bash", write, state: "prepared", timeout_seconds: 10, command_ref: "tool:build", request_digest: hash("f") };
      return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status") {
      const execution = { ...ticket }; state.changeTicket?.(execution);
      return { admission: { operation_id: prepared.operation_id, state: ticket.state }, execution };
    }
    if (method === "ordinary_admission_issue") return { schema_version: 1, permit_id: "permit", operation_id: prepared.operation_id, operation_digest: prepared.operation_digest, source: "human", reviewer_identity: null, context: args.context };
    if (method === "ordinary_admission_consume") {
      ticket = { ...ticket, state: "consumed", lease_id: "2".repeat(32) }; state.afterConsume?.();
      if (state.lost) throw new Error("private-transport");
      const result = { ...ticket }; state.changeConsumed?.(result); return result;
    }
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_retire") return { control_id: args.control_id, state: "retired" };
    if (method === "inspect") return { lease_id: "2".repeat(32), state: state.leaseState ?? "allocating", spawn_committed: state.committed ?? false };
    if (["abort_allocation", "cancel"].includes(method)) { if (state.cleanupFail) throw new Error("secret"); return {}; }
    throw new Error("unexpected RPC");
  } };
  const factory = admission.createOfficialShellAdmission;
  const controller = factory({ supervisor, owner: { manager_activation_id: "manager", runtime_identity: hash("d") }, manifest: { profile_id: "pi-base" }, sessionManager, cwd: "/work",
    configurationSnapshot: async () => ({ configIdentity: state.config, runtimeIdentity: hash("d"), projectConstraintsDigest: hash("b"), policyDigest: hash("c") }),
    policySnapshot: () => ({ generation: state.generation, policy_digest: hash("c") }), now: () => state.wall, monotonic: () => state.mono, timeoutMs });
  const request = { id: "request", toolName: "bash", input: { command: "printf 'private' | cat\n$(true) > output", timeout: 10 }, ctx, signal: abort.signal };
  return { calls, state, abort, ctx, controller, request };
}
const methods = f => f.calls.map(row => row.method);
for (const write of [true, false]) test("Shell consumes bound " + (write ? "write" : "readonly") + " execution lease", async () => {
  const f = setup(write), result = await f.controller.admit(f.request);
  assert.equal(result.ticket.kind, "command"); assert.equal(result.ticket.write, write); assert.equal(result.ticket.lease_id, "2".repeat(32));
  assert.equal(methods(f).filter(x => x === "ordinary_admission_consume").length, 1);
  assert.ok(f.state.dialog.message.includes(JSON.stringify(f.request.input.command)));
  assert.ok(f.state.dialog.message.includes("/work")); assert.ok(f.state.dialog.message.includes("10"));
  assert.ok(Object.isFrozen(result.input));
});
test("captured script survives caller mutation before confirmation", async () => {
  const f = setup(), command = f.request.input.command;
  f.state.confirm = () => { f.request.input.command = "changed"; return true; };
  const result = await f.controller.admit(f.request); assert.equal(result.input.command, command);
  assert.equal(f.calls.find(row => row.method === "ordinary_admission_prepare").args.input.command, command);
  assert.ok(f.state.dialog.message.includes(JSON.stringify(command)));
});
for (const fault of ["no-ui", "false", "truthy", "user_bash", "read"]) test("refuses " + fault, async () => {
  const f = setup(); if (fault === "no-ui") f.ctx.hasUI = false;
  else if (["false", "truthy"].includes(fault)) f.state.confirm = () => fault === "false" ? false : "yes";
  else f.request.toolName = fault;
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_consume"), false);
});
for (const key of ["operation_id", "request_digest", "command_ref", "timeout_seconds", "write", "kind", "tool_name", "extra"]) test("rejects prepared ticket binding " + key, async () => {
  const f = setup(); f.state.changeTicket = ticket => { ticket[key] = key === "write" ? false : key === "timeout_seconds" ? 11 : "foreign"; };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain();
  assert.equal(methods(f).includes("ordinary_admission_issue"), false);
});
for (const fault of ["network", "backend", "services", "hard-policy", "human", "target-extra", "resolution-extra"]) test("rejects shell resolution " + fault, async () => {
  const f = setup(); f.state.changePrepared = prepared => {
    const r = prepared.resolution;
    if (fault === "hard-policy") r.policy.hard_policy = "deny";
    else if (fault === "human") r.policy.requires_human = false;
    else if (fault === "target-extra") r.target.command = "secret";
    else if (fault === "resolution-extra") r.extra = true;
    else r[fault] = fault === "services" ? ["service"] : "foreign";
  };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain(); assert.equal(methods(f).includes("ordinary_admission_issue"), false);
});
test("lost receipt reconciles once without resending consume", async () => {
  const f = setup(false); f.state.lost = true;
  assert.equal((await f.controller.admit(f.request)).ticket.write, false);
  assert.equal(methods(f).filter(x => x === "ordinary_admission_consume").length, 1);
});
test("unknown lost receipt never cleans the execution lease", async () => {
  const f = setup(); f.state.lost = true; f.state.afterConsume = () => { f.state.changeTicket = ticket => { ticket.request_digest = hash("9"); }; };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain();
  assert.equal(methods(f).includes("inspect"), false); assert.equal(methods(f).includes("cancel"), false);
});
for (const committed of [false, true]) test("known readonly cancellation uses lease cleanup committed=" + committed, async () => {
  const f = setup(false); f.state.committed = committed; f.state.afterConsume = () => f.abort.abort();
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/); await f.controller.drain();
  assert.ok(methods(f).includes("inspect")); assert.ok(methods(f).includes(committed ? "cancel" : "abort_allocation")); assert.equal(methods(f).includes("ordinary_finish"), false);
});
for (const change of ["retire", "config", "policy", "wall", "mono"]) test("late " + change + " cannot consume", async () => {
  const f = setup(); f.state.confirm = () => { if (change === "retire") f.controller.retire(); if (change === "config") f.state.config = hash("9"); if (change === "policy") f.state.generation++;
    if (change === "wall") f.state.wall += 1001; if (change === "mono") f.state.mono += 1001; return true; };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain(); assert.equal(methods(f).includes("ordinary_admission_consume"), false);
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/);
});
test("retirement is synchronous and drain reports lease cleanup failure", async () => {
  const f = setup(false); f.state.afterConsume = () => { f.state.cleanupFail = true; f.controller.retire(); };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/); await assert.rejects(f.controller.drain(), /OPERATION_CONTROL_UNAVAILABLE/);
  await assert.rejects(f.controller.admit({ ...f.request, id: "new" }), /OPERATION_CANCELED/);
});
for (const key of ["operation_id", "request_digest", "command_ref", "timeout_seconds", "write", "kind", "tool_name", "lease_id", "extra"]) test("foreign consumed ticket " + key + " stays unknown", async () => {
  const f = setup(); f.state.changeConsumed = ticket => { ticket[key] = key === "write" ? false : key === "timeout_seconds" ? 11 : "foreign"; };
  await assert.rejects(f.controller.admit(f.request), /OPERATION_/); await f.controller.drain(); assert.equal(methods(f).includes("inspect"), false);
});
for (const input of [null, {}, { command: "" }, { command: "x\0y" }, { command: "é".repeat(32769) }]) test("invalid Shell input has a fixed error before RPC", async () => {
  const f = setup(); f.request.input = input;
  await assert.rejects(f.controller.admit(f.request), /OPERATION_INPUT_INVALID/); assert.equal(f.calls.length, 0);
});
test("only explicit uncommitted allocating permits abort; unknown allocation cancels", async () => {
  const f = setup(false); f.state.leaseState = "unknown"; f.state.afterConsume = () => f.abort.abort();
  await assert.rejects(f.controller.admit(f.request), /OPERATION_CANCELED/); await f.controller.drain();
  assert.ok(methods(f).includes("cancel")); assert.equal(methods(f).includes("abort_allocation"), false);
});
test("escaped controls stay exact in confirmation without entering the ticket", async () => {
  const f = setup(); f.request.input.command = "printf '\\x1b'\n\ttrue\r";
  const result = await f.controller.admit(f.request);
  assert.ok(f.state.dialog.message.includes(JSON.stringify(f.request.input.command)));
  assert.equal(JSON.stringify(result.ticket).includes("printf"), false);
  assert.equal(Object.keys(result.ticket).length, 9);
});


test("slow real-tree preparation can pass five seconds while the original operation remains current", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(true, { timeoutMs: 20000 });
  let release;
  f.state.rpc = method => method === "ordinary_admission_prepare" ? new Promise(resolve => { release = resolve; }) : undefined;
  const outcome = f.controller.admit(f.request).then(value => ({ value }), error => ({ error }));
  for (let i = 0; i < 40 && !release; i++) await Promise.resolve();
  assert.equal(typeof release, "function");
  f.state.wall += 6000; f.state.mono += 6000; t.mock.timers.tick(6000);
  for (let i = 0; i < 40; i++) await Promise.resolve();
  const canceledEarly = methods(f).includes("ordinary_admission_cancel_request");
  release();
  const result = await outcome;
  await f.controller.drain();
  assert.equal(canceledEarly, false);
  assert.equal(result.error, undefined);
  assert.equal(result.value.ticket.state, "consumed");
  assert.equal(methods(f).filter(method => method === "ordinary_admission_consume").length, 1);
});

for (const cause of ["cancel", "deadline"]) test("slow Shell preparation resolving after " + cause + " never issues or consumes", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const f = setup(true, { timeoutMs: 20000 });
  let release;
  f.state.rpc = method => method === "ordinary_admission_prepare" ? new Promise(resolve => { release = resolve; }) : undefined;
  const outcome = f.controller.admit(f.request).then(value => ({ value }), error => ({ error }));
  for (let i = 0; i < 40 && !release; i++) await Promise.resolve();
  assert.equal(typeof release, "function");
  if (cause === "cancel") f.abort.abort();
  else { f.state.wall += 20000; f.state.mono += 20000; t.mock.timers.tick(20000); }
  const result = await outcome;
  assert.ok(result.error);
  release();
  for (let i = 0; i < 40; i++) await Promise.resolve();
  await f.controller.drain();
  assert.equal(methods(f).some(method => method === "ordinary_admission_issue" || method === "ordinary_admission_consume"), false);
  assert.equal(methods(f).includes("ordinary_admission_cancel_request"), true);
});
