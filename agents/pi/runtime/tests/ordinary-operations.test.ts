import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialFileAdmission } from "../official-file-admission.ts";
import { captureOperationInput } from "../private-operation-input.ts";
import { OrdinaryOperations } from "../ordinary-operations.ts";
import { PermissionAccess } from "../permission-access.ts";
import { agentcfgGate } from "../../packages/permission-system-vendor/src/agentcfg.ts";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";

function setup() {
  const root = mkdtempSync(join(tmpdir(), "ordinary-")), calls = [], manager = new AgentManager(undefined, 1);
  mkdirSync(join(root, "user-home"));
  const save = (name, value) => { const path = join(root, "state/activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, JSON.stringify(value), { mode: 0o600 }); };
  let content = Buffer.from("original"), ended = false, prepared, consumed;
  const processIdentity = { pid: 123, start: "fixture" };
  const supervisor = { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
    calls.push(method);
    if (method === "ordinary_prepare_deferred") {
      prepared = { operation_id: "op", lease_id: null, state: "prepared", write: ["write", "edit", "rename"].includes(args.tool_name), path: join(root, "file"), request_digest: "a".repeat(64) };
      consumed = null; return { ...prepared };
    }
    if (method === "ordinary_consume") {
      assert.ok(prepared); assert.equal(args.operation_id, prepared.operation_id); assert.equal(consumed, null);
      consumed = { ...prepared, lease_id: prepared.write ? "lease" : "manager-lease", state: "consumed" }; return { ...consumed };
    }
    if (method === "ordinary_status") return { ...(consumed ?? prepared) };
    if (method === "ordinary_list") { assert.ok(consumed); return { entries: [], truncated: false }; }
    if (method === "ordinary_read") { assert.ok(consumed); return { data_b64: content.toString("base64"), total_bytes: content.length, content_digest: "a".repeat(64) }; }
    if (method === "ordinary_finish") return { finished: true };
    if (method === "abort_allocation") { assert.equal(args.lease_id, "lease"); ended = true; return { state: "reclaimed" }; }
    if (method === "ordinary_stage_write") { assert.ok(consumed); content = Buffer.from(args.content); return { staged: true }; }
    if (method === "start") { ended = true; save("exits/lease.json", { lease_id: "lease", exit_code: 0, process_identity: processIdentity }); save("ordinary-results/op.json", { schema_version: 1, operation_id: "op", lease_id: "lease", result: { changed: true } }); return { state: "running" }; }
    if (method === "reconcile" || method === "inspect") return { lease_id: "lease", state: ended ? "reclaimed" : "allocating", protected: !ended, process_identity: ended ? processIdentity : null, termination_evidence: ended ? { verified: true } : null };
    throw Error("unexpected method");
  } };
  const sdk = Object.fromEntries(["Read", "Write", "Edit"].map(kind => ["create" + kind + "ToolDefinition", (cwd, { operations } = {}) => ({ name: kind.toLowerCase(), parameters: {},
    async execute(id, input) {
      calls.push("sdk-execute");
      if (kind === "Edit") await operations.readFile(join(cwd, input.path));
      if (kind === "Read") return { content: [{ type: "text", text: (await operations.readFile(join(cwd, input.path))).toString() }] };
      await operations.mkdir?.(cwd);
      await operations.writeFile(join(cwd, input.path), input.content);
      return { content: [{ type: "text", text: "native success" }] };
    } })]));
  for (const name of ["Ls", "Find", "Grep"]) sdk["create" + name + "ToolDefinition"] = () => ({ name: name.toLowerCase(), parameters: {} });
  const runtime = { owner: { role: "manager" }, supervisor, instanceRoot: root, manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] }, plugins: [], options: {} }, managedRequestScope: { getStore: () => null } };
  runtime.permissionAccess = new PermissionAccess(runtime); runtime.ordinaryOperations = new OrdinaryOperations(sdk, runtime);
  const ctx = { cwd: root, sessionManager: { getSessionId: () => "session" } }, key = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key]; globalThis[key] = { manager, pi: {}, getContext: () => ctx };
  const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1"), oldRuntime = globalThis[runtimeKey]; globalThis[runtimeKey] = runtime;
  const installAdmission = () => {
    const fileAdmission = Object.freeze({ async admit({ toolName, input }) {
      calls.push("final-admit");
      consumed = { operation_id: "op", lease_id: ["write", "edit", "rename"].includes(toolName) ? "lease" : "manager-lease", state: "consumed",
        write: ["write", "edit", "rename"].includes(toolName), path: join(root, "file"), request_digest: "a".repeat(64), kind: "file", tool_name: toolName };
      return { ticket: { ...consumed }, input: captureOperationInput(input).value };
    } });
    runtime.ordinaryOperations = new OrdinaryOperations(sdk, runtime, { fileAdmission });
    return fileAdmission;
  };
  return { root, calls, manager, runtime, ctx, installAdmission, close: async () => { globalThis[key] = old; globalThis[runtimeKey] = oldRuntime; await manager.dispose(); } };
}

