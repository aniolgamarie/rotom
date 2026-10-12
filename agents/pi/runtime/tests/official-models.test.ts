import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, chmodSync, symlinkSync, linkSync, unlinkSync, rmdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialModelConfiguration, createOfficialModels } from "../official-models.ts";
import { digest } from "../managed-types.ts";

const CANARY = "synthetic-private-model-secret";
const zeroCost = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
function fixture({ oauth = false, credentialRef = "secret:fixture", file = !oauth } = {}) {
  const root = mkdtempSync(join(tmpdir(), "official-models-")), home = join(root, "pi-home"), path = join(home, "models.json");
  mkdirSync(home, { mode: 0o700 });
  const route = oauth ? "openai-codex" : "agentcfg-fictional", logical = oauth ? "codex" : "fictional", owner = oauth ? "pi-native" : "pi-environment";
  const binding = { logical_id: logical, auth_kind: oauth ? "oauth" : "api-key", owner };
  const config = { api: "openai-completions", baseUrl: "https://fixture.invalid/v1", models: [{ id: "fixture-chat", input: ["text"] }] };
  const manifest = { provider_bindings: { [route]: structuredClone(binding) }, allowed_models: [{ provider: route, model: "fixture-chat" }],
    model_configuration: { schema_version: 1, providers: { [route]: { ...binding, credential_ref: oauth ? null : credentialRef, config: oauth ? null : structuredClone(config) } } } };
  const variable = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update(logical).digest("hex").slice(0, 16).toUpperCase();
  const raw = { providers: oauth ? {} : { [route]: { ...structuredClone(config), apiKey: "$" + variable } } };
  const state = { error: undefined, throws: false, model: { id: "fixture-chat", provider: route, api: config.api, baseUrl: config.baseUrl,
    name: "fixture-chat", reasoning: false, input: ["text"], cost: { ...zeroCost }, contextWindow: 128000, maxTokens: 16384 } };
  const modelRuntime = Object.freeze({
    getError() { if (state.throws) throw Error(CANARY); return state.error; },
    getModel(provider, id) { assert.equal(provider, route); assert.equal(id, "fixture-chat"); return structuredClone(state.model); },
    get credentials() { throw Error("credentials touched"); },
  });
  const save = value => writeFileSync(path, value instanceof Uint8Array || typeof value === "string" ? value : JSON.stringify(value), { mode: 0o600 });
  if (file) save(raw);
  return { root, home, path, route, variable, manifest, raw, state, modelRuntime, save,
    create: extra => createOfficialModels({ manifest, path, modelRuntime, ...extra }),
    model: () => modelRuntime.getModel(route, "fixture-chat") };
}
const safeFailure = (fn, code) => assert.throws(fn, error => typeof error.message === "string"
  && error.message.startsWith("pi-model-") && !error.message.includes(CANARY) && (code === undefined || error.exitCode === code));

test("configuration precheck works without an SDK runtime and returns only the closed nonsecret API", () => {
  const f = fixture(), guard = createOfficialModelConfiguration({ manifest: f.manifest, path: f.path });
  assert.deepEqual(Object.keys(guard).sort(), ["checkFile", "declarationDigest", "describe"]);
  assert.equal(Object.isFrozen(guard), true);
  assert.equal(guard.checkFile(), undefined);
  assert.deepEqual(guard.describe(f.model()), f.model());
  const poison = { manifest: f.manifest, path: f.path, get modelRuntime() { assert.fail("SDK runtime touched during configuration precheck"); } };
  assert.equal(createOfficialModelConfiguration(poison).declarationDigest, guard.declarationDigest);
});

test("configuration precheck rejects file pollution before a runtime can be constructed", () => {
  const f = fixture(); f.raw.providers[f.route].apiKey = CANARY; f.save(f.raw);
  safeFailure(() => createOfficialModelConfiguration({ manifest: f.manifest, path: f.path }), 4);
});

test("configuration guard rechecks files and composes with the unchanged runtime API", () => {
  const f = fixture(), guard = createOfficialModelConfiguration({ manifest: f.manifest, path: f.path }), runtime = f.create();
  assert.deepEqual(Object.keys(runtime).sort(), ["checkRuntime", "declarationDigest", "describe"]);
  assert.equal(runtime.declarationDigest, guard.declarationDigest);
  f.raw.providers.foreign = { apiKey: CANARY }; f.save(f.raw);
  safeFailure(() => guard.checkFile(), 4); safeFailure(() => runtime.checkRuntime(), 4);
});

