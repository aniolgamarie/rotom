import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";

function backend(kind = "managed-process") {
  const calls = [];
  let finish;
  return { calls, executor: { kind,
    execute(id) { calls.push(["execute", id]); return new Promise(resolve => { finish = resolve; }); },
    async cancel() { calls.push(["cancel"]); return undefined; },
  }, finish(value = {}) { finish({ response_text: "fixture result", terminal_status: "completed", termination_confirmed: true, external_work_empty: true, ...value }); } };
}
const flush = async () => { for (let index = 0; index < 8; index++) await Promise.resolve(); };

test("one actual AgentManager queue bounds session, managed and external execution together", async () => {
  const manager = new AgentManager(undefined, 2);
  manager.setMaxConcurrentForeground(2);
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  const first = backend("session"), second = backend(), third = backend("external");
  const ids = [first, second, third].map((value, index) => manager.spawnWithExecutor({}, { cwd }, "fixture-" + index, "task", value.executor,
    { description: "fixture", cwd, isBackground: index !== 0 }));
  await flush();
  assert.equal(first.calls.length, 1);
  assert.equal(second.calls.length, 1);
  assert.equal(third.calls.length, 0);
  assert.equal(manager.getRecord(ids[2]).status, "queued");
  first.finish(); await flush();
  assert.equal(third.calls.length, 1);
  second.finish(); third.finish(); await flush();
  assert.ok(ids.every(id => manager.getRecord(id).status === "completed"));
  await manager.dispose();
});

test("in-process resources keep lifecycle ownership without consuming the two execution slots", async () => {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "manager-resources-"));
  manager.setMaxConcurrentForeground(2);
  const resources = [backend("resource"), backend("resource")], jobs = [backend(), backend(), backend()];
  const resourceIds = resources.map((value, index) => manager.spawnWithExecutor({}, { cwd }, "listener-" + index, "owned resource", value.executor,
    { description: "listener", cwd, isBackground: true }));
  await flush();
  assert.equal(manager.hasRunning(), true); assert.equal(manager.blocksOrdinaryHelpers(), false);
  const ids = jobs.map((value, index) => manager.spawnWithExecutor({}, { cwd }, "managed-" + index, "task", value.executor,
    { description: "managed", cwd, isBackground: true }));
  await flush();
  assert.deepEqual(jobs.map(value => value.calls.length), [1, 1, 0]);
  assert.equal(manager.blocksOrdinaryHelpers(), true);
  resources[0].finish(); resources[1].finish(); await flush();
  assert.equal(jobs[2].calls.length, 0);
  jobs[0].finish(); await flush(); assert.equal(jobs[2].calls.length, 1);
  jobs[1].finish(); jobs[2].finish(); await flush();
  for (const id of [...resourceIds, ...ids]) manager.consumeControlled(id);
  await manager.dispose();
});

test("known IO helpers do not block one another, but unknown cancellation and managed work do", async () => {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "manager-io-"));
  const io = backend("external"); io.executor.activity = "io";
  const id = manager.spawnWithExecutor({}, { cwd }, "bound-io", "IO", io.executor, { description: "IO", cwd });
  await flush(); assert.equal(manager.blocksOrdinaryHelpers(), false);
  manager.abort(id); await flush(); assert.equal(manager.blocksOrdinaryHelpers(), true);
  manager.settleControlled(id, { response_text: "closed", terminal_status: "canceled", termination_confirmed: true, external_work_empty: true });
  manager.consumeControlled(id);
  assert.equal(manager.blocksOrdinaryHelpers(), false);
  assert.throws(() => manager.spawnWithExecutor({}, { cwd }, "invalid", "task", { ...backend().executor, activity: "io" },
    { description: "invalid", cwd }), /EXECUTOR_INVALID/);
  await manager.dispose();
});