test("SDK file semantics run only after one exact permission ticket and supervised write settlement", async () => {
  const f = setup();
  try {
    const [read, write] = f.runtime.ordinaryOperations.tools(f.root);
    await assert.rejects(read.execute("missing", { path: "file" }, undefined, undefined, f.ctx), /PERMISSION_ADMISSION_STALE/);
    assert.equal(f.calls.length, 0);
    const input = { path: "file", content: "written" }, event = { toolCallId: "call", toolName: "write", input };
    const checked = await f.runtime.permissionAccess.check(event, f.ctx); f.runtime.permissionAccess.approve(event, checked, f.ctx);
    const result = await write.execute("call", input, undefined, undefined, f.ctx);
    assert.equal(result.content[0].text, "native success");
    assert.deepEqual(f.calls.slice(0, 6), ["ordinary_prepare_deferred", "ordinary_consume", "sdk-execute", "ordinary_stage_write", "start", "reconcile"]);
    await assert.rejects(write.execute("call", input, undefined, undefined, f.ctx), /PERMISSION_ADMISSION_STALE/);
  } finally { await f.close(); }
});

test("bound bash uses the same manager and verifies physical identity plus private captured output", async () => {
  const f = setup();
  try {
    const identity = { pid: 123, start: "fixture" }, realCall = f.runtime.supervisor.call;
    const save = (name, value) => {
      const path = join(f.root, "state/activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 });
      writeFileSync(path, value, { mode: 0o600 });
    };
    const checksum = "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df";
    f.runtime.supervisor.call = async (method, args) => {
      if (method === "ordinary_command_prepare") return { operation_id: "command", lease_id: "lease", kind: "command", tool_name: "bash", write: false, timeout_seconds: 1 };
      if (method === "start") {
        assert.equal(args.program, "ordinary-command");
        save("exits/lease.json", JSON.stringify({ lease_id: "lease", exit_code: 0, process_identity: identity }));
        save("outputs/lease/stdout", "ok"); save("outputs/lease/stderr", "");
        save("outputs/lease/capture.json", JSON.stringify({ complete: true, truncated: false, streams: {
          stdout: { sha256: checksum }, stderr: { sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" } } }));
        return { state: "running" };
      }
      if (method === "reconcile") return { lease_id: "lease", protected: false, termination_evidence: { verified: true }, process_identity: identity };
      if (method === "ordinary_command_finish") return { finished: true };
      return realCall(method, args);
    };
    const bash = f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === "bash");
    const input = { command: "agentcfg:build" }, event = { toolCallId: "bound", toolName: "bash", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    const result = await bash.execute("bound", input, undefined, undefined, f.ctx);
    assert.equal(result.content[0].text, "ok"); assert.equal(result.isError, false);
    assert.equal(result.details.terminationConfirmed, true);
    const spawn = f.manager.spawnWithExecutor.bind(f.manager); let selected, captured;
    f.manager.spawnWithExecutor = (...args) => { selected = args[4]; return spawn(...args); };
    await f.runtime.ordinaryOperations.write({ operation_id: "service", lease_id: "lease", kind: "command", tool_name: "bash", timeout_seconds: 1,
      execution_class: "service", service_name: "fixture" }, null, null, undefined, { onCapture(value) { captured = value.stdout; } });
    assert.equal(selected.kind, "resource"); assert.equal(selected.activity, undefined);
    assert.equal(captured.toString(), "ok");
  } finally { await f.close(); }
});


test("approval wait has only deferred prepare; exact take precedes consume and staging", async () => {
  const f = setup();
  try {
    const input = { path: "file", content: "written" }, event = { toolCallId: "call", toolName: "write", input };
    let approve; const wait = new Promise(resolve => { approve = resolve; });
    const take = f.runtime.permissionAccess.take.bind(f.runtime.permissionAccess);
    f.runtime.permissionAccess.take = (...args) => { f.calls.push("take"); return take(...args); };
    const pending = agentcfgGate(event, f.ctx, () => wait);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(f.calls, ["ordinary_prepare_deferred"]);
    f.calls.push("approve"); approve({ block: false }); await pending;
    await f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === "write").execute("call", input, undefined, undefined, f.ctx);
    assert.deepEqual(f.calls.slice(0, 7), ["ordinary_prepare_deferred", "approve", "take", "ordinary_consume", "sdk-execute", "ordinary_stage_write", "start"]);
  } finally { await f.close(); }
});

for (const name of ["read", "write", "edit", "rename", "ls", "find", "grep"]) test(name + " consumes its deferred ticket before SDK or supervisor IO", async () => {
  const f = setup();
  try {
    const input = { path: "file", content: "new", destination: "other", pattern: "test" }, event = { toolCallId: "call", toolName: name, input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    await f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === name).execute("call", input, undefined, undefined, f.ctx);
    assert.equal(f.calls[0], "ordinary_prepare_deferred"); assert.equal(f.calls[1], "ordinary_consume");
    assert.equal(f.calls.filter(value => value === "ordinary_consume").length, 1);
    if (name === "rename") assert.equal(f.calls.includes("ordinary_stage_write"), false);
  } finally { await f.close(); }
});

test("preaborted file drops only preparation and never inspects a null lease", async () => {
  const f = setup();
  try {
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, controller.signal, undefined, f.ctx), /GRANT_REVOKED/);
    assert.deepEqual(f.calls, ["ordinary_prepare_deferred", "ordinary_finish"]);
  } finally { await f.close(); }
});

test("missing manager drops preparation without acquiring a Writer", async () => {
  const f = setup();
  try {
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    globalThis[Symbol.for("agentcfg.pi.managed.v1")].manager = null;
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, undefined, undefined, f.ctx), /CAPABILITY_MISSING/);
    assert.deepEqual(f.calls, ["ordinary_prepare_deferred", "ordinary_finish"]);
  } finally { await f.close(); }
});

test("lost consume reply reconciles once via status and never resends consume", async () => {
  const f = setup();
  try {
    const real = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => { const result = await real(method, args); if (method === "ordinary_consume") throw Error("synthetic lost reply"); return result; };
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    await f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, undefined, undefined, f.ctx);
    assert.deepEqual(f.calls.slice(0, 4), ["ordinary_prepare_deferred", "ordinary_consume", "ordinary_status", "sdk-execute"]);
    assert.equal(f.calls.filter(value => value === "ordinary_consume").length, 1);
    assert.equal(f.calls.filter(value => value === "start").length, 1);
  } finally { await f.close(); }
});

