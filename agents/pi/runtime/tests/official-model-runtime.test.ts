import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, chmodSync, symlinkSync, linkSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialRuntimeInitializer } from "../official-model-runtime.ts";

const canary = "synthetic-private-auth-marker";
const oauthRecord = () => ({ type: "oauth", access: canary, refresh: "synthetic-refresh-marker", expires: 100, accountId: "synthetic-account" });
function fixture({ oauth = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), "official-model-runtime-")), instanceRoot = join(root, "instance"), directory = join(instanceRoot, "pi-home");
  mkdirSync(directory, { recursive: true, mode: 0o700 }); chmodSync(directory, 0o700);
  const protocol = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/pi/model-configuration.json", import.meta.url), "utf8"));
  const manifest = { profile_id: "pi-base", ...protocol.manifest };
  const path = join(directory, "models.json"), authPath = join(directory, "auth.json");
  writeFileSync(path, JSON.stringify(protocol.native), { mode: 0o600 });
  const state = { creates: 0, reads: 0, models: [protocol.effective_model], metadata: [], error: undefined };
  if (oauth) {
    manifest.provider_bindings["openai-codex"] = { logical_id: "codex", auth_kind: "oauth", owner: "pi-native" };
    manifest.model_configuration.providers["openai-codex"] = { ...manifest.provider_bindings["openai-codex"], credential_ref: null, config: null };
    manifest.allowed_models.push({ provider: "openai-codex", model: "synthetic-oauth" });
    state.models.push({ ...structuredClone(protocol.effective_model), provider: "openai-codex", id: "synthetic-oauth" });
  }
  class InMemoryModelsStore { async read() { throw Error("unexpected model cache read"); } }
  class InMemoryCredentialStore { async read() { throw Error("unexpected credential read"); } async list() { return []; } }
  class Runtime {
    getError() { return state.error; }
    getModel(provider, id) {
    if (state.modelError) throw Error(canary);
    return state.models.find(model => model.provider === provider && model.id === id);
    }
    async listCredentials() { state.reads++; if (state.metadataError) throw Error(canary); await state.onMetadata?.(); return structuredClone(state.metadata); }
    getProvider() { throw Error("unexpected provider discovery"); }
    checkAuth() { throw Error("unexpected auth check"); }
    getAvailable() { throw Error("unexpected auth discovery"); }
    getAuth() { throw Error("unexpected auth resolution"); }
    refresh() { throw Error("unexpected refresh"); }
    registerProvider() { throw Error("unexpected registration"); }
  }
  Object.freeze(Runtime.prototype);
  const runtime = new Runtime();
  const sdk = Object.freeze({ ModelRuntime: Object.freeze({ async create(options) {
    state.creates++; state.options = options; state.sourcePath = options.modelsPath;
    await state.onCreate?.(options);
    state.loadedConfig = JSON.parse(readFileSync(options.modelsPath, "utf8"));
    if (options.authPath) {
      if (!existsSync(options.authPath)) writeFileSync(options.authPath, "{}", { mode: 0o600 });
      const data = JSON.parse(readFileSync(options.authPath, "utf8"));
      state.metadata = Object.entries(data).map(([providerId, value]) => ({ providerId, type: value.type }));
    }
    await state.afterRead?.();
    if (state.createError) throw Error(canary);
    return state.runtime ?? runtime;
  } }) });
  const ai = Object.freeze({ InMemoryModelsStore, InMemoryCredentialStore });
  const saveAuth = value => writeFileSync(authPath, typeof value === "string" ? value : JSON.stringify(value), { mode: 0o600 });
  return { root, instanceRoot, directory, path, authPath, manifest, protocol, state, sdk, ai, runtime, saveAuth,
    initializer: extra => createOfficialRuntimeInitializer({ sdk, ai, manifest, instanceRoot, ...extra }) };
}
const safe = error => /^pi-/.test(error.message) && !error.message.includes(canary);

