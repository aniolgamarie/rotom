import assert from "node:assert/strict";
import { test } from "node:test";
import compact, { resolveModels } from "../../packages/smart-compact-vendor/dist/index.js";

test("actual smart-compact factory gates every tool and command and owns refused compaction without native fallback", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key], model = { provider: "fixture", id: "selected" };
  const runtime = { owner: { role: "manager" }, instanceRoot: "/fixture/instance", manifest: { plugins: ["pi-smart-compact"], options: {} },
    managedRequestScope: { getStore: () => null }, models: { current: {
      getModel(provider, id) { return provider === model.provider && id === model.id ? model : undefined; },
      getModels() { return [model]; },
    } } };
  globalThis[key] = runtime;
  const hooks = new Map(), tools = [], commands = [];
  try {
    compact({ on(name, handler) { const entries = hooks.get(name) ?? []; entries.push(handler); hooks.set(name, entries); },
      registerTool(tool) { tools.push(tool); }, registerCommand(name, command) { commands.push({ name, ...command }); },
      getActiveTools() { return []; }, setActiveTools() { throw Error("should not activate tools during factory"); } });
    assert.deepEqual(tools.map(tool => tool.name).sort(), ["smart_compact", "smart_recall", "smart_save_memory"]);
    assert.deepEqual(commands.map(command => command.name), ["smart-compact"]);
    assert.deepEqual(resolveModels({ model }, undefined, {}), { segModel: model, sumModel: model, verifyModel: model });
    assert.throws(() => resolveModels({ model }, undefined, { summaryModel: "fixture/missing" }), /NOT_SELECTED/);
    runtime.managedRequestScope.getStore = () => ({ task_id: "managed" });
    for (const tool of tools) await assert.rejects(tool.execute("call", {}, undefined, undefined, {}), /UNMETERED_PARENT_HELPER/);
    await assert.rejects(commands[0].handler("restore", {}), /UNMETERED_PARENT_HELPER/);
    assert.equal(hooks.get("session_before_compact").length, 1);
    assert.deepEqual(await hooks.get("session_before_compact")[0]({}, {}), { cancel: true });
  } finally { globalThis[key] = previous; }
});