for (const fault of ["unavailable", "foreign", "foreign-operation", "foreign-path", "foreign-write", "prepared", "empty-lease"]) test("unknown consume " + fault + " keeps protection and performs no IO or finish", async () => {
  const f = setup();
  try {
    const real = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => {
      if (method === "ordinary_status") {
        if (fault === "unavailable") { f.calls.push(method); throw Error("synthetic status unavailable"); }
        const status = await real(method, args);
        if (fault === "foreign") return { ...status, request_digest: "b".repeat(64) };
        if (fault === "foreign-operation") return { ...status, operation_id: "other" };
        if (fault === "foreign-path") return { ...status, path: join(f.root, "other") };
        if (fault === "foreign-write") return { ...status, write: false };
        if (fault === "empty-lease") return { ...status, lease_id: "" };
        return { ...status, state: "prepared", lease_id: null };
      }
      const result = await real(method, args); if (method === "ordinary_consume") throw Error("synthetic lost reply"); return result;
    };
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    let ticket; const take = f.runtime.permissionAccess.take.bind(f.runtime.permissionAccess);
    f.runtime.permissionAccess.take = (...args) => { ticket = take(...args); return ticket; };
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, undefined, undefined, f.ctx), /ORDINARY_CONSUME_UNKNOWN/);
    assert.equal(ticket.state, "unknown");
    await f.runtime.ordinaryOperations.finish(ticket);
    await assert.rejects(f.runtime.ordinaryOperations.abort(ticket), /ORDINARY_CONSUME_UNKNOWN/);
    assert.equal(f.calls.filter(value => value === "ordinary_consume").length, 1);
    for (const forbidden of ["sdk-execute", "ordinary_stage_write", "start", "ordinary_finish", "inspect", "cancel", "abort_allocation"]) assert.equal(f.calls.includes(forbidden), false);
  } finally { await f.close(); }
});

