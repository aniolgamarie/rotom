import assert from "node:assert/strict";
import { test } from "node:test";
import { readseekWorker, readseekSettings, wrapReadseekTool, recordReadseekAnchor } from "../readseek-context.ts";

const runtimeSlot = Symbol.for("agentcfg.pi.runtime.v1"), workerSlot = Symbol.for("agentcfg.pi.readseek.worker.v1");
test("parent ReadSeek tools keep schema/renderers but never invoke raw filesystem execution", async () => {
  let bridged = 0, original = 0;
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-readseek"], options: { readseek: { settings: {} } } },
    readseek: { async execute(name, id, args) { bridged++; return { name, id, args }; } } };
  globalThis[runtimeSlot] = runtime;
  try {
    const tool = { name: "readSeek_write", parameters: { type: "object" }, renderCall() {}, async execute() { original++; } };
    const wrapped = wrapReadseekTool(tool);
    assert.deepEqual(wrapped.parameters, { ...tool.parameters, additionalProperties: false }); assert.equal(wrapped.renderCall, tool.renderCall);
    assert.deepEqual(await wrapped.execute("call", { path: "file" }), { name: "readSeek_write", id: "call", args: { path: "file" } });
    assert.equal(original, 0); assert.equal(bridged, 1);
    globalThis[runtimeSlot] = { ...runtime };
    await assert.rejects(wrapped.execute("call", {}), /RUNTIME_STALE/);
    globalThis[runtimeSlot] = runtime;
    runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    await assert.rejects(wrapped.execute("call", {}), /UNMETERED_PARENT_HELPER/);
    globalThis[workerSlot] = { settings: {} };
    assert.throws(readseekWorker, /CONTEXT_COLLISION/);
  } finally { delete globalThis[runtimeSlot]; delete globalThis[workerSlot]; }
});

test("isolated workers receive frozen settings and anchor events without global configuration", () => {
  const worker = { settings: { timeoutMs: 1000 }, native_binary: "/fixture/readseek", anchors: ["/snapshot/file"] };
  globalThis[workerSlot] = worker;
  try {
    assert.deepEqual(readseekSettings(), { timeoutMs: 1000 });
    recordReadseekAnchor("mark", "/snapshot/file"); recordReadseekAnchor("forget", "/snapshot/file");
    assert.equal(worker.anchor_events.length, 2);
    const tool = { name: "readSeek_read", parameters: { type: "object" } };
    assert.equal(wrapReadseekTool(tool).parameters.additionalProperties, false);
    worker.settings.overrideTools = ["write"];
    assert.throws(readseekSettings, /SETTINGS_INVALID/);
  } finally { delete globalThis[workerSlot]; }
});
