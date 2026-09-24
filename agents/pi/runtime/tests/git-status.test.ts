import assert from "node:assert/strict";
import { test } from "node:test";
import { parseGitStatus, inspectGitStatus } from "../git-status.ts";
import extension from "../../extensions/dirty-repo-guard.ts";

const ok = stdout => ({ exitCode: 0, terminationConfirmed: true, truncated: false, stdout, stderr: "" });
const key = Symbol.for("agentcfg.pi.runtime.v1");

test("porcelain NUL parsing counts newline names and renames without interpreting filenames", () => {
  assert.deepEqual(parseGitStatus(ok("")), { status: "clean", changedFiles: 0 });
  assert.deepEqual(parseGitStatus(ok(" M line\nbreak\0R  new name\0old name\0?? 未跟踪\0UU conflict\0")), { status: "dirty", changedFiles: 4 });
  for (const result of [ok(" M truncated"), ok("R  missing source\0"), ok("  invalid\0"), ok("garbage\0"),
    { ...ok(""), exitCode: 128 }, { ...ok(""), stderr: "warning: cannot read directory" }, { ...ok(""), truncated: undefined }, { ...ok(""), truncated: true }, { ...ok(""), terminationConfirmed: false }]) {
    assert.throws(() => parseGitStatus(result), /GIT_STATUS/);
  }
});

function fixture() {
  const calls = [], handlers = new Map(), messages = [];
  const runtime = { owner: { role: "manager" }, manifest: { resource_ids: { extensions: { "dirty-repo-guard": "entry" } } },
    supervisor: { async call(method) {
      calls.push(method);
      if (method === "activity_summary") return { active_count: 0 };
      if (method === "ordinary_git_status_prepare") return { operation_id: "status", kind: "command" };
      if (method === "ordinary_command_finish") return { finished: true };
      throw Error("unexpected method");
    } }, ordinaryOperations: { async write() { calls.push("controlled-execution"); return ok(" M file\0"); } } };
  const context = { cwd: "/fixture", hasUI: true, ui: { async select() { return "继续"; }, notify(message) { messages.push(message); } } };
  extension({ on(name, handler) { handlers.set(name, handler); }, exec() { throw Error("raw Git forbidden"); } });
  return { runtime, context, handlers, calls, messages };
}

test("guard blocks failed, truncated and headless checks; dirty UI requires explicit choice", async () => {
  const { runtime, context, handlers, calls, messages } = fixture();
  globalThis[key] = runtime;
  try {
    const run = () => handlers.get("session_before_switch")({ reason: "new" }, context);
    assert.equal(await run(), undefined);
    assert.ok(calls.includes("controlled-execution") && calls.includes("ordinary_command_finish"));
    context.hasUI = false;
    assert.deepEqual(await run(), { cancel: true });
    context.hasUI = true; context.ui.select = async () => undefined;
    assert.deepEqual(await run(), { cancel: true });
    runtime.ordinaryOperations.write = async () => ok("");
    assert.equal(await run(), undefined);
    for (const result of [{ ...ok(""), exitCode: 128 }, { ...ok(""), truncated: true }]) {
      runtime.ordinaryOperations.write = async () => result;
      assert.deepEqual(await handlers.get("session_before_fork")({}, context), { cancel: true });
    }
    assert.equal(messages.length, 2);
    delete globalThis[key];
    assert.deepEqual(await run(), { cancel: true });
  } finally { delete globalThis[key]; }
});

test("non-repository needs no process; activity and managed contexts fail closed", async () => {
  const { runtime, context, calls } = fixture();
  runtime.supervisor.call = async method => {
    calls.push(method);
    return method === "activity_summary" ? { active_count: 0 } : { status: "not-repository" };
  };
  assert.equal((await inspectGitStatus(runtime, context)).status, "not-repository");
  assert.ok(!calls.includes("controlled-execution"));
  runtime.managedRequestScope = { getStore: () => ({ task: true }) };
  await assert.rejects(inspectGitStatus(runtime, context), /GIT_STATUS_CONTEXT/);
  delete runtime.managedRequestScope;
  runtime.supervisor.call = async () => ({ active_count: 1 });
  await assert.rejects(inspectGitStatus(runtime, context), /SESSION_ACTIVITY_PROTECTED/);
});

test("actual shared manager executes status once and consumes only verified captured results", async () => {
  const { AgentManager } = await import("../../packages/subagents-vendor/src/agent-manager.ts");
  const { OrdinaryOperations } = await import("../ordinary-operations.ts");
  const { mkdtempSync, mkdirSync, writeFileSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const { createHash } = await import("node:crypto");
  const root = mkdtempSync(join(tmpdir(), "git-status-mock-")), manager = new AgentManager(undefined, 1);
  mkdirSync(join(root, "user-home"));
  const identity = { pid: 123, start: "fixture" }, calls = [];
  const save = (name, value) => {
    const path = join(root, "state/activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 });
    writeFileSync(path, value, { mode: 0o600 });
  };
  const runtime = { owner: { role: "manager" }, instanceRoot: root, manifest: { resource_ids: { extensions: { "dirty-repo-guard": "entry" } } },
    supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
      calls.push(method);
      if (method === "activity_summary") return { active_count: 0 };
      if (method === "ordinary_git_status_prepare") return { operation_id: "status", lease_id: "lease", kind: "command", tool_name: "bash", write: false, timeout_seconds: 10 };
      if (method === "start") {
        assert.equal(args.program, "ordinary-command");
        const stdout = " M changed\0", stderr = "";
        save("exits/lease.json", JSON.stringify({ lease_id: "lease", process_identity: identity, exit_code: 0 }));
        save("outputs/lease/stdout", stdout); save("outputs/lease/stderr", stderr);
        save("outputs/lease/capture.json", JSON.stringify({ complete: true, truncated: false,
          streams: Object.fromEntries(Object.entries({ stdout, stderr }).map(([name, value]) => [name, { sha256: createHash("sha256").update(value).digest("hex") }])) }));
        return { state: "running" };
      }
      if (method === "reconcile") return { lease_id: "lease", protected: false, termination_evidence: { verified: true }, process_identity: identity };
      if (method === "ordinary_command_finish") return { finished: true };
      throw Error("unexpected method " + method);
    } } };
  runtime.ordinaryOperations = new OrdinaryOperations({}, runtime);
  const managerKey = Symbol.for("agentcfg.pi.managed.v1"), context = { cwd: root };
  globalThis[managerKey] = { manager, pi: {}, getContext: () => context };
  try {
    assert.deepEqual(await inspectGitStatus(runtime, context), { status: "dirty", changedFiles: 1 });
    assert.equal(calls.filter(value => value === "start").length, 1);
    assert.equal(manager.listAgents().length, 0);
    assert.equal(calls.at(-1), "ordinary_command_finish");
  } finally { delete globalThis[managerKey]; await manager.dispose(); }
});