test("consumed ticket cannot be consumed twice and non-file kinds do not use file consume", async () => {
  const f = setup();
  try {
    const ticket = await f.runtime.ordinaryOperations.preflight({ toolName: "read", input: { path: "file" } }, f.ctx, null);
    await f.runtime.ordinaryOperations.consume(ticket);
    assert.equal(ticket.lease_id, "manager-lease"); assert.equal(ticket.state, "consumed");
    await assert.rejects(f.runtime.ordinaryOperations.consume(ticket), /ORDINARY_CONSUME_REPLAY/);
    for (const kind of ["command", "checkpoint", "service", "readseek"]) await f.runtime.ordinaryOperations.consume({ kind });
    assert.equal(f.calls.filter(value => value === "ordinary_consume").length, 1);
  } finally { await f.close(); }
});


test("native approval cancellation drops only deferred preparation", async () => {
  const f = setup();
  try {
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    await agentcfgGate(event, f.ctx, async () => ({ block: true }));
    assert.deepEqual(f.calls, ["ordinary_prepare_deferred", "ordinary_finish"]);
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, undefined, undefined, f.ctx), /PERMISSION_ADMISSION_STALE/);
  } finally { await f.close(); }
});

test("signal revoked during consume uses actual lease and stops before SDK IO", async () => {
  const f = setup();
  try {
    const controller = new AbortController(), real = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => {
      const value = await real(method, args);
      if (method === "ordinary_consume") controller.abort();
      if (["inspect", "abort_allocation"].includes(method)) assert.equal(args.lease_id, "lease");
      return value;
    };
    const input = { path: "file", content: "new" }, event = { toolCallId: "call", toolName: "write", input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root)[1].execute("call", input, controller.signal, undefined, f.ctx), /GRANT_REVOKED/);
    assert.deepEqual(f.calls, ["ordinary_prepare_deferred", "ordinary_consume", "inspect", "abort_allocation", "ordinary_finish"]);
  } finally { await f.close(); }
});

test("subrole file preflight consumes before reading and read reuses manager lease", async () => {
  const f = setup();
  try {
    const tool = f.runtime.ordinaryOperations.tools(f.root, "reader")[0];
    await tool.execute("child", { path: "file" }, undefined, undefined, f.ctx);
    assert.deepEqual(f.calls.slice(0, 4), ["ordinary_prepare_deferred", "ordinary_consume", "sdk-execute", "ordinary_read"]);
  } finally { await f.close(); }
});


for (const name of ["read", "ls"]) test(name + " consumes and reads without the global managed AgentManager", async () => {
  const f = setup();
  try {
    const input = { path: "file" }, event = { toolCallId: "call", toolName: name, input };
    f.runtime.permissionAccess.approve(event, await f.runtime.permissionAccess.check(event, f.ctx), f.ctx);
    delete globalThis[Symbol.for("agentcfg.pi.managed.v1")];
    const result = await f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === name).execute("call", input, undefined, undefined, f.ctx);
    assert.equal(result.content[0].text, name === "read" ? "original" : "No matching entries.");
    assert.deepEqual(f.calls, name === "read" ? ["ordinary_prepare_deferred", "ordinary_consume", "sdk-execute", "ordinary_read", "ordinary_finish"]
      : ["ordinary_prepare_deferred", "ordinary_consume", "ordinary_list", "ordinary_finish"]);
    for (const forbidden of ["ordinary_stage_write", "start", "inspect", "abort_allocation", "cancel"]) assert.equal(f.calls.includes(forbidden), false);
  } finally { await f.close(); }
});

