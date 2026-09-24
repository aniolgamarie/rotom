import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loginCodex } from "../user-login.ts";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "delegate-login-")), calls = [];
  let state = "allocating";
  const runtime = { instanceRoot: root, manifest: { bootstrap: true, options: { model_delegate: { backends: ["codex"] } }, permission_policy: { schema_version: 1, default: "deny", rules: [] } },
    installed: { lock_identity: "a".repeat(64), slice_identity: "b".repeat(64) }, managedRequestScope: { getStore: () => null },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method) {
      calls.push(method);
      if (method === "allocate") return { lease_id: "login" };
      if (method === "inspect") return { state };
      if (method === "abort_allocation" || method === "cancel") { state = "failed"; return {}; }
      if (method === "start") {
        state = "completed";
        const path = join(root, "state/activity/exits"); mkdirSync(path, { recursive: true, mode: 0o700 });
        writeFileSync(join(path, "login.json"), JSON.stringify({ lease_id: "login", exit_code: 0 }), { mode: 0o600 }); return {};
      }
      if (method === "reconcile") return { protected: state === "allocating", termination_evidence: { verified: state !== "allocating" } };
      throw new Error("unexpected method");
    } } };
  return { root, runtime, calls };
}

test("bootstrap login is supervised and never treats CLI exit as model or account verification", async () => {
  const f = fixture();
  assert.deepEqual(await loginCodex(f.runtime, {}, { cwd: f.root }), { state: "ended", lease_id: "login", model_execution: "not-run" });
  assert.deepEqual(f.calls, ["allocate", "start", "reconcile"]);
});

test("managed callers cannot login and a queued login deadline aborts before native start", async () => {
  const f = fixture(); f.runtime.managedRequestScope.getStore = () => ({});
  await assert.rejects(loginCodex(f.runtime, {}, {}), /USER_CONTROL_REQUIRED/); assert.deepEqual(f.calls, []);
  f.runtime.managedRequestScope.getStore = () => null;
  const key = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key]; let timeout, queued;
  globalThis[key] = { manager: { spawnWithExecutor(_pi, _ctx, _type, _prompt, executor) { queued = executor; }, getRecord() { return null; }, abort() { void queued.cancel(); } } };
  try {
    const promise = loginCodex(f.runtime, {}, {}, { setTimer: callback => { timeout = callback; return 1; }, clearTimer: () => {} });
    await new Promise(resolve => setImmediate(resolve)); timeout();
    assert.equal((await promise).state, "canceled");
    await queued.execute();
    assert.equal(f.calls.includes("start"), false);
    assert.equal(f.calls.includes("abort_allocation"), true);
  } finally { globalThis[key] = old; }
});
