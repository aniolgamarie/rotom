import assert from "node:assert/strict";
import { test } from "node:test";
import { pluginModelMethod } from "../plugin-model.ts";

test("plugin helpers use the current constrained runtime, zero nested retries and selected capability", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key], calls = [];
  const runtime = { owner: { role: "manager" }, manifest: { bootstrap: false, plugins: ["pi-btw", "pi-smart-compact"], options: {} },
    managedRequestScope: { getStore: () => null }, models: { current: { completeSimple(model, context, options) { calls.push({ model, context, options }); return "fixture"; } } } };
  globalThis[key] = runtime;
  try {
    const helper = pluginModelMethod("pi-btw", "completeSimple");
    assert.equal(helper({ id: "selected" }, { messages: [] }, { maxRetries: 8 }), "fixture");
    assert.equal(calls[0].options.maxRetries, 0);
    runtime.models.current.completeSimple = () => "replacement";
    assert.equal(helper({}, {}), "replacement");
    assert.throws(() => pluginModelMethod("unselected", "completeSimple")({}, {}), /CAPABILITY_NOT_SELECTED/);
    runtime.managedRequestScope.getStore = () => ({ task_id: "task" });
    assert.throws(() => helper({}, {}), /UNMETERED_PARENT_HELPER/);
  } finally { globalThis[key] = old; }
});

test("out-of-band helper cannot bypass a running managed task after async scope exits", () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), bridge = Symbol.for("agentcfg.pi.managed.v1"), old = globalThis[key], oldBridge = globalThis[bridge];
  globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["pi-smart-compact"], options: { task_keeper: { enabled: true } } },
    managedRequestScope: { getStore: () => null }, models: { current: { stream: () => assert.fail("must not send") } } };
  globalThis[bridge] = { manager: { hasRunning: () => true } };
  try { assert.throws(() => pluginModelMethod("pi-smart-compact", "stream")({}, {}), /UNMETERED_PARENT_HELPER/); }
  finally { globalThis[key] = old; globalThis[bridge] = oldBridge; }
});

test("plugin state roots and read-only settings come from the explicit instance, never ambient HOME", async () => {
  const { pluginSettings, pluginAgentDir, managedSettingWrite } = await import("../plugin-settings.ts");
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key];
  const runtime = { owner: { role: "manager" }, instanceRoot: "/fixture/selected-instance", manifest: { plugins: ["pi-btw"], options: { btw: { thinkingLevel: "low" } } } };
  globalThis[key] = runtime;
  try {
    assert.equal(pluginAgentDir(), "/fixture/selected-instance/pi-home");
    const settings = pluginSettings("pi-btw", "btw"); settings.thinkingLevel = "high";
    assert.equal(runtime.manifest.options.btw.thinkingLevel, "low");
    assert.throws(() => pluginSettings("pi-smart-compact", "smart_compact"), /CAPABILITY_NOT_SELECTED/);
    assert.throws(() => managedSettingWrite(), /agentcfg/);
  } finally { globalThis[key] = old; }
});

test("smart compaction failure or refusal cancels instead of handing the call to a second compactor", async () => {
  const { ownedCompactionHook } = await import("../plugin-model.ts");
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key];
  globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["pi-smart-compact"], options: {} }, managedRequestScope: { getStore: () => null } };
  try {
    assert.deepEqual(await ownedCompactionHook(async () => undefined)({}, {}), { cancel: true });
    assert.deepEqual(await ownedCompactionHook(async () => { throw Error("private provider error"); })({}, {}), { cancel: true });
    const output = { compaction: { summary: "fixture", firstKeptEntryId: "entry", tokensBefore: 100 } };
    assert.deepEqual(await ownedCompactionHook(async () => output)({}, {}), output);
  } finally { globalThis[key] = old; }
});

test("a supervised MCP service can exchange messages in its own slot but cannot hide other managed activity", async () => {
  const { requireOrdinaryHelper } = await import("../capability-policy.ts");
  const key = Symbol.for("agentcfg.pi.managed.v1"), previous = globalThis[key];
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: { task_keeper: { enabled: true } } } };
  const records = [{ id: "mcp-owned", status: "running" }];
  globalThis[key] = { manager: { hasRunning: () => true, listAgents: () => records } };
  try {
    requireOrdinaryHelper(runtime, "pi-mcp", "mcp-owned");
    records.push({ id: "managed-worker", status: "queued" });
    assert.throws(() => requireOrdinaryHelper(runtime, "pi-mcp", "mcp-owned"), /UNMETERED_PARENT_HELPER/);
    assert.throws(() => requireOrdinaryHelper(runtime, "pi-btw", "mcp-owned"), /HELPER_SERVICE_ID_INVALID/);
  } finally { globalThis[key] = previous; }
});

test("an explicitly configured helper model never falls back to the parent when missing", async () => {
  const { selectedPluginModel } = await import("../plugin-model.ts");
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key], model = { provider: "fixture", id: "exact/model" };
  globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["pi-btw"], options: {} },
    models: { current: { getModel(provider, id) { return provider === model.provider && id === model.id ? model : undefined; } } } };
  try {
    assert.equal(selectedPluginModel("pi-btw", "fixture/exact/model", undefined), model);
    assert.equal(selectedPluginModel("pi-btw", undefined, model), model);
    assert.throws(() => selectedPluginModel("pi-btw", "fixture/missing", model), /NOT_SELECTED/);
    assert.throws(() => selectedPluginModel("pi-btw", "fuzzy", model), /REFERENCE/);
  } finally { globalThis[key] = previous; }
});
