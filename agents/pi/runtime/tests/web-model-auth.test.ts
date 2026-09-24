import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { webSearchModel, webSearchAuthAvailable, webSearchAuth } from "../web-model-auth.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const model = { provider: "fixture-provider", id: "fixture-model" }, controller = new AbortController(), calls = [];
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {},
    provider_bindings: { "fixture-provider": { auth_kind: "oauth", owner: "pi-native", logical_id: "fixture" } },
    web_model_bindings: { openai: { provider: model.provider, model: model.id } } },
    models: { current: { getModel(provider, id) { return provider === model.provider && id === model.id ? model : undefined; },
      hasConfiguredAuth: provider => provider === model.provider,
      async getAuth(selected, options) { calls.push({ selected, options }); return { auth: { apiKey: "synthetic-token", headers: {} } }; } } },
    web: { current: () => ({ controller }), track: promise => promise } };
  globalThis[slot] = runtime; return { runtime, model, controller, calls };
}
test("search auth availability uses exact declared model metadata without reading credentials", async () => {
  const f = fixture();
  try {
    assert.equal(webSearchModel("openai"), f.model); assert.equal(webSearchAuthAvailable("openai"), true);
    assert.equal(webSearchAuthAvailable("kimi"), false); assert.equal(f.calls.length, 0);
    assert.equal(await webSearchAuth("kimi"), undefined);
    assert.equal((await webSearchAuth("openai")).apiKey, "synthetic-token");
    assert.equal(f.calls[0].selected, f.model); assert.deepEqual(f.calls[0].options.env, {});
    f.runtime.manifest.web_model_bindings.openai.model = "undeclared";
    await assert.rejects(webSearchAuth("openai"), /NOT_SELECTED/); assert.equal(f.calls.length, 1);
  } finally { delete globalThis[slot]; }
});
test("API auth receives only the selected generated credential variable", async () => {
  const f = fixture(), name = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update("fixture").digest("hex").slice(0, 16).toUpperCase();
  f.runtime.manifest.provider_bindings["fixture-provider"].auth_kind = "api-key";
  const before = process.env[name], ambient = process.env.OPENAI_API_KEY;
  try {
    process.env[name] = "synthetic-declared"; process.env.OPENAI_API_KEY = "synthetic-ambient";
    await webSearchAuth("openai"); assert.deepEqual(f.calls[0].options.env, { [name]: "synthetic-declared" });
  } finally {
    delete globalThis[slot];
    if (before === undefined) delete process.env[name]; else process.env[name] = before;
    if (ambient === undefined) delete process.env.OPENAI_API_KEY; else process.env.OPENAI_API_KEY = ambient;
  }
});
test("auth failure is sanitized and declared-account failure cannot fall back to another model", async () => {
  const f = fixture();
  try {
    f.runtime.models.current.getAuth = async () => { throw new Error("synthetic-secret must stay private"); };
    await assert.rejects(webSearchAuth("openai"), error => error.message === "WEB_MODEL_AUTH_FAILED");
    f.controller.abort(); await assert.rejects(webSearchAuth("openai"), /abort/i);
  } finally { delete globalThis[slot]; }
});