for (const profile of ["pi-base", "pi-full"]) for (const name of ["read", "write", "edit", "rename", "ls", "find", "grep"])
  test(profile + " " + name + " consumes and executes without Full AgentManager", async () => {
    const f = setup(), key = Symbol.for("agentcfg.pi.managed.v1");
    try {
      f.runtime.manifest.profile_id = profile;
      f.installAdmission(); delete globalThis[key];
      const input = name === "rename" ? { path: "file", destination: "other" } : { path: "file", content: "written" };
      const event = { toolCallId: "base-call", toolName: name, input };
      const result = await f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === name).execute("base-call", input, undefined, undefined, f.ctx);
      assert.ok(result.content); assert.equal(f.calls.filter(method => method === "final-admit").length, 1);
      assert.equal(f.calls.includes("ordinary_consume"), false); assert.equal(f.calls.includes("ordinary_prepare_deferred"), false);
      assert.equal(f.calls.filter(method => method === "start").length, ["write", "edit", "rename"].includes(name) ? 1 : 0);
      if (name === "rename") assert.ok(!f.calls.includes("ordinary_stage_write"));
    } finally { await f.close(); }
  });

test("Base lost start remains unknown without finish or allocation abandonment", async () => {
  const f = setup(), key = Symbol.for("agentcfg.pi.managed.v1");
  try {
    f.runtime.manifest.profile_id = "pi-base"; f.installAdmission(); delete globalThis[key];
    f.runtime.ordinaryOperations.pause = async () => {};
    const original = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => {
      if (["start", "cancel"].includes(method)) { f.calls.push(method); throw Error("lost reply"); }
      if (["inspect", "reconcile"].includes(method)) { f.calls.push(method); return { lease_id: "lease", protected: true, state: "starting", termination_evidence: null }; }
      return original(method, args);
    };
    const input = { path: "file", content: "written" }, event = { toolCallId: "lost", toolName: "write", input };
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === "write").execute("lost", input, undefined, undefined, f.ctx), /TERMINATION_UNKNOWN/);
    assert.equal(f.calls.filter(method => method === "start").length, 1);
    assert.ok(!f.calls.includes("ordinary_finish")); assert.ok(!f.calls.includes("abort_allocation"));
  } finally { await f.close(); }
});


for (const name of ["read", "write", "edit", "rename", "ls", "find", "grep"]) test("modern " + name + " cannot use legacy permission ticket without final controller", async () => {
  const f = setup();
  try {
    f.runtime.manifest.profile_id = "pi-base";
    f.runtime.permissionAccess.take = () => { throw new Error("legacy take must not run"); };
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === name).execute("missing", { path: "file", content: "body" }, new AbortController().signal, undefined, f.ctx), /OPERATION_ADMISSION_REQUIRED/);
    assert.deepEqual(f.calls, []);
    await assert.rejects(f.runtime.ordinaryOperations.preflight({ toolName: name, input: {} }, f.ctx), /OPERATION_ADMISSION_REQUIRED/);
    assert.deepEqual(f.calls, []);
  } finally { await f.close(); }
});

test("modern SDK gets the frozen final input, cannot use a forged consumed ticket or subrole", async () => {
  const f = setup();
  try {
    f.runtime.manifest.profile_id = "pi-base"; f.installAdmission();
    f.runtime.permissionAccess.take = () => { throw new Error("legacy take must not run"); };
    const original = f.runtime.ordinaryOperations.sdk.createReadToolDefinition; let observed;
    f.runtime.ordinaryOperations.sdk.createReadToolDefinition = (...args) => {
      const definition = original(...args);
      return { ...definition, async execute(id, input, ...rest) { observed = input; assert.equal(Object.isFrozen(input), true); return definition.execute(id, input, ...rest); } };
    };
    const input = { path: "file" };
    await f.runtime.ordinaryOperations.tools(f.root).find(tool => tool.name === "read").execute("modern", input, new AbortController().signal, undefined, f.ctx);
    assert.notEqual(observed, input); assert.deepEqual(observed, input);
    const forged = { kind: "file", lease_id: "lease", operation_id: "op", state: "consumed" };
    await assert.rejects(f.runtime.ordinaryOperations.consume(forged), /OPERATION_ADMISSION_REQUIRED/);
    await assert.rejects(f.runtime.ordinaryOperations.tools(f.root, "scout").find(tool => tool.name === "read").execute("subrole", input, new AbortController().signal, undefined, f.ctx), /OPERATION_ADMISSION_REQUIRED/);
    assert.equal(f.calls.filter(method => method === "final-admit").length, 1);
    assert.equal(f.calls.includes("ordinary_consume"), false);
  } finally { await f.close(); }
});


