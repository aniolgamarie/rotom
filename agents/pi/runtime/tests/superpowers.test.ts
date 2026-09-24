import assert from "node:assert/strict";
import { test } from "node:test";
import superpowers from "../../packages/superpowers-vendor/.pi/extensions/superpowers.ts";

test("Superpowers bootstrap uses the explicit pack, keeps compaction summaries first and never registers discovery", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), previous = globalThis[key], hooks = new Map();
  globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["superpowers"] }, managedRequestScope: { getStore: () => null } };
  try {
    superpowers({ on(name, handler) { assert.equal(hooks.has(name), false); hooks.set(name, handler); } });
    assert.equal(hooks.has("resources_discover"), false);
    const summary = { role: "compactionSummary", content: "fixture summary" }, user = { role: "user", content: "fixture task" };
    const result = await hooks.get("context")({ messages: [summary, user] });
    assert.equal(result.messages[0], summary);
    assert.equal(result.messages[2], user);
    assert.match(result.messages[1].content[0].text, /using-superpowers bootstrap for pi/);
    assert.match(result.messages[1].content[0].text, /`Agent`/);
    assert.equal(await hooks.get("context")(result), undefined);
    await hooks.get("agent_end")();
    assert.equal(await hooks.get("context")({ messages: [user] }), undefined);
    await hooks.get("session_compact")();
    assert.equal((await hooks.get("context")({ messages: [user] })).messages.length, 2);
    globalThis[key].managedRequestScope.getStore = () => ({ task_id: "managed" });
    assert.equal(await hooks.get("context")({ messages: [user] }), undefined);
    globalThis[key].managedRequestScope.getStore = () => null;
    globalThis[key].manifest.plugins = [];
    assert.equal(await hooks.get("context")({ messages: [user] }), undefined);
  } finally { globalThis[key] = previous; }
});
