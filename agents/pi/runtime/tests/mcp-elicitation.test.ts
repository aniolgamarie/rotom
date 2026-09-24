import assert from "node:assert/strict";
import { test } from "node:test";
import { handleUrlElicitation } from "../../packages/mcp-vendor/elicitation-handler.ts";

test("MCP URL elicitation requires selected service and user action, without starting a browser", async () => {
  const slot = Symbol.for("agentcfg.pi.runtime.v1"), previous = process.stdout.write;
  const frames = [], notices = [], decisions = [], accepted = [];
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: {},
    mcp_config: { mcpServers: { fixture: { url: "https://service.invalid" } }, settings: { elicitation: true } } } };
  globalThis[slot] = runtime;
  let selection = "Show link";
  const options = { serverName: "fixture", allowUrl: true,
    ui: { async select(message, choices) { decisions.push({ message, choices }); return selection; }, notify(text) { notices.push(text); } },
    onUrlAccepted: id => accepted.push(id) };
  const params = { mode: "url", message: "fixture request", url: "https://service.invalid/consent", elicitationId: "fixture-action" };
  process.stdout.write = value => { frames.push(value); return true; };
  try {
    selection = "Decline";
    assert.deepEqual(await handleUrlElicitation(options, params), { action: "decline" });
    assert.equal(frames.length, 0);
    selection = "Show link";
    assert.deepEqual(await handleUrlElicitation(options, params), { action: "accept" });
    assert.ok(frames[0].startsWith("\x1b]8;;https://service.invalid/consent"));
    assert.deepEqual(accepted, ["fixture-action"]);
    for (const url of ["file:///private/credential", "https://user:secret@service.invalid/", "https://service.invalid/\x1b]evil"]) {
      await assert.rejects(handleUrlElicitation(options, { ...params, url }));
    }
    assert.equal(frames.length, 1);
    runtime.manifest.mcp_config.settings.elicitation = false;
    await assert.rejects(handleUrlElicitation(options, params), /MCP_ELICITATION_NOT_SELECTED/);
  } finally { process.stdout.write = previous; delete globalThis[slot]; }
  assert.equal(decisions.length, 2); assert.equal(notices.length, 1);
});
