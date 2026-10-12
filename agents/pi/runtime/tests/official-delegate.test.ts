import test from "node:test";
import assert from "node:assert/strict";
import { createOfficialDelegate } from "../official-delegate.ts";
function fixture() {
  const calls = [], manifest = { profile_id: "pi-full", plugins: ["model-delegate"], plugin_capabilities: { "model-delegate": { capability_id: "unified-delegate" } } };
  let config = { configIdentity: "fixed" }, sessionId = "actual-session", release;
  const supervisor = { async call(method, args) {
    calls.push([method, structuredClone(args)]);
    if (method === "delegate_source_open_v3") return { source_ref: "opaque-ref" };
    if (release) await release;
    return { status: "acknowledged", actions: [] };
  } };
  const manager = { getSessionId: () => sessionId };
  const input = { manifest, supervisor, sessionManager: manager, configurationSnapshot: async () => config, policySnapshot() {} };
  return { calls, input, drift() { config = { configIdentity: "changed" }; }, switch() { sessionId = "other-session"; }, pause(promise) { release = promise; } };
}
const submit = { schema_version: 3, action: "submit", request_id: "stable", backend: "pi", mode: "review", preset: "review", task: "literal", model: { provider_id: "selected", model_id: "model" }, cwd: "/owned", timeout_seconds: 30 };
test("Full source uses actual session and exact action, never model issuer fields", async () => {
  const f = fixture(), controller = createOfficialDelegate(f.input);
  assert.equal(f.calls.length, 0);
  assert.equal((await controller.tool.execute("id", submit)).isError, false);
  assert.deepEqual(f.calls, [["delegate_source_open_v3", { session_id: "actual-session" }], ["delegate_action_v3", { source_ref: "opaque-ref", action: submit }]]);
  for (const patch of [{ source_ref: "cli-ref" }, { budget: {} }, { mode: "implement" }, { allow_workspace_write: true }, { worktree_root: "/other" }]) {
    assert.equal((await controller.tool.execute("id", { ...submit, ...patch })).isError, true);
  }
  assert.equal(f.calls.length, 2);
});
test("session replacement retires old tool synchronously and drains late action without resurrection", async () => {
  const f = fixture(), controller = createOfficialDelegate(f.input);
  let resolve; f.pause(new Promise(done => { resolve = done; }));
  const result = controller.tool.execute("id", submit);
  while (f.calls.length < 2) await new Promise(done => setImmediate(done));
  controller.retire();
  assert.equal((await controller.tool.execute("late", submit)).isError, true);
  resolve(); assert.equal((await result).isError, true); await controller.drain();
  assert.equal(f.calls.length, 2);
});
test("configuration drift and Base absent selection create no new control call", async () => {
  const f = fixture(), controller = createOfficialDelegate(f.input);
  await controller.tool.execute("id", submit); f.drift();
  assert.equal((await controller.tool.execute("next", submit)).isError, true);
  assert.equal(f.calls.length, 2);
  assert.throws(() => createOfficialDelegate({ ...f.input, manifest: { ...f.input.manifest, profile_id: "pi-base" } }), /CAPABILITY_UNAVAILABLE/);
});
