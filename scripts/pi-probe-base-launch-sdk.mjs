// 默认只验证封闭计划；native入口只用公开SDK和自有launch。
import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
export function validateLaunchPlan(plan) {
  assert.deepEqual(Object.keys(plan).sort(), ["cases", "schema_version", "sdk_abi_only"].sort());
  assert.equal(plan.schema_version, 1); assert.equal(plan.sdk_abi_only, true);
  assert.deepEqual(plan.cases, ["L01-help", "L02-print", "L03-footer"]); return plan;
}
const hash = value => createHash("sha256").update(value).digest("hex");
const LIMITS = { sender_calls: 4, starts: 0, rpc_calls: 128, fixture_bytes: 262144, operations_per_scene: 64 };
async function native() {
  assert.deepEqual(process.argv.slice(2), ["--native-base-launch-sdk-probe"]); assert.equal(process.env.PI_PROBE_NATIVE, "1");
  const plan = validateLaunchPlan(JSON.parse(fs.readFileSync("/probe/fixture/plan.json")));
  const source = JSON.parse(fs.readFileSync("/probe/fixture/source-plan.json"));
  const { verifyCandidateInventory } = await import("./fixture/candidate-inventory.mjs");
  const r = source.candidate_inventory;
  verifyCandidateInventory({ candidateRoot: "/candidate", receiptPath: "/probe/fixture/" + r.fixture, receiptSha256: r.sha256, receiptRootName: r.receipt_root_name });
  for (const row of source.source_inventory) { const data = fs.readFileSync("/source/" + row.path); assert.equal(data.length, row.bytes); assert.equal(hash(data), row.sha256); }
  const own = name => import(pathToFileURL("/source/agents/pi/runtime/" + name + ".ts").href);
  const { launch } = await own("official-launch");
  const { createFakeSupervisor } = await import("./fixture/base12-helper.mjs");
  const { createOfficialFileRuntime } = await own("official-file-runtime");
  const result = { schema_version: 1, sdk_abi_only: true, actual_python_or_os_authority: false, cases: [] };
  const budget = { sender: 0, starts: 0, rpc: 0 }; let phase = "help";
  try {
    const bomb = new Proxy({}, { get() { throw Error("HELP_ACCESSED_SDK"); } });
    assert.equal((await launch({ sdk: bomb, argv: ["--help"] })).code, 0);
    result.cases.push({ case_id: "L01-help", outcome: "observed", sdk_or_inference: 0 });
    const sdk = await import("@earendil-works/pi-coding-agent"), ai = await import("@earendil-works/pi-ai");
    const { createOfficialModels } = await own("official-models"), { createOfficialModelScope } = await own("official-model-scope");
    const id = "launch";
    const root = "/work/scene-" + id, cwd = root + "/project", instanceRoot = root + "/instance", stateRoot = root + "/state";
    for (const dir of [cwd, instanceRoot + "/pi-home", stateRoot, root + "/sessions"]) fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(cwd + "/source.txt", "alpha\nneedle 中文\nomega\n", { mode: 0o600 }); fs.writeFileSync(cwd + "/ignored.txt", "ignored sentinel", { mode: 0o600 });
    for (const name of ["AGENTS.md", "APPEND_SYSTEM.md"]) fs.writeFileSync(instanceRoot + "/pi-home/" + name, "Own synthetic Base component probe\n", { mode: 0o600 });
    phase = "synthetic-provider";
    const faux = ai.fauxProvider({ provider: "synthetic-base", api: "synthetic-base", models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] });
    const model = { ...faux.getModel(), baseUrl: "https://synthetic.invalid/unused" };
    const provider = ai.createProvider({ id: model.provider, models: [model], auth: { apiKey: { name: "synthetic", check: async () => ({ type: "api_key" }), resolve: async () => ({ auth: { apiKey: "synthetic" } }) } },
      api: { stream: (...args) => { if (++budget.sender > LIMITS.sender_calls) fail(); return faux.provider.stream(...args); }, streamSimple: (...args) => { if (++budget.sender > LIMITS.sender_calls) fail(); return faux.provider.streamSimple(...args); } } });
    const raw = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsStore: new ai.InMemoryModelsStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false }); raw.registerNativeProvider(provider);
    await raw.refresh({ providers: [model.provider], allowNetwork: false });
    const config = { api: model.api, baseUrl: model.baseUrl, models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] }, binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" };
    const groups = ["extensions", "skills", "prompts", "themes", "roles"];
    const manifest = { schema_version: 1, profile_id: "pi-base", engine: "node", bootstrap: false, cost_reporting: "unmetered", plugins: ["pi-todo", "loop-guard", "colorful-footer"],
      plugin_capabilities: { "pi-todo": { capability_id: "todo", model_tools: ["todo"] }, "loop-guard": { capability_id: "loop-protection", model_tools: [] }, "colorful-footer": { capability_id: "footer", model_tools: [] } },
      resources: Object.fromEntries(groups.map(k => [k, []])), resource_ids: Object.fromEntries(groups.map(k => [k, {}])),
      options: { discovery: { project_resources: false }, todo: {}, ui: { footer: {} }, loop_guard: { enforcementMode: false ? "enforce" : "off", advisoryMode: "off", repeatLimit: 1 },
        paths: { roots: { project: { path: cwd, purpose: "project" } } }, external_tools: { shell: { executable: "/synthetic/bash", args: [] } } },
      provider_bindings: { [model.provider]: binding }, model_configuration: { schema_version: 1, providers: { [model.provider]: { ...binding, credential_ref: "secret:SYNTHETIC", config } } },
      model_bindings: { main: { provider: model.provider, model: "main" } }, allowed_models: [{ provider: model.provider, model: "main" }] };
    if (false) manifest.native_mcp = { schema_version: 1, loaded_config: { servers: [{ name: "docs", source: "agentcfg:registry/mcp/docs", scope: "extension",
      config: { type: "stdio", command: "/synthetic/docs", args: [], cwd, env: {}, exposure: "hidden", toolExposure: { query: "codemode" } } }], errors: [], autoEnableCodemode: false },
      bindings: { docs: { transport: "stdio", command_ref: "docs", authentication: "none" } }, allowed_tools: { docs: ["query"] } };
    const modelPath = instanceRoot + "/pi-home/models.json"; fs.writeFileSync(modelPath, JSON.stringify({ providers: { [model.provider]: { ...config, apiKey: "$AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0, 16).toUpperCase() } } }), { mode: 0o600 });
    phase = "model-scope";
    const models = createOfficialModels({ manifest, path: modelPath, modelRuntime: raw }), scope = createOfficialModelScope({ modelRuntime: raw, manifest, describe: models.describe });
    const settingsValue = { packages: [], extensions: [], skills: [], prompts: [], themes: [], defaultProjectTrust: "never", enableInstallTelemetry: false, enableAnalytics: false, cacheWarming: "off", compaction: { enabled: false }, retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0 } } };
    const settings = { settingsManager: sdk.SettingsManager.inMemory(settingsValue, { projectTrusted: false }), snapshot: () => structuredClone(settingsValue) };
    const installed = { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64), runtime_identity: "d".repeat(64),
      resources: Object.fromEntries(groups.map(k => [k, k === "extensions" ? [{ id: "pi-todo", capability_id: "todo", path: "agents/pi/packages/todo-vendor/index.ts" },
        { id: "loop-guard", capability_id: "loop-protection", path: "agents/pi/packages/loop-guard/index.ts" }, { id: "colorful-footer", capability_id: "footer", path: "agents/pi/packages/colorful-footer/index.ts" }] : []])) };
    if (false) {
      manifest.options.mcp = { servers: { docs: { transport: "stdio", command_ref: "docs" } } };
      manifest.options.external_tools.docs = { executable: "/synthetic/docs", args: [], interactive: true, project_root: "project" };
    }

    Object.assign(installed, { schema_version: 2, engine: "node", entrypoint: "node_modules/@earendil-works/pi-coding-agent/dist/index.js", package_path: "package.json",
      sdk_package: "@earendil-works/pi-coding-agent", sdk_version: "1.0.1", ai_package: "@earendil-works/pi-ai", ai_version: "1.0.2", toolchains: { node: process.version }, platform: "linux-x86_64" });
    manifest.permission_policy = { synthetic: true };
    fs.writeFileSync(instanceRoot + "/pi-home/settings.json", JSON.stringify(settingsValue), { mode: 0o600 });
    const fake = createFakeSupervisor({ cwd, stateRoot, budget, limits: LIMITS });
    const supervisor = { options: fake.supervisor.options, call(method, args) {
      if (method === "handshake") return Promise.resolve({ role: "manager", runtime_identity: installed.runtime_identity, slice_identity: installed.slice_identity,
        manager_activation_id: "synthetic-activation", instance_id: "synthetic-instance", owner_nonce: "synthetic-owner" });
      return fake.supervisor.call(method, args);
    } };
    faux.setResponses([ai.fauxAssistantMessage("OWN_LAUNCH_SYNTHETIC_REPLY")]);
    phase = "real-runPrintMode";
    let footerObservations;
    const observeRuntime = async (...args) => {
      const runtime = await createOfficialFileRuntime(...args);
      try {
      sdk.initTheme("dark", false);
      const tokens = "accent border borderAccent borderMuted success error warning muted dim text thinkingText scrollbarTrack scrollbarThumb searchMatchText userMessageText customMessageText customMessageLabel toolTitle toolOutput mdHeading mdLink mdLinkUrl mdCode mdCodeBlock mdCodeBlockBorder mdQuote mdQuoteBorder mdHr mdListBullet toolDiffAdded toolDiffRemoved toolDiffContext syntaxComment syntaxKeyword syntaxFunction syntaxVariable syntaxString syntaxNumber syntaxType syntaxOperator syntaxPunctuation thinkingOff thinkingMinimal thinkingLow thinkingMedium thinkingHigh thinkingXhigh thinkingMax bashMode".split(" ");
      const theme = new sdk.Theme(Object.fromEntries(tokens.map(key => [key, "#ffffff"])), Object.fromEntries("selectedBg searchMatchBg userMessageBg customMessageBg toolPendingBg toolSuccessBg toolErrorBg".split(" ").map(key => [key, "#000000"])), "truecolor");
      let component, registrations = 0;
      const ui = { notify() {}, setStatus() {}, setWidget() {}, setWorkingMessage() {}, setTitle() {}, setHeader() {},
        setFooter(factory) { if (!factory) return; registrations++; component = factory({ requestRender() {} }, theme, { onBranchChange() {}, getGitBranch() { return undefined; } }); } };
      phase = "footer-public-bind";
      const bind = () => runtime.session.bindExtensions({ mode: "tui", uiContext: ui, onError(error) { throw error; } });
      runtime.setRebindSession(bind); await bind();
      assert(component?.render);
      const previous = ai.fauxAssistantMessage("own prior Footer usage sentinel");
      previous.usage = { input: 987, output: 654, cacheRead: 0, cacheWrite: 0, totalTokens: 1641, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
      args[1].sessionManager.appendMessage(previous); component.invalidate();
      const wide = component.render(200).join("\n"), narrow = component.render(80).join("\n");
      assert(wide.includes("987")); assert(wide.includes("费用未计量")); assert(narrow.includes("费用未计量")); assert(!wide.includes("$0"));
      const first = registrations;
      await runtime.newSession();
      assert(registrations > first); const next = component.render(200).join("\n"); assert(next.includes("费用未计量")); assert(!next.includes("987"));
      footerObservations = { actual_component: true, wide: 200, narrow: 80, unmetered_chinese: true, new_session_registered_fresh_component: true, previous_usage_cache_cleared: true, actual_tty: false };
      return runtime;
      } catch (error) { result.public_observer_error = { error_type: error.name, message: String(error.message).slice(0, 192) }; await runtime.dispose(); throw error; }
    };
    const answer = await launch({ sdk, ai, manifest, installed, instanceRoot, runtimeRoot: "/source", cwd, engine: "node", supervisor,
      argv: ["--print", "own synthetic prompt"], verifyDeployment() {}, createRuntime: observeRuntime, initializeRuntime: () => async () => ({ modelRuntime: scope.modelRuntime, check: scope.check, configurationDigest: models.declarationDigest }) });
    assert.equal(answer.code, 0); assert.equal(budget.sender, 1); assert.equal(budget.starts, 0);
    result.cases.push({ case_id: "L02-print", outcome: "observed", sender: budget.sender, service_starts: 0, default_authentication_route: false });
    result.cases.push({ case_id: "L03-footer", outcome: "observed", observations: footerObservations });
  } catch (error) { result.cases.push({ case_id: phase, outcome: "failed", error_type: error.name, message: String(error.message).slice(0, 192) }); process.exitCode = 2; }
  finally { result.budget = budget; fs.writeFileSync("/work/probe-result.json", JSON.stringify(result) + "\n", { mode: 0o600 }); process.stdout.write(JSON.stringify(result) + "\n"); }
}
if (process.argv[2] === "--native-base-launch-sdk-probe") await native();
