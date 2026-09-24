import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { OrdinaryOperations } from "../ordinary-operations.ts";
import { checkpointClient } from "../checkpoints.ts";
import extension from "../../extensions/git-checkpoint.ts";

const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1"), managerKey = Symbol.for("agentcfg.pi.managed.v1");

test("checkpoint uses the existing manager and waits for independent termination proof", async () => {
  const root = mkdtempSync(join(tmpdir(), "checkpoint-mock-")), calls = [], manager = new AgentManager(undefined, 1);
  mkdirSync(join(root, "user-home"), { mode: 0o700 });
  const identity = { pid: 123, start: "fixture" };
  const save = (name, value) => { const file = join(root, "state/activity", name); mkdirSync(join(file, ".."), { recursive: true, mode: 0o700 }); writeFileSync(file, JSON.stringify(value), { mode: 0o600 }); };
  let finished = false;
  const runtime = { owner: { role: "manager" }, instanceRoot: root, manifest: { resource_ids: { extensions: { "git-checkpoint": "entry" } } },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
      calls.push(method);
      if (method === "activity_summary") return { active_count: 0 };
      if (method === "ordinary_checkpoint_prepare") return { operation_id: "cp", lease_id: "lease", kind: "checkpoint", tool_name: "checkpoint", write: true, timeout_seconds: 10 };
      if (method === "start") {
        assert.equal(args.program, "checkpoint");
        save("exits/lease.json", { lease_id: "lease", exit_code: 0, process_identity: identity });
        save("ordinary-results/cp.json", { lease_id: "lease", operation_id: "cp", result: { status: "completed", checkpoint_id: "snapshot", files: 1 } });
        finished = true; return { state: "running" };
      }
      if (method === "reconcile") return { lease_id: "lease", protected: !finished, termination_evidence: { verified: finished }, process_identity: identity };
      throw Error("unexpected method " + method);
    } } };
  runtime.ordinaryOperations = new OrdinaryOperations({}, runtime);
  const context = { cwd: root, hasUI: false, sessionManager: { getSessionId: () => "session" } };
  globalThis[managerKey] = { manager, pi: {}, getContext: () => context };
  try {
    const result = await checkpointClient(runtime, context).capture("entry");
    assert.equal(result.checkpoint_id, "snapshot");
    assert.equal(calls.filter(value => value === "start").length, 1);
    assert.ok(!calls.includes("ordinary_stage_write"));
    assert.equal(manager.listAgents().length, 0);
  } finally { delete globalThis[managerKey]; }
});

test("extension keeps persisted checkpoints after agent_end and previews before a confirmed fork restore", async () => {
  const handlers = new Map(), commands = new Map(), calls = [], messages = [];
  const runtime = { owner: { role: "manager" }, manifest: { resource_ids: { extensions: { "git-checkpoint": "entry" } } },
    supervisor: { async call(method, args) {
      calls.push(method);
      if (method === "activity_summary") return { active_count: 0 };
      if (method === "ordinary_checkpoint_list") { assert.equal(args.entry_id, "entry"); return { checkpoints: [{ entry_id: "entry", checkpoint_id: "saved" }] }; }
      if (method === "ordinary_checkpoint_preview") return { checkpoint_id: "saved", before_digest: "before", scope_digest: "scope", write_count: 1, delete_count: 0 };
      if (method === "ordinary_checkpoint_prepare") { assert.equal(args.before_digest, "before"); return { kind: "checkpoint" }; }
      throw Error("unexpected method");
    } }, ordinaryOperations: { async write() { calls.push("restore"); return { status: "completed", backup_id: "backup" }; } } };
  globalThis[runtimeKey] = runtime;
  try {
    extension({ on(name, callback) { handlers.set(name, callback); }, registerCommand(name, command) { commands.set(name, command); } });
    assert.equal(handlers.has("agent_end"), false);
    assert.ok(commands.has("checkpoint") && commands.has("checkpoint-restore"));
    const context = { cwd: "/fixture", hasUI: true, sessionManager: { getSessionId: () => "session" }, ui: {
      async select() { calls.push("confirm"); return "恢复"; }, notify(value) { messages.push(value); } } };
    await handlers.get("session_before_fork")({ entryId: "entry" }, context);
    assert.ok(calls.indexOf("ordinary_checkpoint_preview") < calls.indexOf("confirm"));
    assert.ok(calls.indexOf("confirm") < calls.indexOf("restore"));
    assert.match(messages[0], /backup/);
    calls.length = 0;
    context.hasUI = false;
    await handlers.get("session_before_fork")({ entryId: "entry" }, context);
    assert.ok(!calls.includes("restore"));
    context.hasUI = true;
    runtime.ordinaryOperations.write = async () => ({ status: "partial", backup_id: "recovery-backup" });
    const failed = await handlers.get("session_before_fork")({ entryId: "entry" }, context);
    assert.deepEqual(failed, { cancel: true });
    assert.ok(messages.some(value => value.includes("recovery-backup")));
  } finally { delete globalThis[runtimeKey]; }
});