test("unknown physical termination and cancel acknowledgment never release an executor slot", async () => {
  const manager = new AgentManager(undefined, 1);
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  const first = backend(), next = backend();
  const id = manager.spawnWithExecutor({}, { cwd }, "task-keeper-reader", "task", first.executor, { description: "first", cwd });
  const second = manager.spawnWithExecutor({}, { cwd }, "next", "task", next.executor, { description: "next", cwd });
  await flush();
  first.finish({ termination_confirmed: false }); await flush();
  assert.equal(manager.getRecord(id).status, "running");
  manager.abort(id); await flush();
  assert.equal(next.calls.length, 0);
  assert.equal(manager.getRecord(second).status, "queued");
  manager.settleControlled(id, { response_text: "partial", terminal_status: "canceled", termination_confirmed: true, external_work_empty: true });
  await flush();
  assert.equal(next.calls.length, 1);
  next.finish(); await flush();
  await manager.dispose();
});

test("unconsumed results survive cleanup and ordinary spawn cannot forge managed control", async () => {
  const manager = new AgentManager(undefined, 2);
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  const controlled = backend();
  const id = manager.spawnWithExecutor({}, { cwd }, "task-keeper-reader", "task", controlled.executor, { description: "fixture", cwd });
  await flush(); controlled.finish(); await flush();
  manager.clearCompleted();
  assert.ok(manager.getRecord(id));
  manager.consumeControlled(id);
  manager.clearCompleted();
  assert.equal(manager.getRecord(id), undefined);
  assert.throws(() => manager.spawn({}, { cwd }, "task-keeper-writer", "task", { description: "forged", cwd }), /AGENTCFG_MANAGED_DESCRIPTOR_REQUIRED/);
  assert.throws(() => manager.spawn({}, { cwd }, "scout", "task", { description: "forged", cwd, bypassQueue: true }), /AGENTCFG_SPAWN_FORBIDDEN/);
  assert.throws(() => manager.spawn({}, { cwd }, "scout", "task", { description: "forged", cwd, parentAgentId: "parent" }), /AGENTCFG_SPAWN_FORBIDDEN/);
  await manager.dispose();
});

test("bulk cancellation preserves physical unknown and queued ownership", async () => {
  const manager = new AgentManager(undefined, 1);
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  const first = backend(), queued = backend();
  const ids = [first, queued].map(value => manager.spawnWithExecutor({}, { cwd }, "task-keeper-reader", "task", value.executor, { description: "fixture", cwd }));
  await flush();
  assert.equal(manager.abortAll(), 2);
  await flush();
  assert.equal(manager.getRecord(ids[0]).status, "running");
  assert.equal(manager.getRecord(ids[1]).status, "queued");
  assert.equal(first.calls.filter(call => call[0] === "cancel").length, 1);
  assert.equal(queued.calls.filter(call => call[0] === "cancel").length, 1);
  assert.equal(queued.calls.filter(call => call[0] === "execute").length, 0);
  await manager.dispose();
  assert.ok(manager.getRecord(ids[0]));
  assert.equal(manager.hasRunning(), true);
});

test("synchronous executor failure retains ownership and slot until explicit evidence", async () => {
  const manager = new AgentManager(undefined, 1);
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  const broken = { kind: "external", execute() { throw new Error("fixture failure"); }, async cancel() {} };
  const id = manager.spawnWithExecutor({}, { cwd }, "fixture", "task", broken, { description: "fixture", cwd });
  const queued = backend();
  manager.spawnWithExecutor({}, { cwd }, "fixture", "task", queued.executor, { description: "fixture", cwd });
  await flush();
  assert.equal(manager.getRecord(id)?.status, "running");
  assert.equal(queued.calls.length, 0);
  await manager.dispose();
});