test("API-key initialization uses explicit private configuration, memory stores and no refresh", async () => {
  const f = fixture(); f.saveAuth("malformed " + canary);
  const initialize = f.initializer(); assert.equal(f.state.creates, 0);
  const result = await initialize(), options = f.state.options;
  assert.notEqual(result.modelRuntime, f.runtime); assert.equal(Object.getPrototypeOf(result.modelRuntime), Object.getPrototypeOf(f.runtime));
  assert.equal(result.modelRuntime instanceof f.runtime.constructor, true); assert.equal(Object.isFrozen(result), true);
  assert.match(result.configurationDigest, /^[0-9a-f]{64}$/);
  assert.match(options.modelsPath, /^\/proc\/self\/fd\/\d+$/); assert.notEqual(options.modelsPath, f.path);
  assert.deepEqual(f.state.loadedConfig, f.protocol.native);
  assert.equal(options.allowModelNetwork, false); assert.equal(options.refreshOnCreate, false);
  assert.ok(options.modelsStore instanceof f.ai.InMemoryModelsStore); assert.ok(options.credentials instanceof f.ai.InMemoryCredentialStore);
  assert.deepEqual(Object.keys(options).sort(), ["allowModelNetwork", "credentials", "modelsPath", "modelsStore", "refreshOnCreate"].sort());
  assert.equal(readFileSync(f.authPath, "utf8"), "malformed " + canary);
  assert.equal(Object.hasOwn(result, "close"), false); await result.check();
  assert.deepEqual(readdirSync(f.directory).sort(), ["auth.json", "models.json"]);
});
test("concurrent calls and retries share exactly one native initialization", async () => {
  const f = fixture(), initialize = f.initializer();
  const a = initialize(), b = initialize(); assert.equal(a, b);
  const first = await a; assert.equal(await initialize(), first); assert.equal(f.state.creates, 1);
});
test("a failed native initialization is sticky and closes its undisclosed source", async () => {
  const f = fixture(); f.state.createError = true; const initialize = f.initializer(), first = initialize();
  await assert.rejects(first, error => safe(error) && error.message === "pi-runtime-create-failed");
  assert.equal(initialize(), first); await assert.rejects(initialize(), safe);
  assert.equal(f.state.creates, 1); assert.equal(existsSync(f.state.sourcePath), false);
  assert.deepEqual(readdirSync(f.directory), ["models.json"]);
});
test("replacing the original models filename during native create cannot change what SDK reads", async () => {
  const f = fixture(), original = readFileSync(f.path);
  f.state.onCreate = () => { const altered = structuredClone(f.protocol.native); altered.providers["agentcfg-fictional"].apiKey = "!" + canary; writeFileSync(f.path, JSON.stringify(altered)); };
  f.state.afterRead = () => writeFileSync(f.path, original);
  const result = await f.initializer()();
  assert.deepEqual(f.state.loadedConfig, f.protocol.native); await result.check();
});
test("configuration drift left behind during native create refuses the initialized runtime", async () => {
  const f = fixture(); f.state.onCreate = () => writeFileSync(f.path, "{}");
  await assert.rejects(f.initializer()(), safe);
  assert.equal(existsSync(f.state.sourcePath), false);
});
test("runtime initialization keeps its own deployment declaration", async () => {
  const f = fixture(), initialize = f.initializer();
  f.manifest.model_configuration.providers["agentcfg-fictional"].config.baseUrl = "https://wrong.invalid";
  const result = await initialize(); await result.check(); assert.deepEqual(f.state.loadedConfig, f.protocol.native);
});
test("drift after constructing the initializer is caught before SDK consumption", async () => {
  const f = fixture(), initialize = f.initializer(); writeFileSync(f.path, "{}");
  await assert.rejects(initialize(), safe); assert.equal(f.state.creates, 0);
});
test("OAuth initialization passes only the instance auth path and preserves credential bytes", async () => {
  const f = fixture({ oauth: true }); f.saveAuth({ "openai-codex": oauthRecord(), retired: { type: "api_key", key: canary } });
  const original = readFileSync(f.authPath), result = await f.initializer()();
  assert.equal(f.state.options.authPath, f.authPath); assert.equal(Object.hasOwn(f.state.options, "credentials"), false);
  assert.deepEqual(readFileSync(f.authPath), original); await result.check();
  assert.equal(JSON.stringify({ configurationDigest: result.configurationDigest }).includes(canary), false);
});
test("OAuth's missing auth file is left for the native factory under its original ownership", async () => {
  const f = fixture({ oauth: true }), initialize = f.initializer(); assert.equal(existsSync(f.authPath), false);
  await initialize(); assert.equal(readFileSync(f.authPath, "utf8"), "{}");
});
for (const fault of ["api-key-shadow", "wrong-oauth-type", "non-native-owner", "malformed", "duplicate-key", "partial-oauth", "oversize", "mode", "symlink", "hardlink"])
  test("native credential preflight rejects " + fault + " before SDK consumes accounts", async () => {
    const f = fixture({ oauth: true }); f.saveAuth({ "openai-codex": oauthRecord() });
    if (fault === "api-key-shadow") f.saveAuth({ "agentcfg-fictional": { type: "api_key", key: canary } });
    if (fault === "wrong-oauth-type") f.saveAuth({ "openai-codex": { type: "api_key", key: canary } });
    if (fault === "non-native-owner") for (const record of [f.manifest.provider_bindings["openai-codex"], f.manifest.model_configuration.providers["openai-codex"]]) record.owner = "pi-cursor";
    if (fault === "malformed") f.saveAuth(canary);
    if (fault === "duplicate-key") f.saveAuth('{"openai-codex":null,"openai-codex":' + JSON.stringify(oauthRecord()) + '}');
    if (fault === "partial-oauth") f.saveAuth({ "openai-codex": { type: "oauth", access: canary } });
    if (fault === "oversize") f.saveAuth({ "openai-codex": { ...oauthRecord(), extra: canary.repeat(100000) } });
    if (fault === "mode") chmodSync(f.authPath, 0o644);
    if (["symlink", "hardlink"].includes(fault)) {
      const target = join(f.directory, "foreign-auth.json"); writeFileSync(target, JSON.stringify({ "openai-codex": oauthRecord() }), { mode: 0o600 });
      if (fault === "symlink") { const alternate = join(f.directory, "auth-link.json"); symlinkSync(target, alternate); f.saveAuth("{}");
        // 仅以临时文件替换测试目标，不碰账号或真实HOME。
        const { renameSync } = await import("node:fs"); renameSync(alternate, f.authPath);
      } else linkSync(f.authPath, join(f.directory, "auth-hardlink.json"));
    }
    await assert.rejects(async () => f.initializer()(), safe); assert.equal(f.state.creates, 0);
  });
