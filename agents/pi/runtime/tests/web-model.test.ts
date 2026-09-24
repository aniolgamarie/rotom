import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { webModel, webModels, webComplete } from "../web-model.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), managerSlot = Symbol.for("agentcfg.pi.managed.v1");
function fixture() {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "web-model-"));
  const model = { provider: "agentcfg-selected", id: "fixture-model", api: "fixture", baseUrl: "https://fixture.invalid" };
  const controller = new AbortController(), calls = [], tracked = [];
  const runtime = { cwd, owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: { task_keeper: { enabled: true } },
    web_model_bindings: { summary: { provider: model.provider, model: model.id } } },
    models: { current: { getModels: () => [model], getModel: (provider, id) => provider === model.provider && id === model.id ? model : undefined,
      async completeSimple(selected, context, options) { calls.push({ selected, context, options }); return { content: "fixture response" }; } } },
    web: { current: () => ({ controller }), track(promise) { tracked.push(promise); return promise; } } };
  globalThis[slot] = runtime; globalThis[managerSlot] = { manager, pi: {}, getContext: () => ({ cwd }) };
  return { runtime, model, controller, calls, tracked, manager, async cleanup() { await manager.dispose(); delete globalThis[slot]; delete globalThis[managerSlot]; } };
}
test("web model purposes resolve exact selected models and reject ambient aliases", async () => {
  const f = fixture();
  try {
    assert.equal(webModel("summary"), f.model); assert.deepEqual(webModels(), [f.model]);
    assert.equal(webModel("answer", undefined, f.model), f.model);
    assert.throws(() => webModel("summary", "ambient/fixture-model"), /NOT_SELECTED/);
    assert.throws(() => webModel("undeclared", undefined, f.model), /PURPOSE/);
    assert.throws(() => webModel("answer"), /NOT_SELECTED/);
  } finally { await f.cleanup(); }
});
test("web completion uses the canonical model, disables retries, and tracks until settlement", async () => {
  const f = fixture();
  try {
    await webComplete({ ...f.model, baseUrl: "https://unselected.invalid" }, { messages: [] }, { maxTokens: 200, reasoning: "low" });
    assert.equal(f.calls.length, 1); assert.equal(f.calls[0].selected, f.model);
    assert.equal(f.calls[0].options.maxRetries, 0); assert.equal(f.tracked.length, 1);
    assert.throws(() => webComplete(f.model, {}, { apiKey: "unselected" }), /OPTIONS/);
    f.controller.abort(); assert.throws(() => webComplete(f.model, {}), /abort/i);
    assert.equal(f.calls.length, 1);
  } finally { await f.cleanup(); }
});
test("runtime replacement before dispatch or response prevents unowned model results", async () => {
  const f = fixture();
  try {
    const pending = webComplete(f.model, {}); globalThis[slot] = {};
    await assert.rejects(pending, /STALE/); assert.equal(f.calls.length, 0);
    globalThis[slot] = f.runtime;
    f.runtime.models.current.completeSimple = async () => { globalThis[slot] = {}; return "stale"; };
    await assert.rejects(webComplete(f.model, {}), /STALE/);
  } finally { await f.cleanup(); }
});


test("web model calls occupy actual execution capacity and retain unknown canceled work", async () => {
  const f = fixture(); let resolveModel, started;
  const ready = new Promise(resolve => { started = resolve; });
  f.runtime.models.current.completeSimple = async () => { started(); return new Promise(resolve => { resolveModel = resolve; }); };
  try {
    const pending = webComplete(f.model, {}); const observed = assert.rejects(pending, /abort/i);
    await ready;
    assert.equal(f.manager.hasRunning(), true); assert.equal(f.manager.blocksOrdinaryHelpers(), true);
    assert.throws(() => webModel("summary"), /UNMETERED_PARENT_HELPER/);
    f.controller.abort(); await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.manager.hasRunning(), true);
    resolveModel({ content: "discard canceled result" }); await observed;
    assert.equal(f.manager.hasRunning(), false);
  } finally { await f.cleanup(); }
});

test("parallel ordinary web model helpers share the same hard two-execution limit", async () => {
  const f = fixture(), pending = [], outputs = [];
  f.runtime.manifest.options.task_keeper.enabled = false;
  f.runtime.models.current.completeSimple = () => new Promise(resolve => { pending.push(resolve); });
  const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
  try {
    for (let i = 0; i < 3; i++) outputs.push(webComplete(f.model, {}));
    await flush(); assert.equal(pending.length, 2);
    assert.equal(f.manager.listAgents().filter(row => row.status === "queued").length, 1);
    pending[0]({ content: "first" }); await flush(); assert.equal(pending.length, 3);
    pending[1]({ content: "second" }); pending[2]({ content: "third" });
    assert.deepEqual(await Promise.all(outputs), [{ content: "first" }, { content: "second" }, { content: "third" }]);
    assert.equal(f.manager.hasRunning(), false);
  } finally { await f.cleanup(); }
});


test("reasoning aliases have one explicit meaning and conflicting settings fail before dispatch", async () => {
  const f = fixture();
  try {
    await webComplete(f.model, {}, { reasoningEffort: "low" });
    assert.equal(f.calls[0].options.reasoning, "low");
    assert.throws(() => webComplete(f.model, {}, { reasoning: "high", reasoningEffort: "low" }), /CONFLICT/);
    assert.throws(() => webComplete(f.model, {}, { reasoning: "invented" }), /REASONING/);
    assert.equal(f.calls.length, 1);
  } finally { await f.cleanup(); }
});
