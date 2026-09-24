import assert from "node:assert/strict";
import { test } from "node:test";
import { readLoopGuardConfig } from "../../packages/loop-guard/config.ts";
import { assertSessionBoundary, compactionOwner, mayTransformHistory, requireOrdinaryHelper } from "../capability-policy.ts";
import sessionYolo from "../../packages/session-yolo/index.ts";
import { PermissionAccess } from "../permission-access.ts";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("loop guard reads only manifest and rejects malformed values without clamping or environment fallback", () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key], previous = process.env.PI_LOOP_GUARD_REPEAT_LIMIT;
  process.env.PI_LOOP_GUARD_REPEAT_LIMIT = "1";
  const runtime = { manifest: { options: { loop_guard: { repeatLimit: 3 } } } }; globalThis[key] = runtime;
  try {
    assert.equal(readLoopGuardConfig().repeatLimit, 3);
    for (const value of [{ repeatLimit: 20 }, { repeatLimit: "2" }, { extra: true }, { enforcementMode: "unknown" }]) {
      runtime.manifest.options.loop_guard = value;
      assert.throws(() => readLoopGuardConfig(), /AGENTCFG_LOOP_GUARD_CONFIG/);
    }
  } finally { globalThis[key] = old; if (previous === undefined) delete process.env.PI_LOOP_GUARD_REPEAT_LIMIT; else process.env.PI_LOOP_GUARD_REPEAT_LIMIT = previous; }
});

test("only one ordinary compaction owner is selected and managed scope rejects auxiliary model work", () => {
  const runtime = { owner: { role: "manager" }, manifest: { bootstrap: false, plugins: ["pi-smart-compact"], options: { compaction: { owner: "smart-compact" } }, resource_ids: { extensions: { handoff: "declared" } } },
    managedRequestScope: { getStore: () => null } };
  assert.equal(compactionOwner(runtime.manifest), "smart-compact");
  requireOrdinaryHelper(runtime, "handoff"); assert.equal(mayTransformHistory(runtime), true);
  assert.throws(() => compactionOwner({ ...runtime.manifest, options: {} }), /COMPACTION_OWNER_CONFLICT/);
  runtime.managedRequestScope.getStore = () => ({ task_id: "managed" });
  assert.throws(() => requireOrdinaryHelper(runtime, "handoff"), /UNMETERED_PARENT_HELPER/);
  assert.equal(mayTransformHistory(runtime), false);
});

test("actual session YOLO command publishes the hard-policy-backed state and does not increase permissions", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), stateKey = Symbol.for("session-yolo:state"), old = globalThis[key], oldState = globalThis[stateKey];
  const runtime = { owner: { role: "manager" }, manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] } }, managedRequestScope: { getStore: () => null } };
  runtime.permissionAccess = new PermissionAccess(runtime); globalThis[key] = runtime;
  const handlers = new Map(), commands = new Map(), cwd = mkdtempSync(join(tmpdir(), "plugin-yolo-")), notices = [];
  const ctx = { cwd, sessionManager: { getSessionId: () => "session" }, ui: { notify: text => notices.push(text) } };
  try {
    sessionYolo({ on: (name, handler) => handlers.set(name, handler), registerCommand: (name, command) => commands.set(name, command) });
    const before = runtime.permissionAccess.require().policy_digest;
    await commands.get("yolo").handler("cwd", ctx);
    assert.equal(globalThis[stateKey].effective, true); assert.equal(runtime.permissionAccess.require().policy_digest, before);
    await handlers.get("session_shutdown")({}, ctx); assert.equal(globalThis[stateKey].effective, false);
  } finally { globalThis[key] = old; globalThis[stateKey] = oldState; }
});


test("session transition blocks queued, unknown and unconsumed work, including allocations outside the mirror", async () => {
  const key = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key];
  let active = 0, running = false, pending = [];
  const runtime = { supervisor: { async call(method) { assert.equal(method, "activity_summary"); return { active_count: active, unknown_count: active }; } } };
  globalThis[key] = { manager: { hasRunning: () => running, listAgents: () => pending, isControlled: () => true } };
  try {
    await assertSessionBoundary(runtime);
    active = 1; await assert.rejects(assertSessionBoundary(runtime), /SESSION_ACTIVITY_PROTECTED/);
    active = 0; running = true; await assert.rejects(assertSessionBoundary(runtime), /SESSION_ACTIVITY_PROTECTED/);
    running = false; pending = [{ id: "result", resultConsumed: false }]; await assert.rejects(assertSessionBoundary(runtime), /SESSION_ACTIVITY_PROTECTED/);
    pending[0].resultConsumed = true; await assertSessionBoundary(runtime);
  } finally { globalThis[key] = old; }
});
