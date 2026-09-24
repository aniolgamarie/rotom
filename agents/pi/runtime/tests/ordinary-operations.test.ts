import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { OrdinaryOperations } from "../ordinary-operations.ts";
import { PermissionAccess } from "../permission-access.ts";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";

function setup() {
  const root = mkdtempSync(join(tmpdir(), "ordinary-")), calls = [], manager = new AgentManager(undefined, 1);
  mkdirSync(join(root, "user-home"));
  const save = (name, value) => { const path = join(root, "state/activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, JSON.stringify(value), { mode: 0o600 }); };
  let content = Buffer.from("original"), ended = false;
  const supervisor = { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
    calls.push(method);
    if (method === "ordinary_prepare") return { operation_id: "op", lease_id: "lease", write: args.tool_name !== "read", path: join(root, "file"), request_digest: "a".repeat(64) };
    if (method === "ordinary_read") return { data_b64: content.toString("base64"), total_bytes: content.length, content_digest: "a".repeat(64) };
    if (method === "ordinary_finish") return { finished: true };
    if (method === "ordinary_stage_write") { content = Buffer.from(args.content); return { staged: true }; }
    if (method === "start") { ended = true; save("exits/lease.json", { lease_id: "lease", exit_code: 0 }); save("ordinary-results/op.json", { operation_id: "op", lease_id: "lease", result: { changed: true } }); return { state: "running" }; }
    if (method === "reconcile" || method === "inspect") return { lease_id: "lease", state: ended ? "reclaimed" : "allocating", protected: !ended, termination_evidence: ended ? { verified: true } : null };
    throw Error("unexpected method");
  } };
  const sdk = Object.fromEntries(["Read", "Write", "Edit"].map(kind => ["create" + kind + "ToolDefinition", (cwd, { operations } = {}) => ({ name: kind.toLowerCase(), parameters: {},
    async execute(id, input) {
      if (kind === "Read") return { content: [{ type: "text", text: (await operations.readFile(join(cwd, input.path))).toString() }] };
      await operations.mkdir?.(cwd);
      await operations.writeFile(join(cwd, input.path), input.content);
      return { content: [{ type: "text", text: "native success" }] };
    } })]));
  const runtime = { supervisor, instanceRoot: root, manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] }, plugins: [] }, managedRequestScope: { getStore: () => null } };
  runtime.permissionAccess = new PermissionAccess(runtime); runtime.ordinaryOperations = new OrdinaryOperations(sdk, runtime);
  const ctx = { cwd: root, sessionManager: { getSessionId: () => "session" } }, key = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key]; globalThis[key] = { manager, pi: {}, getContext: () => ctx };
  return { root, calls, manager, runtime, ctx, close: async () => { globalThis[key] = old; await manager.dispose(); } };
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
    assert.deepEqual(f.calls.slice(0, 4), ["ordinary_prepare", "ordinary_stage_write", "start", "reconcile"]);
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