test("API-key deployment references produce the actual SDK default model description", () => {
  const f = fixture(), models = f.create();
  assert.equal(models.checkRuntime(), undefined);
  assert.deepEqual(models.describe(f.model()), { id: "fixture-chat", provider: "agentcfg-fictional", api: "openai-completions", baseUrl: "https://fixture.invalid/v1",
    name: "fixture-chat", reasoning: false, input: ["text"], cost: { ...zeroCost }, contextWindow: 128000, maxTokens: 16384 });
  assert.equal(typeof models.declarationDigest, "string"); assert.match(models.declarationDigest, /^[a-f0-9]{64}$/);
});

test("credential reference changes declaration identity while environment secret contents do not", () => {
  const first = fixture(), second = fixture({ credentialRef: "secret:other" }), old = process.env[first.variable];
  try {
    const baseline = first.create().declarationDigest;
    process.env[first.variable] = CANARY;
    assert.equal(first.create().declarationDigest, baseline);
    assert.notEqual(second.create().declarationDigest, baseline);
    assert.ok(!JSON.stringify(first.create().describe(first.model())).includes(CANARY));
    assert.notEqual(baseline, createHash("sha256").update(CANARY).digest("hex"));
  } finally { if (old === undefined) delete process.env[first.variable]; else process.env[first.variable] = old; }
});
for (const credentialRef of ["secret:fixture", "secret:中文 key"]) test("schema-compatible secret reference remains a reference: " + credentialRef, () => {
  const f = fixture({ credentialRef }); assert.doesNotThrow(() => f.create());
});

test("headers and SDK type stay out of public descriptions and their identity", () => {
  const f = fixture(), models = f.create(); f.state.model.headers = { Authorization: CANARY }; f.state.model.type = "chat";
  const observed = models.describe(f.model()), identity = digest(observed);
  assert.ok(!Object.hasOwn(observed, "headers")); assert.ok(!Object.hasOwn(observed, "type")); assert.ok(!JSON.stringify(observed).includes(CANARY));
  f.state.model.headers.Authorization = "another-private-header";
  assert.deepEqual(models.describe(f.model()), observed); assert.equal(digest(models.describe(f.model())), identity);
});

for (const change of [{ api: "openai-responses" }, { baseUrl: "https://other.invalid/v1" }, { thinkingLevelMap: { high: "max" } },
  { compat: { thinkingFormat: "deepseek" } }, { contextWindow: 64000 }, { maxTokens: 8192 }, { reasoning: true }, { input: ["text", "image"] }])
  test("effective API-key model drift refuses a valid-looking alternate model: " + Object.keys(change)[0], () => {
    const f = fixture(), models = f.create(); Object.assign(f.state.model, change); safeFailure(() => models.describe(f.model()), 4);
  });

test("explicit thinking and compat descriptions accept the deployed model and preserve independent copies", () => {
  const f = fixture(), definition = f.manifest.model_configuration.providers[f.route].config.models[0];
  Object.assign(definition, { name: "Chosen", reasoning: true, contextWindow: 200000, maxTokens: 20000,
    thinkingLevelMap: { high: "max", off: null }, compat: { thinkingFormat: "deepseek" } });
  f.raw.providers[f.route].models = [structuredClone(definition)]; f.save(f.raw);
  Object.assign(f.state.model, definition); const models = f.create(), observed = models.describe(f.model());
  assert.deepEqual(observed.thinkingLevelMap, { high: "max", off: null });
  observed.thinkingLevelMap.high = "mutated";
  assert.equal(models.describe(f.model()).thinkingLevelMap.high, "max");
});

for (const fault of ["plaintext-key", "header", "config", "overrides", "foreign-provider", "api", "endpoint", "thinking", "compat"])
  test("models.json pollution or drift cannot be accepted: " + fault, () => {
    const f = fixture(), models = f.create(), provider = f.raw.providers[f.route];
    if (fault === "plaintext-key") provider.apiKey = CANARY;
    if (fault === "header") provider.headers = { Authorization: CANARY };
    if (fault === "config") provider.unknownConfig = CANARY;
    if (fault === "overrides") provider.modelOverrides = { "fixture-chat": { token: CANARY } };
    if (fault === "foreign-provider") f.raw.providers.foreign = { apiKey: CANARY };
    if (fault === "api") provider.api = "openai-responses";
    if (fault === "endpoint") provider.baseUrl = "https://other.invalid";
    if (fault === "thinking") provider.models[0].thinkingLevelMap = { high: "max" };
    if (fault === "compat") provider.models[0].compat = { thinkingFormat: "deepseek" };
    f.save(f.raw); safeFailure(() => models.checkRuntime(), 4);
  });

