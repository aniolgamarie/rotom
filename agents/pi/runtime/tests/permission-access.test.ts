import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PermissionAccess } from "../permission-access.ts";
import { convertParentPolicy } from "../permission-policy.ts";
import { agentcfgGate, AgentcfgPolicyLoader } from "../../packages/permission-system-vendor/src/agentcfg.ts";

function fixture() {
  const cwd = mkdtempSync(join(tmpdir(), "permission-access-")), calls = [];
  const context = { instanceRoot: cwd, owner: { role: "manager" }, manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] }, options: {} },
    managedRequestScope: { getStore: () => null }, ordinaryOperations: { async preflight(event) { calls.push(["preflight", event.toolName]); return { id: event.toolCallId }; },
      async abort(ticket) { calls.push(["abort", ticket.id]); } } };
  const access = new PermissionAccess(context); context.permissionAccess = access;
  const ctx = { cwd, sessionManager: { getSessionId: () => "session" } };
  const event = { toolCallId: "call", toolName: "read", input: { path: "file" } };
  return { cwd, context, access, ctx, event, calls };
}

test("missing or malformed policy fails closed instead of returning an empty deny set", () => {
  const f = fixture();
  const missing = new PermissionAccess({ ...f.context, manifest: { permission_policy: null } });
  assert.throws(() => missing.require(), /PERMISSION_CAPABILITY_MISSING/);
  f.access.base.rules.push({ kind: "regex", pattern: ".*" });
  assert.throws(() => f.access.require());
});

test("YOLO changes native prompt state but does not alter hard policy or managed ceilings", () => {
  const f = fixture(), before = f.access.require().policy_digest;
  f.access.setMode("session", "cwd", f.cwd);
  assert.equal(f.access.yolo("session", f.cwd), true);
  assert.equal(f.access.yolo("other", f.cwd), false);
  assert.equal(f.access.require().policy_digest, before);
  f.context.managedRequestScope.getStore = () => ({ task_id: "managed" });
  assert.equal(f.access.yolo("session", f.cwd), false);
  assert.throws(() => f.access.setMode("session", "global", f.cwd), /USER_CONTROL_REQUIRED/);
});

test("actual permission adapter approves only after native decision and aborts stale or denied tickets", async () => {
  const f = fixture(), key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key]; globalThis[key] = f.context;
  try {
    assert.deepEqual(new AgentcfgPolicyLoader().loadGlobalConfig(), { permission: { "*": "ask" } });
    await agentcfgGate(f.event, f.ctx, async () => ({ block: false }));
    assert.deepEqual(f.access.take("call", "read", { path: "file" }, f.ctx), { id: "call" });
    await agentcfgGate(f.event, f.ctx, async () => ({ block: true }));
    assert.throws(() => f.access.take("call", "read", { path: "file" }, f.ctx), /PERMISSION_ADMISSION_STALE/);
    await assert.rejects(agentcfgGate(f.event, f.ctx, async () => { f.access.setMode("session", "off", f.cwd); return { block: false }; }), /PERMISSION_ADMISSION_STALE/);
    assert.equal(f.calls.filter(([kind]) => kind === "abort").length, 2);
  } finally { globalThis[key] = old; }
});


test("approval cannot cross sessions or working directories, including a switch during the prompt", async () => {
  const f = fixture(), other = { ...f.ctx, sessionManager: { getSessionId: () => "other" } };
  const ticket = await f.access.check(f.event, f.ctx);
  assert.throws(() => f.access.approve(f.event, ticket, other), /PERMISSION_ADMISSION_STALE/);
  f.access.approve(f.event, ticket, f.ctx);
  assert.throws(() => f.access.take("call", "read", f.event.input, other), /PERMISSION_ADMISSION_STALE/);
  assert.throws(() => f.access.take("call", "read", f.event.input, { ...f.ctx, cwd: tmpdir() }), /PERMISSION_ADMISSION_STALE/);
  assert.deepEqual(f.access.take("call", "read", f.event.input, f.ctx), { id: "call" });
});


test("parent file and fixed argv rules preserve denials and reject ambiguous or unknown inputs", () => {
  const f = fixture();
  const source = rules => ({ schema_version: 1, source_id: "fixture-parent", source_digest: "a".repeat(64), rules });
  const file = { id: "private", kind: "absolute-file", effect: "deny", tool_ids: ["read"], operations: ["read"], path: join(f.cwd, "private"), recursive: true };
  const command = { id: "editor", kind: "argv", effect: "deny", tool_ids: ["editor"], executable: "/fixture/editor", args: ["--fixed"] };
  const options = { roots: { project: { path: f.cwd } }, commands: { "tool:editor": { argv: ["/fixture/editor", "--fixed"] } } };
  const result = convertParentPolicy(source([file, command]), options);
  assert.deepEqual(result.policy.rules[0], { id: "private", kind: "file", effect: "deny", tool_ids: ["tk_read"], operations: ["read"], root_ref: "project", relative_path: "private", match: "subtree" });
  assert.equal(result.policy.rules[1].command_ref, "tool:editor");
  for (const invalid of [{ ...file, path: join(f.cwd, "*") }, { ...file, tool_ids: ["unknown"] }, { ...command, args: ["different"] }, { kind: "regex", pattern: ".*" }]) {
    assert.throws(() => convertParentPolicy(source([invalid]), options), /PERMISSION_UNREPRESENTABLE/);
  }
  assert.throws(() => convertParentPolicy(source([file]), { ...options, roots: { project: { path: f.cwd }, duplicate: { path: f.cwd } } }), /PERMISSION_UNREPRESENTABLE/);
});