for (const fault of ["error", "throws", "missing-model", "model-error", "metadata-error", "metadata-shadow", "metadata-extra", "metadata-secret-field"])
  test("post-create runtime proof rejects " + fault + " without returning a usable handle", async () => {
    const f = fixture();
    if (fault === "error") f.state.error = canary;
    if (fault === "throws") f.state.runtime = { ...f.runtime, getError() { throw Error(canary); } };
    if (fault === "missing-model") f.state.models.length = 0;
    if (fault === "model-error") f.state.modelError = true;
    if (fault === "metadata-error") f.state.metadataError = true;
    if (fault === "metadata-shadow") f.state.metadata = [{ providerId: "agentcfg-fictional", type: "api_key" }];
    if (fault === "metadata-extra") f.state.metadata = [{ providerId: "foreign", type: "api_key" }];
    if (fault === "metadata-secret-field") f.state.metadata = [{ providerId: "foreign", type: "api_key", key: canary }];
    await assert.rejects(f.initializer()(), safe); assert.equal(f.state.creates, 1); assert.equal(existsSync(f.state.sourcePath), false);
  });
test("native cached credential metadata must match the current validated account source", async () => {
  const f = fixture({ oauth: true }); f.saveAuth({ "openai-codex": oauthRecord() });
  f.state.afterRead = () => { f.state.metadata.push({ providerId: "agentcfg-fictional", type: "api_key" }); };
  await assert.rejects(f.initializer()(), error => safe(error) && error.message === "pi-runtime-auth-owner-conflict");
});
test("a later in-memory API-key override fails the next asynchronous source check", async () => {
  const f = fixture(), result = await f.initializer()();
  f.state.metadata.push({ providerId: "agentcfg-fictional", type: "api_key" });
  await assert.rejects(result.check(), error => safe(error) && error.message === "pi-runtime-auth-owner-conflict");
});
test("changes to the native account source during metadata inspection cannot pass", async () => {
  const f = fixture({ oauth: true }); f.saveAuth({ "openai-codex": oauthRecord() });
  const result = await f.initializer()();
  f.state.onMetadata = () => f.saveAuth({});
  await assert.rejects(result.check(), error => safe(error) && error.message === "pi-runtime-auth-state-stale");
});
test("OAuth token refresh does not become a credential-content identity", async () => {
  const f = fixture({ oauth: true }); f.saveAuth({ "openai-codex": oauthRecord() });
  const result = await f.initializer()(), before = result.configurationDigest;
  f.saveAuth({ "openai-codex": { ...oauthRecord(), access: "synthetic-rotated-access", refresh: "synthetic-rotated-refresh" } });
  await result.check(); assert.equal(result.configurationDigest, before);
});