for (const fault of ["duplicate-key", "utf8", "oversize", "file-mode", "directory-mode", "symlink", "hardlink"])
  test("private file structure rejects " + fault + " without exposing bytes", () => {
    const f = fixture();
    if (fault === "duplicate-key") f.save('{"providers":{"agentcfg-fictional":{"apiKey":"' + CANARY + '"}},"prov\\u0069ders":' + JSON.stringify(f.raw.providers) + '}');
    if (fault === "utf8") f.save(Buffer.from([0xff, 0xfe]));
    if (fault === "oversize") f.save(JSON.stringify(f.raw) + " ".repeat(1024 * 1024));
    if (fault === "file-mode") chmodSync(f.path, 0o644);
    if (fault === "directory-mode") chmodSync(f.home, 0o755);
    if (fault === "symlink" || fault === "hardlink") {
      const source = join(f.home, "source.json"); writeFileSync(source, JSON.stringify(f.raw), { mode: 0o600 }); unlinkSync(f.path);
      if (fault === "symlink") symlinkSync(source, f.path); else linkSync(source, f.path);
    }
    safeFailure(() => f.create(), 4);
  });

test("OAuth records can use no models.json and still describe a safe public Model", () => {
  const f = fixture({ oauth: true }), models = f.create();
  assert.equal(models.checkRuntime(), undefined); assert.deepEqual(models.describe(f.model()), f.model());
  assert.equal(f.manifest.model_configuration.providers[f.route].config, null);
});
test("missing OAuth file does not authorize a missing private home directory", () => {
  const f = fixture({ oauth: true }); rmdirSync(f.home);
  safeFailure(() => f.create(), 4);
});
for (const opaque of ["samplingParams", "samplingParamsByThinkingLevel", "chatTemplate", "unknownField"]) test("OAuth opaque model field is refused: " + opaque, () => {
  const f = fixture({ oauth: true }), models = f.create(); f.state.model[opaque] = { secret: CANARY };
  safeFailure(() => models.describe(f.model()), 2);
});

for (const fault of ["empty-string", "error-string", "throws", "missing-getError", "missing-getModel"])
  test("SDK runtime composition errors cannot silently fall back: " + fault, () => {
    const f = fixture();
    if (fault === "empty-string") f.state.error = "";
    if (fault === "error-string") f.state.error = CANARY;
    if (fault === "throws") f.state.throws = true;
    const modelRuntime = fault === "missing-getError" ? { getModel() {} } : fault === "missing-getModel" ? { getError() {} } : f.modelRuntime;
    safeFailure(() => f.create({ modelRuntime }), 5);
  });

test("Python-generated shared protocol fixture matches native fields and SDK description", () => {
  const protocol = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/pi/model-configuration.json", import.meta.url), "utf8"));
  const f = fixture(); f.save(protocol.native);
  const modelRuntime = Object.freeze({ getError() { return undefined; }, getModel() { return structuredClone(protocol.effective_model); } });
  const checker = f.create({ manifest: protocol.manifest, modelRuntime });
  assert.equal(checker.checkRuntime(), undefined);
  assert.deepEqual(checker.describe(modelRuntime.getModel()), protocol.effective_model);
});

for (const fault of ["declaration", "provider", "binding", "binding-owner", "model-id", "duplicate-model", "foreign-selected", "schema"])
  test("closed declaration and exact binding identity reject " + fault, () => {
    const f = fixture(), declaration = f.manifest.model_configuration, provider = declaration.providers[f.route];
    if (fault === "declaration") declaration.token = CANARY;
    if (fault === "provider") provider.headers = { token: CANARY };
    if (fault === "binding") f.manifest.provider_bindings[f.route].token = CANARY;
    if (fault === "binding-owner") f.manifest.provider_bindings[f.route].owner = "foreign";
    if (fault === "model-id") f.manifest.allowed_models[0].model = "other";
    if (fault === "duplicate-model") f.manifest.allowed_models.push({ ...f.manifest.allowed_models[0] });
    if (fault === "foreign-selected") f.manifest.allowed_models.push({ provider: "foreign", model: "other" });
    if (fault === "schema") declaration.schema_version = true;
    safeFailure(() => f.create(), 2);
  });