test("foreground ordinary resume shares managed execution capacity", async () => {
  const { bindSessionBackend } = await import("../../packages/subagents-vendor/src/agent-manager.ts");
  const manager = new AgentManager(undefined, 2), calls = [];
  const cwd = mkdtempSync(join(tmpdir(), "manager-"));
  bindSessionBackend({
    async runAgent(ctx, type, prompt, options) { const session = {}; options.onSessionCreated(session); return { responseText: "first result", session }; },
    async resumeAgent() { calls.push("resume"); return { text: "resumed" }; },
  });
  const ordinary = manager.spawn({}, { cwd }, "fixture", "task", { description: "fixture", cwd });
  await flush();
  const first = backend(), second = backend();
  for (const value of [first, second]) manager.spawnWithExecutor({}, { cwd }, "fixture", "task", value.executor, { description: "fixture", cwd });
  await flush();
  const pending = manager.resume(ordinary, "follow-up");
  await flush();
  assert.equal(calls.length, 0);
  assert.equal(manager.getRecord(ordinary).status, "queued");
  first.finish(); await flush();
  await pending;
  assert.equal(calls.length, 1);
  assert.equal(manager.getRecord(ordinary).result, "resumed");
  second.finish(); await flush();
  await manager.dispose();
});

test("UI callback failure cannot erase controlled execution ownership", async () => {
  const manager = new AgentManager(undefined, 2, () => { throw Error("synthetic UI failure"); });
  const cwd = mkdtempSync(join(tmpdir(), "manager-")), controlled = backend();
  const id = manager.spawnWithExecutor({}, { cwd }, "fixture", "task", controlled.executor, { description: "fixture", cwd });
  await flush();
  assert.equal(manager.getRecord(id).status, "running");
  assert.equal(controlled.calls.length, 1);
  controlled.finish(); await flush();
  assert.equal(manager.getRecord(id).status, "completed");
  await manager.dispose();
});

test("resource ownership is bounded independently and cannot free unknown canceled records", async () => {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "manager-resource-cap-"));
  const resources = Array.from({ length: 16 }, () => backend("resource"));
  const spawn = value => manager.spawnWithExecutor({}, { cwd }, "resource", "owned resource", value.executor, { description: "fixture", cwd });
  const ids = resources.map(spawn); await flush();
  assert.throws(() => spawn(backend("resource")), /RESOURCE_LIMIT/);
  manager.abort(ids[0]); await flush();
  assert.equal(manager.blocksOrdinaryHelpers(), true);
  assert.throws(() => spawn(backend("resource")), /RESOURCE_LIMIT/);
  resources[0].finish({ terminal_status: "canceled" }); await flush();
  const replacement = backend("resource"); spawn(replacement); await flush();
  for (const resource of resources.slice(1)) resource.finish();
  replacement.finish(); await flush(); await manager.dispose();
});

test("service ownership only permits its own model's IO and never hides managed or canceled work", async () => {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "manager-owner-"));
  const parent = backend("resource"), other = backend("resource"), model = backend("external"), managed = backend();
  const add = value => manager.spawnWithExecutor({}, { cwd }, "fixture", "fixture", value.executor, { description: "fixture", cwd });
  try {
    const parentId = add(parent), otherId = add(other); await flush();
    model.executor.activity = "model"; model.executor.service_owner_run_id = parentId;
    const modelId = add(model); await flush();
    assert.equal(manager.blocksOrdinaryHelpers(), true);
    assert.equal(manager.blocksOrdinaryHelpers(parentId), false);
    assert.equal(manager.blocksOrdinaryHelpers(otherId), true);
    add(managed); await flush(); assert.equal(manager.blocksOrdinaryHelpers(parentId), true);
    managed.finish(); await flush(); assert.equal(manager.blocksOrdinaryHelpers(parentId), false);
    manager.abort(modelId); await flush(); assert.equal(manager.blocksOrdinaryHelpers(parentId), true);
    model.finish({ terminal_status: "canceled" }); parent.finish(); other.finish(); await flush();
    const invalid = backend("external"); invalid.executor.activity = "model"; invalid.executor.service_owner_run_id = "unselected";
    assert.throws(() => add(invalid), /SERVICE_OWNER_INVALID/);
  } finally { await manager.dispose(); }
});
