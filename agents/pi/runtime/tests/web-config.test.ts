import assert from "node:assert/strict";
import { test } from "node:test";
import { webConfig, webConfigDirectory, webCredentialDeclared, webCredential, webCredentialDocument } from "../web-config.ts";
import { hasCredentialSource, resolveCredential } from "../../packages/web-vendor/credential-source.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1"), name = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
function fixture() {
  return { owner: { role: "manager" }, instanceRoot: "/fixture/instance", manifest: { plugins: ["pi-web"], options: {},
    web_services: { brave: { type: "api" } }, web_config: { provider: "brave", braveApiKey: "${" + name + "}" }, web_credential_variables: [name] } };
}
test("web config uses an explicit instance projection and availability does not read secret values", () => {
  globalThis[slot] = fixture();
  try {
    assert.equal(webConfigDirectory(), "/fixture/instance/pi-home/web");
    const config = webConfig(); config.provider = "changed";
    assert.equal(webConfig().provider, "brave");
    assert.equal(webCredentialDeclared("${" + name + "}"), true);
    assert.equal(hasCredentialSource({ provider: "Brave", environmentValue: "unselected global key" }), false);
    assert.throws(() => webCredentialDeclared("$OPENAI_API_KEY"), /UNDECLARED/);
    delete globalThis[slot].manifest.web_config;
    assert.throws(webConfig, /UNBOUND/);
  } finally { delete globalThis[slot]; }
});

test("web credentials are literal, never run commands and never expand ambient aliases", async () => {
  globalThis[slot] = fixture(); const previous = process.env[name];
  let commands = 0;
  try {
    for (const value of ["!not a command", "$UNSELECTED_ENVIRONMENT", "plain synthetic value"]) {
      process.env[name] = value;
      assert.equal(await resolveCredential({ provider: "Brave", configuredValue: "${" + name + "}",
        environmentValue: "must not override", runCommand: async () => { commands++; return { stdout: "wrong" }; } }), value);
    }
    for (const configuredValue of ["!echo forbidden", "$HOME", "literal source key"]) {
      await assert.rejects(resolveCredential({ provider: "Brave", configuredValue }), /invalid-source/);
    }
    delete process.env[name];
    await assert.rejects(resolveCredential({ provider: "Brave", configuredValue: "$" + name }), /environment-empty/);
    assert.equal(commands, 0);
  } finally {
    delete globalThis[slot]; if (previous === undefined) delete process.env[name]; else process.env[name] = previous;
  }
});

test("managed calls and canceled requests cannot obtain web credentials", async () => {
  const runtime = fixture(); globalThis[slot] = runtime;
  try {
    runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    await assert.rejects(resolveCredential({ provider: "Brave", configuredValue: "$" + name }), /invalid-source/);
    delete runtime.managedRequestScope;
    const abort = new AbortController(); abort.abort();
    await assert.rejects(resolveCredential({ provider: "Brave", configuredValue: "$" + name, signal: abort.signal }), /aborted/);
  } finally { delete globalThis[slot]; }
});

test("actual provider config getters use the manifest even when global environment overrides are present", async () => {
  const runtime = fixture(); globalThis[slot] = runtime;
  const previous = process.env.BRAVE_API_KEY;
  try {
    process.env.BRAVE_API_KEY = "synthetic unselected global key";
    const { isBraveAvailable } = await import("../../packages/web-vendor/brave.ts");
    const { resolveApiBaseUrl } = await import("../../packages/web-vendor/utils.ts");
    assert.equal(isBraveAvailable(), true);
    delete runtime.manifest.web_services.brave;
    assert.equal(isBraveAvailable(), false);
    runtime.manifest.web_services.brave = { type: "api" };
    delete runtime.manifest.web_config.braveApiKey;
    assert.equal(isBraveAvailable(), false);
    assert.equal(resolveApiBaseUrl({ configKey: "braveBaseUrl", configuredValue: "https://configured.example.invalid/api",
      defaultValue: "https://default.example.invalid", environmentKey: "BRAVE_BASE_URL", environmentValue: "https://unselected.example.invalid" }),
      "https://configured.example.invalid/api");
  } finally {
    delete globalThis[slot]; if (previous === undefined) delete process.env.BRAVE_API_KEY; else process.env.BRAVE_API_KEY = previous;
  }
});

test("Gemini ADC requires explicit service and secret reference, never ambient gcloud paths", async () => {
  const runtime = fixture(); globalThis[slot] = runtime;
  const saved = process.env.GOOGLE_APPLICATION_CREDENTIALS;
  try {
    process.env.GOOGLE_APPLICATION_CREDENTIALS = "/fixture/unselected-secret.json";
    const { isGeminiAdcAvailable, getAdcProject, getAdcAccessToken } = await import("../../packages/web-vendor/gemini-adc.ts");
    runtime.manifest.web_config = { geminiAuth: "adc", geminiProject: "fixture-project", geminiLocation: "global", geminiAdcCredentials: "$" + name };
    assert.equal(isGeminiAdcAvailable(), false);
    runtime.manifest.web_services["gemini-auth"] = { type: "api" };
    assert.equal(isGeminiAdcAvailable(), true); assert.equal(getAdcProject(), "fixture-project");
    process.env[name] = "{synthetic invalid JSON with credential content";
    await assert.rejects(getAdcAccessToken(), error => error.message === "Gemini ADC credential document is invalid");
  } finally {
    delete globalThis[slot]; delete process.env[name];
    if (saved === undefined) delete process.env.GOOGLE_APPLICATION_CREDENTIALS; else process.env.GOOGLE_APPLICATION_CREDENTIALS = saved;
  }
});

test("ADC token cache follows runtime ownership and credential rotation", async () => {
  const first = fixture(); first.manifest.web_services["gemini-auth"] = { type: "api" };
  first.manifest.web_config = { geminiAdcCredentials: "$" + name };
  let calls = 0;
  first.web = { async fetch() { calls++; return Response.json({ access_token: "synthetic-access-" + calls, expires_in: 3600 }); } };
  globalThis[slot] = first;
  const credential = refresh_token => JSON.stringify({ type: "authorized_user", client_id: "fixture-client", client_secret: "fixture-secret", refresh_token }, null, 2);
  try {
    const { getAdcAccessToken, clearAdcTokenCache } = await import("../../packages/web-vendor/gemini-adc.ts");
    clearAdcTokenCache(); process.env[name] = credential("fixture-first");
    assert.equal(await getAdcAccessToken(), "synthetic-access-1");
    assert.equal(await getAdcAccessToken(), "synthetic-access-1"); assert.equal(calls, 1);
    process.env[name] = credential("fixture-second");
    assert.equal(await getAdcAccessToken(), "synthetic-access-2");
    globalThis[slot] = { ...first };
    assert.equal(await getAdcAccessToken(), "synthetic-access-3"); assert.equal(calls, 3);
  } finally { delete globalThis[slot]; delete process.env[name]; }
});


test("structured credential documents allow JSON whitespace while HTTP header credentials remain strict", () => {
  const runtime = fixture(); globalThis[slot] = runtime;
  try {
    process.env[name] = '{\n  "fixture": "document"\n}';
    assert.equal(webCredentialDocument("$" + name), process.env[name]);
    assert.throws(() => webCredential("$" + name), /CREDENTIAL_INVALID/);
    process.env[name] = "invalid\x01document";
    assert.throws(() => webCredentialDocument("$" + name), /CREDENTIAL_INVALID/);
  } finally { delete globalThis[slot]; delete process.env[name]; }
});
