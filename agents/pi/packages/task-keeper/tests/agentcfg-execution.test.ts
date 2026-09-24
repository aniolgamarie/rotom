import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { AsyncLocalStorage } from "node:async_hooks";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Store } from "../src/store/database.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { ManagedExecution } from "../src/orchestration/managed-execution.ts";
import { descriptor, fixture } from "../../../runtime/tests/fixtures.ts";
import { registerManagedRpc } from "@agentcfg/pi-runtime/managed-rpc";
import { EventEmitter } from "node:events";
import { digest } from "@agentcfg/pi-runtime/managed-types";
import { PermissionAccess } from "@agentcfg/pi-runtime/permission-access";

function setup() {
  const root = mkdtempSync(join(tmpdir(), "managed-step-")), home = join(root, "instance/pi-home"), cwd = join(root, "candidate");
  mkdirSync(home, { recursive: true }); mkdirSync(cwd);
  const f = fixture(), emitter = new EventEmitter();
  const events = { emit: (key, value) => emitter.emit(key, value), on(key, fn) { emitter.on(key, fn); return () => emitter.off(key, fn); } };
  const store = new Store(join(home, "task-keeper")), owner = store.claimOwner("scope", "owner");
  store.put("managed-jobs", "task", { id: "task", workScope: "scope", workflow: "inspect", goal: "fixture goal", cwd, sourceCwd: cwd,
    createdAt: Date.now(), parentSessionId: "session", schedule: { admittedAt: Date.now(), deadline: null } });
  const text = '---\nname: task-keeper-reader\n---\n\nRead the project.\n', path = join(root, "reader.md"); writeFileSync(path, text);
  writeFileSync(join(home, "models.json"), JSON.stringify({ providers: { "agentcfg-fixture": { api: "openai-completions", baseUrl: "https://fixture.invalid/v1",
    apiKey: "$AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA", models: [{ id: "selected", input: ["text"] }] } } }));
  const calls = [];
  const runtime = { owner: { ...f.owner, role: "manager" }, instanceRoot: join(root, "instance"), managedRequestScope: new AsyncLocalStorage(),
    installed: { runtime_identity: "b".repeat(64), lock_identity: "c".repeat(64), slice_identity: "d".repeat(64) },
    roleManifest: { roles: [{ id: "task-keeper-reader", managed: true, path, compiled_digest: createHash("sha256").update(text).digest("hex"),
      tools: ["tk_read", "structured_output"], model: { provider: "agentcfg-fixture", model: "selected" }, read_roots: ["project"], write_roots: [] }] },
    manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] }, options: {
      task_keeper: { enabled: true, check_ids: ["unit"], second_view_enabled: false, limits: { model_requests: 20, model_turns: 20, wall_seconds: 1800 } },
      network: { routes: { direct: { mode: "direct", provider_ids: ["fixture"] } } } } },
    supervisor: { async call(method, args) {
      calls.push({ method, args });
      if (method === "workspace_identity") return { workspace_key: "a".repeat(64), worktree_path: cwd };
      if (method === "workspace_snapshot") return { snapshot_digest: "d".repeat(64) };
      if (method === "allocate") return { lease_id: "lease", allocation_id: "lease", grant_generation: 1, workspace_write_lease_ids: [] };
      throw Error("unexpected method");
    } } };
  runtime.permissionAccess = new PermissionAccess(runtime);
  const config = { roles: { scout: { route: "reader", profileRef: "reader" } }, routes: { reader: { provider: "agentcfg-fixture", model: "selected", network: "direct" } }, executionProfiles: { reader: { thinking: "off" } } };
  const adapter = new SubagentsAdapter({ events }, store, config, owner, runtime);
  const off = registerManagedRpc(events, f.bridge);
  return { root, cwd, store, owner, runtime, adapter, config, calls, off };
}

test("business step prepares one durable attempt and closed worker context without dispatching a model", async () => {
  const f = setup();
  try {
    const execution = new ManagedExecution(f.adapter, f.store, f.owner, f.config, f.runtime);
    const input = { jobId: "task", stepId: "inspect", role: "scout", task: "inspect fixture", cwd: f.cwd, parentIntentId: "step-intent" };
    const prepared = await execution.prepare(input);
    assert.equal(prepared.descriptor.continuation_of, null);
    assert.equal(prepared.descriptor.allocation_id, "lease");
    const context = JSON.parse(readFileSync(join(f.store.root, "dispatches", prepared.attempt.attempt_id + ".json"), "utf8"));
    assert.equal(context.context.manager_run_id, null);
    assert.deepEqual(context.context.database.owner, f.owner);
    assert.ok(context.context.prompt.includes("structured_output"));
    assert.equal((await execution.prepare(input)).attempt.attempt_id, prepared.attempt.attempt_id);
    assert.equal(f.calls.filter(call => call.method === "allocate").length, 1);
    assert.equal(f.calls.some(call => call.method === "start"), false);
  } finally { f.off(); f.store.close(); }
});


test("missing or incomplete parent permission bridge fails before task allocation", async () => {
  const f = setup();
  try {
    const execution = new ManagedExecution(f.adapter, f.store, f.owner, f.config, f.runtime);
    const input = { jobId: "task", stepId: "inspect", role: "scout", task: "fixture", cwd: f.cwd };
    f.runtime.permissionAccess = undefined;
    await assert.rejects(() => execution.prepare(input), /PERMISSION_CAPABILITY_MISSING/);
    assert.equal(f.calls.length, 0);
    const deny = { id: "private", kind: "file", effect: "deny", tool_ids: ["tk_read"], operations: ["read"], root_ref: "project", relative_path: "private", match: "subtree" };
    f.runtime.manifest.permission_policy.rules = [deny];
    f.runtime.permissionAccess = { parentSnapshot: () => ({ policy: f.runtime.manifest.permission_policy,
      policy_digest: digest(f.runtime.manifest.permission_policy), generation: 1, inherited_denials: [] }) };
    await assert.rejects(() => execution.prepare(input), /PARENT_DENIALS_MISSING/);
    assert.equal(f.calls.length, 0);
  } finally { f.off(); f.store.close(); }
});