test("filesOnly constructs all seven file tools without entering the command SDK factory", async () => {
  const f = setup();
  try {
    f.runtime.ordinaryOperations.sdk.createBashToolDefinition = () => { throw new Error("command factory must not run"); };
    assert.deepEqual(f.runtime.ordinaryOperations.tools(f.root, "main", { filesOnly: true }).map(tool => tool.name), ["read", "write", "edit", "rename", "ls", "find", "grep"]);
    assert.deepEqual(f.calls, []);
  } finally { await f.close(); }
});


test("actual final controller composes with ordinary execute and waits for UI before any read", async () => {
  const f = setup();
  try {
    f.runtime.manifest.profile_id = "pi-base";
    let approve, prepared, consumed;
    f.ctx.hasUI = true; f.ctx.ui = { confirm: () => new Promise(resolve => { approve = resolve; }) };
    const context = { configIdentity: "a".repeat(64), runtimeIdentity: "b".repeat(64), policyDigest: "c".repeat(64), projectConstraintsDigest: "d".repeat(64) };
    const physical = { operation_id: "physical", request_digest: "e".repeat(64), write: false, path: join(f.root, "file"), lease_id: null, state: "prepared" };
    f.runtime.supervisor.call = async (method, args) => {
      f.calls.push(method);
      if (method === "ordinary_admission_open") return { ...args, state: "open" };
      if (method === "ordinary_admission_prepare") {
        prepared = { schema_version: 1, operation_id: "admitted", request_id: args.request_id, context: args.context,
          private_input_ref: "nonce", operation_digest: "f".repeat(64), resolution: { kind: "file", tool_name: "read",
            target: { path: physical.path, destination: null }, read_roots: [{ path: f.root, identity: "a".repeat(64) }],
            write_roots: [], workspace_keys: [], network: "deny", services: [], backend: "guarded-files-v1",
            policy: { generation: 1, policy_digest: context.policyDigest, ceiling_digest: "a".repeat(64), hard_policy: "allow", requires_human: true } } };
        return prepared;
      }
      if (method === "ordinary_admission_status") return { admission: { operation_id: "admitted", state: "prepared" }, execution: physical };
      if (method === "ordinary_admission_issue") return { schema_version: 1, permit_id: "permit", operation_id: "admitted", operation_digest: prepared.operation_digest,
        source: "human", reviewer_identity: null, context: args.context };
      if (method === "ordinary_admission_consume") { consumed = { ...physical, lease_id: "manager-lease", state: "consumed" }; return consumed; }
      if (method === "ordinary_read") {
        assert.ok(consumed); assert.equal(args.operation_id, "physical");
        return { data_b64: Buffer.from("approved read").toString("base64"), total_bytes: 13, content_digest: "a".repeat(64) };
      }
      if (method === "ordinary_finish") return { finished: true };
      throw new Error("unexpected legacy or unsafe RPC");
    };
    const fileAdmission = createOfficialFileAdmission({ supervisor: f.runtime.supervisor, owner: { manager_activation_id: "activation", runtime_identity: context.runtimeIdentity },
      manifest: f.runtime.manifest, sessionManager: f.ctx.sessionManager, cwd: f.root, configurationSnapshot: async () => ({ ...context }),
      policySnapshot: () => ({ generation: 1, policy_digest: context.policyDigest }) });
    f.runtime.ordinaryOperations = new OrdinaryOperations(f.runtime.ordinaryOperations.sdk, f.runtime, { fileAdmission });
    f.runtime.permissionAccess.take = () => { throw new Error("legacy approval must not be used"); };
    const pending = f.runtime.ordinaryOperations.tools(f.root, "main", { filesOnly: true }).find(tool => tool.name === "read").execute("final", { path: "file" }, new AbortController().signal, undefined, f.ctx);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.includes("ordinary_admission_issue"), false); assert.equal(f.calls.includes("sdk-execute"), false);
    approve(true);
    const result = await pending; assert.equal(result.content[0].text, "approved read");
    assert.ok(f.calls.indexOf("ordinary_admission_consume") < f.calls.indexOf("sdk-execute"));
    assert.equal(f.calls.includes("ordinary_consume"), false); assert.equal(f.calls.includes("ordinary_prepare_deferred"), false);
  } finally { await f.close(); }
});
