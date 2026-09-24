import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { ProcessManager } from "../../packages/processes-vendor/src/manager/index.ts";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { OrdinaryOperations } from "../ordinary-operations.ts";

const hash = value => createHash("sha256").update(value).digest("hex");
test("all process views use the existing queue, show queued instead of a fake pid, and stream supervised logs", async () => {
  const root = mkdtempSync(join(tmpdir(), "process-bridge-")), shared = new AgentManager(undefined, 1), calls = [];
  mkdirSync(join(root, "user-home"));
  const key = Symbol.for("agentcfg.pi.runtime.v1"), bridgeKey = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key], oldBridge = globalThis[bridgeKey];
  let ended = false, started = false, release;
  const identity = { pid: 901, start_time: "fixture" };
  const save = (name, body) => { const path = join(root, "state/activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, body, { mode: 0o600 }); };
  const runtime = { owner: { role: "manager" }, instanceRoot: root, manifest: { plugins: ["pi-processes"], options: {}, permission_policy: {} },
    managedRequestScope: { getStore: () => null }, supervisor: { options: { endpoint: join(root, "state/activity/control/control.json") }, async call(method, args) {
      calls.push(method);
      if (method === "ordinary_command_prepare") { assert.equal(args.tool_name, "process"); return { operation_id: "op", lease_id: "lease", kind: "command", tool_name: "process", write: false, timeout_seconds: 5 }; }
      if (method === "start") { assert.equal(args.program, "ordinary-command"); started = true; return { state: "running" }; }
      if (method === "inspect" || method === "reconcile") return { lease_id: "lease", state: ended ? "reclaimed" : started ? "running" : "allocating", process_identity: identity,
        protected: !ended, termination_evidence: ended ? { verified: true } : null };
      if (method === "ordinary_command_output") return { events: args.cursor === 0 && started ? [{ seq: 1, stream: "stdout", data_b64: Buffer.from("ready\n").toString("base64") }] : [],
        next_cursor: started ? 1 : 0, dropped: false, has_more: false, complete: ended };
      if (method === "ordinary_command_stdin") return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: args.end };
      if (method === "ordinary_command_finish") return { finished: true };
      throw Error("unexpected control " + method);
    } } };
  runtime.ordinaryOperations = new OrdinaryOperations({}, runtime);
  globalThis[key] = runtime; globalThis[bridgeKey] = { manager: shared, pi: {}, getContext: () => ({ cwd: root }) };
  const occupied = shared.spawnWithExecutor({}, { cwd: root }, "fixture", "fixture", { kind: "session", manager_run_id: "occupied",
    execute: () => new Promise(resolve => { release = resolve; }), cancel: async () => undefined }, { description: "fixture", cwd: root });
  const manager = new ProcessManager();
  try {
    const row = await manager.start("server", "agentcfg:server", root);
    assert.equal(row.status, "queued"); assert.equal(row.pid, -1); assert.equal(started, false);
    const onStart = new Promise(resolve => { const off = manager.onEvent(event => { if (event.type === "process_started") { off(); resolve(event); } }); });
    const onOutput = new Promise(resolve => { const off = manager.onEvent(event => { if (event.type === "process_output_changed") { off(); resolve(event); } }); });
    release({ response_text: "fixture done", terminal_status: "completed", termination_confirmed: true, external_work_empty: true });
    await onStart; await onOutput;
    assert.equal(manager.get(row.id).pid, 901);
    assert.deepEqual(manager.getOutput(row.id).stdout, ["ready"]);
    assert.deepEqual(await manager.writeToStdin(row.id, "hello\n"), { ok: true });
    const onEnd = new Promise(resolve => { const off = manager.onEvent(event => { if (event.type === "process_ended") { off(); resolve(event); } }); });
    save("outputs/lease/stdout", "ready\n"); save("outputs/lease/stderr", "");
    save("outputs/lease/capture.json", JSON.stringify({ complete: true, truncated: false, streams: { stdout: { sha256: hash("ready\n") }, stderr: { sha256: hash("") } } }));
    save("exits/lease.json", JSON.stringify({ lease_id: "lease", exit_code: 0, process_identity: identity }));
    ended = true; await onEnd;
    assert.equal(manager.get(row.id).success, true); assert.equal(shared.hasRunning(), false);
    assert.equal(calls.filter(method => method === "start").length, 1);
    assert.equal(manager.clearFinished(), 1);
    shared.consumeControlled(occupied); shared.removeConsumedControlled(occupied);
  } finally { await manager.cleanup(); await shared.dispose(); globalThis[key] = old; globalThis[bridgeKey] = oldBridge; }
});

test("cancel acknowledgment cannot clear unknown activity or delete its log view", async () => {
  const root = mkdtempSync(join(tmpdir(), "process-unknown-")), key = Symbol.for("agentcfg.pi.runtime.v1"), bridgeKey = Symbol.for("agentcfg.pi.managed.v1");
  const old = globalThis[key], oldBridge = globalThis[bridgeKey], calls = []; let stopped = false;
  const runtime = { owner: { role: "manager" }, instanceRoot: root, manifest: { plugins: ["pi-processes"], options: {} }, managedRequestScope: { getStore: () => null },
    supervisor: { async call(method, args) {
      calls.push([method, args]);
      if (method === "ordinary_command_prepare") return { operation_id: "op", lease_id: "lease", kind: "command", tool_name: "process", write: false, timeout_seconds: 20 };
      if (method === "inspect" || method === "reconcile") return { lease_id: "lease", state: stopped ? "reclaimed" : "running", protected: !stopped, termination_evidence: stopped ? { verified: true } : null };
      if (method === "cancel") return { accepted: true, termination_confirmed: false };
      if (method === "ordinary_command_output") return { events: [], next_cursor: 0, has_more: false, dropped: false, complete: stopped };
      if (method === "ordinary_command_finish") return { finished: true };
      throw Error("unexpected method");
    } }, ordinaryOperations: { async write(ticket, _content, _digest, _signal, callbacks) {
      ticket.manager_run_id = "run"; await callbacks.onStarted({ lease_id: "lease", process_identity: { pid: 902 } });
      throw Error("TERMINATION_UNKNOWN");
    } } };
  globalThis[key] = runtime; globalThis[bridgeKey] = { manager: { abort() {}, isControlled: () => false } };
  const manager = new ProcessManager();
  try {
    const row = await manager.start("unknown", "agentcfg:server", root);
    const result = await manager.kill(row.id, { signal: "SIGKILL", timeoutMs: 0 });
    assert.equal(result.ok, false); assert.equal(result.reason, "timeout");
    assert.equal(manager.get(row.id).status, "terminate_timeout"); assert.equal(manager.clearFinished(), 0);
    assert.equal(calls.find(([method]) => method === "cancel")[1].force, true);
    const done = new Promise(resolve => { const off = manager.onEvent(event => { if (event.type === "process_ended") { off(); resolve(); } }); });
    stopped = true;
    // 生产观察定时器不保活主进程；测试必须自己持有有界等待，不能借其他用例的句柄。
    let deadline;
    try {
      await Promise.race([done, new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error("reconciliation timeout")), 1000); })]);
    } finally { clearTimeout(deadline); }
    assert.equal(manager.get(row.id).success, false); assert.equal(manager.clearFinished(), 1);
  } finally { stopped = true; await manager.cleanup(); globalThis[key] = old; globalThis[bridgeKey] = oldBridge; }
});
