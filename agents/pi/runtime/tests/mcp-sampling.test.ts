import assert from "node:assert/strict";
import { test } from "node:test";
import { handleSamplingRequest } from "../../packages/mcp-vendor/sampling-handler.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const calls = [], model = { provider: "agentcfg-fictional", id: "exact-model" };
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: { mcp: { sampling: {
    enabled: true, model: "agentcfg-fictional/exact-model", max_tokens: 50, auto_approve: false,
  } } } }, models: { current: { getModel(provider, id) { return provider === model.provider && id === model.id ? model : undefined; },
    async complete(chosen, context, options) { calls.push({ chosen, context, options }); return { ...model, model: model.id,
      stopReason: "stop", content: [{ type: "text", text: "fixture answer" }] }; } } } };
  const approvals = [], options = { serverName: "fixture", autoApprove: false,
    ui: { async confirm(title) { approvals.push(title); return true; } },
    modelRegistry: { getAvailable() { assert.fail("no model discovery"); }, getApiKeyAndHeaders() { assert.fail("no raw credentials"); } },
    getCurrentModel: () => model, getSignal: () => undefined };
  const request = { params: { maxTokens: 30, modelPreferences: { hints: [{ name: "unselected model" }] },
    messages: [{ role: "user", content: { type: "text", text: "fixture prompt" } }] } };
  return { runtime, calls, options, request, approvals };
}

test("MCP sampling uses only the selected ModelRuntime and keeps both approval stages", async () => {
  const f = fixture(); globalThis[slot] = f.runtime;
  try {
    const result = await handleSamplingRequest(f.options, f.request);
    assert.equal(result.model, "agentcfg-fictional/exact-model");
    assert.equal(result.content.text, "fixture answer"); assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].options.maxRetries, 0); assert.equal(f.calls[0].options.apiKey, undefined);
    assert.equal(f.approvals.length, 2);
  } finally { delete globalThis[slot]; }
});

test("sampling refuses unselected models, limits and managed contexts without provider fallback", async () => {
  for (const kind of ["disabled", "model", "limit", "managed"]) {
    const f = fixture(); globalThis[slot] = f.runtime;
    if (kind === "disabled") f.runtime.manifest.options.mcp.sampling.enabled = false;
    if (kind === "model") f.runtime.manifest.options.mcp.sampling.model = "different/unselected";
    if (kind === "limit") f.request.params.maxTokens = 51;
    if (kind === "managed") f.runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    try {
      await assert.rejects(handleSamplingRequest(f.options, f.request), /NOT_SELECTED|TOKEN_LIMIT|UNMETERED_PARENT_HELPER/);
      assert.equal(f.calls.length, 0);
    } finally { delete globalThis[slot]; }
  }
});
