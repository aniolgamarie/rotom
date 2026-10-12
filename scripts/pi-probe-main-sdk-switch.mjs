// 仅准备不会加载SDK；native入口须未来单独授权及冻结计划，本文不启动子进程。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { isDeepStrictEqual, types } from "node:util";
// 此helper只在native入口按固定fixture位置import；默认plan函数不读取candidate。

export const CASES = Object.freeze(["selected-alternate", "outside-after-switch", "public-native-oauth-login"]);
const ENV = Object.freeze({ HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1", OTEL_SDK_DISABLED: "true", TMPDIR: "/work/tmp", XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data", XDG_CACHE_HOME: "/work/cache", XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8" });
const deny = () => { throw new Error("MAIN_SDK_SWITCH_PROBE_PLAN_INVALID"); };
const closed = (value, keys) => {
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype || Reflect.ownKeys(value).some(key => typeof key !== "string")
      || Object.keys(value).sort().join() !== [...keys].sort().join()
      || Object.values(Object.getOwnPropertyDescriptors(value)).some(item => !item.enumerable || !Object.hasOwn(item, "value"))) deny();
};
const exact = (left, right) => { if (!isDeepStrictEqual(left, right)) deny(); };
const absolute = value => typeof value === "string" && path.isAbsolute(value) && path.normalize(value) === value && !/[\p{Cc}\p{Cf}]/u.test(value) && value !== "/";
export function validatePlan(plan, { requireFrozen = false } = {}) {
  closed(plan, ["schema_version", "probe_id", "state", "versions", "source_root", "candidate_root", "node_root", "work_root", "cases", "provider", "sentinels", "source_pins", "candidate_pins", "candidate_inventory", "limits"]);
  if (plan.schema_version !== 1 || plan.probe_id !== "main-sdk-switch-1.0.1" || !["requires-final-freeze", "frozen"].includes(plan.state) || requireFrozen && plan.state !== "frozen") deny();
  closed(plan.versions, ["pi", "pi_ai", "node"]); exact(plan.versions, { pi: "1.0.1", pi_ai: "1.0.2", node: "24.14.0" });
  exact([plan.source_root, plan.candidate_root, plan.node_root, plan.work_root], ["/source", "/candidate", "/node", "/work"]); exact(plan.cases, CASES);
  closed(plan.provider, ["id", "model", "alternate_model", "outside_model", "api", "base_url"]);
  exact(plan.provider, { id: "synthetic-main-probe", model: "selected", alternate_model: "alternate", outside_model: "outside", api: "synthetic-main-probe", base_url: "https://synthetic.invalid/unused" });
  exact(plan.sentinels, ["OWN_FAILED_TASK_SENTINEL", "OWN_UNFINISHED_TASK_SENTINEL"]);
  closed(plan.limits, ["case_timeout_ms", "total_timeout_ms", "max_result_bytes"]); exact(plan.limits, { case_timeout_ms: 5000, total_timeout_ms: 60000, max_result_bytes: 65536 });
  for (const [kind, prefix] of [["source_pins", "agents/pi/runtime/"], ["candidate_pins", "node_modules/@earendil-works/"]]) {
    const pins = plan[kind];
    if (!pins || types.isProxy(pins) || Object.getPrototypeOf(pins) !== Object.prototype || Object.keys(pins).length > 512
      || Reflect.ownKeys(pins).some(key => typeof key !== "string")
      || Object.values(Object.getOwnPropertyDescriptors(pins)).some(item => !item.enumerable || !Object.hasOwn(item, "value"))) deny();
    for (const [name, sha] of Object.entries(pins)) if (!name.startsWith(prefix) || path.normalize(name) !== name || name.split("/").includes("..") || !/^[a-f0-9]{64}$/.test(sha)) deny();
  }
  if (plan.candidate_inventory !== null) {
    closed(plan.candidate_inventory, ["fixture", "sha256", "entries", "file_count", "bytes"]);
    const receipt = plan.candidate_inventory;
    if (receipt.fixture !== "candidate-inventory.json" || !/^[a-f0-9]{64}$/.test(receipt.sha256)
      || !Number.isSafeInteger(receipt.entries) || receipt.entries < 1 || receipt.entries > 65536
      || !Number.isSafeInteger(receipt.file_count) || receipt.file_count < 1 || receipt.file_count > receipt.entries
      || !Number.isSafeInteger(receipt.bytes) || receipt.bytes < 0 || receipt.bytes > 512 * 1024 * 1024) deny();
  }
  if (plan.state === "frozen") {
    if (plan.candidate_inventory === null) deny();
    for (const name of ["official-model-scope.ts", "official-model-runtime.ts", "official-session.ts"]) if (!plan.source_pins["agents/pi/runtime/" + name]) deny();
    for (const pkg of ["pi-coding-agent", "pi-ai"]) if (!plan.candidate_pins[`node_modules/@earendil-works/${pkg}/package.json`]) deny();
  }
  return structuredClone(plan);
}
export function buildInvocation({ plan, sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot }) {
  validatePlan(plan, { requireFrozen: true });
  const mounts = [sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot];
  if (mounts.some(value => !absolute(value)) || new Set(mounts).size !== mounts.length || !/^\/(tmp|data)\//.test(workRoot)
      || [sourceRoot, candidateRoot, nodeRoot, fixtureRoot].some(root => workRoot === root || workRoot.startsWith(root + "/"))) deny();
  // 当前系统bwrap不支持--clearenv；外层必须使用返回的空env，guest再核对完整ENV。
  const argv = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", sourceRoot, "/source", "--ro-bind", candidateRoot, "/candidate", "--ro-bind", nodeRoot, "/node",
    "--dir", "/probe", "--ro-bind", worker, "/probe/worker.mjs", "--ro-bind", fixtureRoot, "/probe/fixture",
    "--symlink", "/candidate/node_modules", "/probe/node_modules", "--bind", workRoot, "/work"];
  for (const [name, value] of Object.entries(ENV)) argv.push("--setenv", name, value);
  argv.push("--chdir", "/work", "/node/bin/node", "--max-old-space-size=512", "/probe/worker.mjs", "--native-main-sdk-switch-probe");
  return { argv, env: {} };
}
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
function verifyPins(root, pins) {
  for (const [name, digest] of Object.entries(pins)) {
    const file = path.join(root, name), stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink() && fs.realpathSync(file) === file && stat.size <= 4 * 1024 * 1024);
    assert.equal(hash(fs.readFileSync(file)), digest);
  }
}
// 自有外层冻结准备：只读核全树并返回计划，不写文件、不spawn、不importSDK。
export async function prepareFrozenPlan({ plan, sourceRoot, candidateRoot, receiptPath, receiptSha256 }) {
  const fixed = validatePlan(plan);
  if (![sourceRoot, candidateRoot, receiptPath].every(absolute) || fs.realpathSync(sourceRoot) !== sourceRoot) deny();
  const helper = new URL("../tests/fixtures/pi/main-sdk-switch-probe/candidate-inventory.mjs", import.meta.url);
  const { verifyCandidateInventory } = await import(helper.href);
  const measured = verifyCandidateInventory({ candidateRoot, receiptPath, receiptSha256 });
  fixed.candidate_inventory = { fixture: "candidate-inventory.json", ...measured };
  fixed.source_pins = {};
  const runtime = path.join(sourceRoot, "agents/pi/runtime");
  for (const name of fs.readdirSync(runtime)) if (name.endsWith(".ts")) {
    const file = path.join(runtime, name), info = fs.lstatSync(file);
    if (!info.isFile() || info.isSymbolicLink() || fs.realpathSync(file) !== file || info.size > 4 * 1024 * 1024) deny();
    fixed.source_pins["agents/pi/runtime/" + name] = hash(fs.readFileSync(file));
  }
  fixed.candidate_pins = {};
  for (const pkg of ["pi-coding-agent", "pi-ai"]) {
    const name = `node_modules/@earendil-works/${pkg}/package.json`;
    fixed.candidate_pins[name] = hash(fs.readFileSync(path.join(candidateRoot, name)));
  }
  fixed.state = "frozen"; return validatePlan(fixed, { requireFrozen: true });
}
const bounded = async (value, ms = 5000) => {
  let timer; try { return await Promise.race([value, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(Error("MAIN_SDK_SWITCH_PROBE_TIMEOUT")), ms); })]); }
  finally { clearTimeout(timer); }
};
const deferred = () => { let resolve; const promise = new Promise(value => { resolve = value; }); return { promise, resolve }; };
async function runNative() {
  // 固定沙箱输入通过之后才加载包根公开API；没有进程启动API。
  assert.equal(process.argv.length, 3); assert.equal(process.argv[2], "--native-main-sdk-switch-probe");
  assert.deepEqual(Object.keys(process.env).sort(), Object.keys(ENV).sort());
  for (const [name, value] of Object.entries(ENV)) assert.equal(process.env[name], value);
  assert.equal(process.platform, "linux"); assert.equal(process.version, "v24.14.0");
  const planFile = "/probe/fixture/plan.json", planStat = fs.lstatSync(planFile);
  assert(planStat.isFile() && !planStat.isSymbolicLink() && planStat.size <= 256 * 1024);
  const plan = validatePlan(JSON.parse(fs.readFileSync(planFile, "utf8")), { requireFrozen: true });
  verifyPins("/source", plan.source_pins); verifyPins("/candidate", plan.candidate_pins);
  const { verifyCandidateInventory } = await import("./fixture/candidate-inventory.mjs");
  const inventory = verifyCandidateInventory({ candidateRoot: "/candidate", receiptPath: "/probe/fixture/" + plan.candidate_inventory.fixture, receiptSha256: plan.candidate_inventory.sha256, receiptRootName: "pi-base-1e4f9e6dc96d1083ed6b201deef2356cea8dcf743839db887f703f7ae386a76f" });
  // 收据path前缀保持原candidate目录basename；仅读取其在/candidate的相同相对树。
  exact(inventory, { sha256: plan.candidate_inventory.sha256, entries: plan.candidate_inventory.entries, file_count: plan.candidate_inventory.file_count, bytes: plan.candidate_inventory.bytes });
  const sdk = await import("@earendil-works/pi-coding-agent"), ai = await import("@earendil-works/pi-ai");
  assert.equal(sdk.VERSION, plan.versions.pi);
  assert.equal(JSON.parse(fs.readFileSync("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, plan.versions.pi_ai);
  const own = file => import(pathToFileURL(`/source/agents/pi/runtime/${file}`).href);
  const { createOfficialModelScope } = await own("official-model-scope.ts");
  const { createOfficialModels } = await own("official-models.ts");
  const { createOfficialSessionFactory } = await own("official-session.ts");
  const { digest } = await own("managed-types.ts");
  const groups = ["extensions", "skills", "prompts", "themes", "roles"];
  const result = { schema_version: 1, probe_id: plan.probe_id, status: "failed", cases: [] };
  let fixtureIndex = 0;
  async function fixture() {
    const root = `/work/case-${++fixtureIndex}`, cwd = root + "/project", instanceRoot = root + "/instance";
    for (const dir of [cwd, instanceRoot + "/pi-home", root + "/sessions"]) fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(instanceRoot + "/pi-home/AGENTS.md", "Own synthetic Main SDK probe", { mode: 0o600, flag: "wx" });
    fs.writeFileSync(instanceRoot + "/pi-home/APPEND_SYSTEM.md", "No shell, network, MCP or account operations", { mode: 0o600, flag: "wx" });
    const p = plan.provider, sentModels = [], state = { auth: 0, authWait: null, authReady: null, authSignal: null };
    const faux = ai.fauxProvider({ provider: p.id, api: p.api, models: [p.model, p.alternate_model, p.outside_model].map(id => ({ id, input: ["text"], contextWindow: 8192, maxTokens: 512 })) });
    const models = faux.models.map(model => ({ ...model, baseUrl: p.base_url }));
    // 自有Provider经公开createProvider/registerNativeProvider配置；不改原faux或SDK实例。
    const provider = ai.createProvider({ id: p.id, models, auth: { apiKey: { name: "Own synthetic auth",
      check: async () => ({ type: "api_key", source: "synthetic" }), resolve: async ({ signal }) => {
        state.auth++; if (state.authWait) state.authSignal = signal;
        state.authReady?.resolve(); if (state.authWait) await state.authWait.promise;
        return { auth: { apiKey: "synthetic" }, source: "synthetic" };
      } } }, api: { stream: (model, ...args) => { sentModels.push(model.id); return faux.provider.stream(model, ...args); }, streamSimple: (model, ...args) => { sentModels.push(model.id); return faux.provider.streamSimple(model, ...args); } } });
    const raw = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsStore: new ai.InMemoryModelsStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
    raw.registerNativeProvider(provider); await raw.refresh({ providers: [p.id], allowNetwork: false });
    await raw.getAvailable(p.id);
    const config = { api: p.api, baseUrl: p.base_url, models: [p.model, p.alternate_model].map(id => ({ id, input: ["text"], contextWindow: 8192, maxTokens: 512 })) };
    const binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" };
    const manifest = { schema_version: 1, profile_id: "pi-base", engine: "node", bootstrap: false, plugins: [], options: { discovery: { project_resources: false } },
      resources: Object.fromEntries(groups.map(group => [group, []])), resource_ids: Object.fromEntries(groups.map(group => [group, {}])),
      provider_bindings: { [p.id]: binding }, model_configuration: { schema_version: 1, providers: { [p.id]: { ...binding, credential_ref: "secret:SYNTHETIC", config } } },
      model_bindings: { main: { provider: p.id, model: p.model } }, allowed_models: [p.model, p.alternate_model].map(model => ({ provider: p.id, model })) };
    const variable = "AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0, 16).toUpperCase(), modelPath = instanceRoot + "/pi-home/models.json";
    fs.writeFileSync(modelPath, JSON.stringify({ providers: { [p.id]: { ...config, apiKey: "$" + variable } } }), { mode: 0o600, flag: "wx" });
    const descriptions = createOfficialModels({ manifest, path: modelPath, modelRuntime: raw });
    const before = Object.getOwnPropertyDescriptors(raw), scope = createOfficialModelScope({ modelRuntime: raw, manifest, describe: descriptions.describe });
    assert(scope.modelRuntime instanceof sdk.ModelRuntime); assert.deepEqual(Object.getOwnPropertyDescriptors(raw), before);
    const settingsValue = { packages: [], extensions: [], skills: [], prompts: [], themes: [], defaultProjectTrust: "never", enableInstallTelemetry: false, enableAnalytics: false, cacheWarming: "off",
      compaction: { enabled: false, reserveTokens: 512, keepRecentTokens: 1 }, retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0 } } };
    const settings = { settingsManager: sdk.SettingsManager.inMemory(settingsValue, { projectTrusted: false }), snapshot: () => structuredClone(settingsValue) };
    const installed = { runtime_identity: "a".repeat(64), resources: Object.fromEntries(groups.map(group => [group, []])) };
    const create = createOfficialSessionFactory({ sdk, manifest, installed, instanceRoot, runtimeRoot: "/candidate", engine: "node", settings,
      runtimeHandle: { modelRuntime: scope.modelRuntime, configurationDigest: digest(manifest.model_configuration), check: scope.check },
      configuration: () => ({ policyDigest: "b".repeat(64), projectConstraintsDigest: "c".repeat(64) }), toolDefinitions: [], thinkingLevel: "off" });
    const manager = sdk.SessionManager.create(cwd, root + "/sessions"), created = await create({ cwd, sessionManager: manager });
    await created.session.bindExtensions({ mode: "json", onError: () => { throw Error("MAIN_SDK_SWITCH_PROBE_EXTENSION_ERROR"); } });
    return { root, cwd, raw, before, scope, faux, sentModels, state, manager, create, session: created.session, created, provider: p,
      async dispose() { await this.session.abort(); this.session.dispose(); } };
  }
  async function scenario(id, body) {
    const f = await fixture();
    try { const observations = await bounded(body(f)); result.cases.push({ case_id: id, outcome: "observed", observations }); }
    catch (error) {
      const known = new Set(["MODEL_SCOPE_OPTIONS_UNSUPPORTED", "MODEL_SCOPE_CREDENTIAL_MUTATION", "MODEL_SCOPE_AUTH_OVERRIDE", "MODEL_SCOPE_PROPERTY_DENIED", "MODEL_SCOPE_MODEL_DENIED", "MODEL_SCOPE_OPERATION_FAILED", "MODEL_SCOPE_AUTH_INVALID", "MODEL_SCOPE_HEADERS_INVALID"]);
      result.cases.push({ case_id: id, outcome: "failed", observations: { stage: f.probeStage ?? "case-body", sender_count: f.faux.state.callCount,
        failure_class: known.has(error?.message) ? error.message : error?.code === "ERR_ASSERTION" ? "assertion" : error?.message === "Nothing to compact" ? "nothing-to-compact" : "unclassified" } });
      throw Error("MAIN_SDK_SWITCH_PROBE_CASE_FAILED");
    }
    finally { await bounded(f.dispose()); }
  }
  try {
    await scenario("selected-alternate", async f => {
      assert.equal(f.session.model.id, f.provider.model);
      const alternate = f.scope.modelRuntime.getModel(f.provider.id, f.provider.alternate_model);
      assert(alternate); await f.session.setModel(alternate);
      assert.equal(f.session.model.id, f.provider.alternate_model);
      f.faux.setResponses([ai.fauxAssistantMessage("synthetic alternate done")]);
      await f.session.prompt("own selected alternate prompt", { expandPromptTemplates: false });
      assert.equal(f.faux.state.callCount, 1); assert.deepEqual(f.sentModels, [f.provider.alternate_model]);
      await f.created.configurationSnapshot();
      assert(f.manager.getEntries().some(entry => entry.type === "message" && entry.message?.role === "assistant"
        && entry.message.model === f.provider.alternate_model && entry.message.stopReason === "stop"));
      return { public_set_model: true, actual_sent_model: f.sentModels[0], sender_count: 1, scoped_configuration_snapshot: true };
    });
    await scenario("outside-after-switch", async f => {
      await f.session.setModel(f.scope.modelRuntime.getModel(f.provider.id, f.provider.alternate_model));
      const outside = f.raw.getModel(f.provider.id, f.provider.outside_model);
      await f.session.setModel(outside);
      try { await f.session.prompt("must not send outside", { expandPromptTemplates: false }); } catch { /* 公共SDK可通过error消息表达失败。 */ }
      assert.equal(f.faux.state.callCount, 0); assert.deepEqual(f.sentModels, []);
      return { prior_selected_switch: true, outside_sender_count: 0 };
    });
    let oauthStage = "setup";
    try {
    const oauthRoot = "/work/native-oauth";
    fs.mkdirSync(oauthRoot + "/pi-home", { recursive: true, mode: 0o700 });
    const oauthId = "synthetic-native-oauth", credentials = new ai.InMemoryCredentialStore();
    const existing = { type: "oauth", refresh: "synthetic-existing-refresh", access: "synthetic-existing-access", expires: Date.now() + 3600000 };
    await credentials.modify("unselected-existing-native", async () => existing);
    const state = { login: 0, refresh: 0, toAuth: 0, originalReceiver: false, prompts: 0 };
    const oauth = { name: "Own synthetic native OAuth", async login(interaction, options) {
      state.login++; state.originalReceiver = this === oauth;
      assert.equal(options.getDeviceId(), "own-synthetic-device");
      assert.equal(await interaction.prompt({ type: "text", message: "Own synthetic public login" }), "own-code");
      return { type: "oauth", refresh: "synthetic-new-refresh", access: "synthetic-new-access", expires: Date.now() + 3600000 };
    }, async refresh() { state.refresh++; throw Error("MAIN_SDK_SWITCH_PROBE_REFRESH_FORBIDDEN"); },
    async toAuth(credential) { state.toAuth++; assert.equal(credential.access, "synthetic-new-access"); return { apiKey: credential.access }; } };
    const faux = ai.fauxProvider({ provider: oauthId, api: "synthetic-oauth", models: [{ id: "main", input: ["text"], contextWindow: 8192, maxTokens: 512 }] });
    const nativeProvider = ai.createProvider({ id: oauthId, models: faux.models.map(model => ({ ...model, baseUrl: "https://synthetic.invalid/unused" })), auth: { oauth }, api: {
      stream: (...args) => faux.provider.stream(...args), streamSimple: (...args) => faux.provider.streamSimple(...args) } });
    oauthStage = "raw-create";
    const raw = await sdk.ModelRuntime.create({ credentials, modelsStore: new ai.InMemoryModelsStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
    oauthStage = "register-refresh";
    raw.registerNativeProvider(nativeProvider); await raw.refresh({ providers: [oauthId], allowNetwork: false });
    const binding = { logical_id: "synthetic-oauth", auth_kind: "oauth", owner: "pi-native" };
    const manifest = { provider_bindings: { [oauthId]: binding }, model_configuration: { schema_version: 1,
      providers: { [oauthId]: { ...binding, credential_ref: null, config: null } } }, allowed_models: [{ provider: oauthId, model: "main" }] };
    oauthStage = "own-descriptions";
    const descriptions = createOfficialModels({ manifest, path: oauthRoot + "/pi-home/models.json", modelRuntime: raw });
    oauthStage = "scope-create";
    const scope = createOfficialModelScope({ modelRuntime: raw, manifest, describe: descriptions.describe });
    oauthStage = "login";
    try {
      await bounded(scope.modelRuntime.login(oauthId, "oauth", { prompt: async () => { state.prompts++; return "own-code"; }, notify: () => {} }, { getDeviceId: () => "own-synthetic-device" }));
      assert.equal(state.login, 1); assert.equal(state.originalReceiver, true); assert.equal(state.prompts, 1);
      assert.deepEqual(await credentials.read("unselected-existing-native"), existing);
      assert.equal((await credentials.read(oauthId)).type, "oauth");
      assert.deepEqual(await scope.modelRuntime.listCredentials(), [{ providerId: oauthId, type: "oauth" }]);
      const auth = await scope.modelRuntime.getAuth(scope.modelRuntime.getModel(oauthId, "main"));
      assert.equal(auth.auth.apiKey, "synthetic-new-access"); assert.equal(state.refresh, 0); assert.equal(state.toAuth, 1);
      faux.setResponses([ai.fauxAssistantMessage("synthetic native OAuth done")]);
      const message = await scope.modelRuntime.completeSimple(scope.modelRuntime.getModel(oauthId, "main"), { messages: [{ role: "user", content: "own synthetic OAuth request", timestamp: Date.now() }] }, { ...auth.auth, ...(auth.env === undefined ? {} : { env: auth.env }) });
      assert.equal(message.stopReason, "stop"); assert.equal(faux.state.callCount, 1);
      result.cases.push({ case_id: "public-native-oauth-login", outcome: "observed", observations: { public_login_calls: 1,
        original_auth_receiver: true, synthetic_interaction_prompts: 1, original_memory_store_written: true,
        unrelated_native_credential_unchanged: true, selected_metadata_only: true, selected_get_auth_consumed: true,
        refresh_count: 0, sender_count: 1, real_account_or_tui: false } });
    } catch (error) {
      result.cases.push({ case_id: "public-native-oauth-login", outcome: "failed", observations: { login_calls: state.login,
        stage: state.login ? "after-login" : "login", failure_class: error?.code === "ERR_ASSERTION" ? "assertion" : "public-login-failed" } });
      throw Error("MAIN_SDK_SWITCH_PROBE_CASE_FAILED");
    }
    } catch (error) {
      if (!result.cases.some(item => item.case_id === "public-native-oauth-login")) result.cases.push({ case_id: "public-native-oauth-login", outcome: "failed", observations: { stage: oauthStage, failure_class: ["pi-model-config-invalid", "pi-model-config-private", "MODEL_SCOPE_INCOMPATIBLE", "MODEL_SCOPE_MODEL_DENIED", "MODEL_SCOPE_RUNTIME_ERROR"].includes(error?.message) ? error.message : "public-oauth-setup-failed" } });
      throw Error("MAIN_SDK_SWITCH_PROBE_CASE_FAILED");
    }
    result.status = "observed";
  } finally {
    for (const id of CASES) if (!result.cases.some(item => item.case_id === id)) result.cases.push({ case_id: id, outcome: "not-run", observations: {} });
    const bytes = JSON.stringify(result) + "\n"; assert(Buffer.byteLength(bytes) <= plan.limits.max_result_bytes);
    fs.writeFileSync("/work/probe-result.json", bytes, { mode: 0o600, flag: "wx" }); process.stdout.write(bytes);
  }
  assert.equal(result.status, "observed");
}
// import此文件用于纯plan测试时不会访问官方包、创建目录或进入native入口。
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] !== "--native-main-sdk-switch-probe") { process.stderr.write("MAIN_SDK_SWITCH_PROBE_REQUIRES_SEPARATE_AUTHORIZATION_AND_FROZEN_PLAN\n"); process.exitCode = 2; }
  else {
    const deadline = setTimeout(() => { process.stderr.write("MAIN_SDK_SWITCH_PROBE_TIMEOUT\n"); process.exit(2); }, 60000);
    try { await runNative(); } catch { process.stderr.write("MAIN_SDK_SWITCH_PROBE_FAILED\n"); process.exitCode = 2; } finally { clearTimeout(deadline); }
  }
}
