#!/usr/bin/env node
// 显式原生 SDK 验收：临时 HOME、模拟监督者/交互驱动，零模型请求。
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

if (process.argv.length !== 5 || process.argv[2] !== "--allow-host") {
  throw Error("Usage: node scripts/smoke-pi-public-api.mjs --allow-host RUNTIME EVIDENCE.json");
}
process.umask(0o077);
const runtimeRoot = resolve(process.argv[3]), evidence = resolve(process.argv[4]);
const installed = JSON.parse(readFileSync(join(runtimeRoot, "runtime/profile.json"), "utf8"));
assert.equal(installed.sdk_version, "0.84.4");
assert.equal(installed.engine, "node");
assert.equal(process.version, installed.toolchains.node);
const root = mkdtempSync(join(tmpdir(), "rotom-pi-public-api-"));
const checks = {};
try {
  const instanceRoot = join(root, "instance"), agentDir = join(instanceRoot, "pi-home"), cwd = join(root, "project");
  for (const path of [instanceRoot, agentDir, cwd, join(root, "home"), join(agentDir, "extensions"), join(cwd, ".pi"), join(cwd, ".pi/extensions")]) mkdirSync(path, { mode: 0o700 });
  process.env = { HOME: join(root, "home"), PATH: dirname(process.execPath), PI_CODING_AGENT_DIR: agentDir,
    PI_CODING_AGENT_SESSION_DIR: join(agentDir, "sessions"), PI_OFFLINE: "1", PI_SKIP_VERSION_CHECK: "1",
    XDG_CONFIG_HOME: join(root, "config"), XDG_DATA_HOME: join(root, "data"), XDG_CACHE_HOME: join(root, "cache"), XDG_STATE_HOME: join(root, "state") };
  const save = (path, data) => writeFileSync(path, data, { mode: 0o600 });
  save(join(agentDir, "settings.json"), JSON.stringify({ packages: ["npm:must-not-install"], extensions: ["/must-not-load"], theme: "dark" }));
  save(join(agentDir, "AGENTS.md"), "Synthetic selected rules\n");
  save(join(agentDir, "APPEND_SYSTEM.md"), "Synthetic append rules\n");
  save(join(agentDir, "models.json"), JSON.stringify({ providers: { fixture: { api: "openai-completions", baseUrl: "https://example.invalid/v1", apiKey: "synthetic-key",
    models: [{ id: "selected", name: "Fixture", reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8192, maxTokens: 64 }] } } }));
  save(join(agentDir, "extensions/selected.mjs"), "export default api => { globalThis.__rotomSelected = (globalThis.__rotomSelected ?? 0) + 1; };\n");
  save(join(cwd, ".pi/extensions/unselected.mjs"), "export default () => { throw Error('UNSELECTED_FACTORY'); };\n");
  const sdk = await import(pathToFileURL(join(runtimeRoot, installed.entrypoint)).href);
  const { launch } = await import(pathToFileURL(resolve(dirname(fileURLToPath(import.meta.url)), "../agents/pi/runtime/launch.ts")).href);
  const original = [sdk.DefaultPackageManager.prototype.resolve, sdk.DefaultResourceLoader.prototype.extendResources, sdk.SessionManager.open, sdk.ModelRuntime.prototype.streamSimple];
  const kinds = ["extensions", "skills", "prompts", "themes", "roles"];
  const resources = Object.fromEntries(kinds.map(kind => [kind, []])), resource_ids = Object.fromEntries(kinds.map(kind => [kind, {}]));
  resources.extensions.push("pi-home/extensions/selected.mjs"); resource_ids.extensions.selected = resources.extensions[0];
  const manifest = { schema_version: 1, engine: "node", bootstrap: false, plugins: [], resources, resource_ids,
    project_resources: [], external_skills: [], role_bindings: {}, options: { discovery: { project_resources: false } },
    model_bindings: { main: { provider: "fixture", model: "selected" } }, allowed_models: [{ provider: "fixture", model: "selected" }] };
  let active = 0;
  const supervisor = { async call(method) {
    if (method === "handshake") return { role: "manager", runtime_identity: installed.runtime_identity, slice_identity: installed.slice_identity };
    if (method === "activity_summary") return { active_count: active };
    throw Error("UNEXPECTED_SUPERVISOR_CALL");
  } };
  class Driver {
    constructor(runtime) { this.runtime = runtime; }
    async run() {
      const runtime = this.runtime, session = runtime.session;
      checks.selected_extension = globalThis.__rotomSelected === 1;
      checks.model = session.model.provider === "fixture" && session.model.id === "selected";
      assert.ok(Object.isFrozen(session.model));
      const sessions = join(agentDir, "sessions"), bad = join(sessions, "old.jsonl"), current = join(sessions, "current.jsonl");
      mkdirSync(sessions, { recursive: true, mode: 0o700 });
      const header = { type: "session", version: 3, id: "synthetic", timestamp: "2026-10-15T00:00:00Z", cwd };
      save(bad, JSON.stringify({ ...header, version: 2 }) + "\n");
      const before = readFileSync(bad);
      assert.equal((await runtime.switchSession(bad)).cancelled, true);
      assert.deepEqual(readFileSync(bad), before); checks.old_session_unmodified = true;
      await assert.rejects(runtime.importFromJsonl(bad), /pi-session-import-unsupported/); checks.import_closed = true;
      active = 1;
      await assert.rejects(session.reload(), /SESSION_ACTIVITY_PROTECTED/);
      assert.equal((await runtime.newSession()).cancelled, true); checks.active_change_blocked = true;
      active = 0;
      const appendPath = join(agentDir, "APPEND_SYSTEM.md"), appendBefore = readFileSync(appendPath);
      save(appendPath, "unexpected replacement\n");
      await assert.rejects(session.reload(), /pi-resource-changed/);
      assert.equal(globalThis.__rotomSelected, 1);
      save(appendPath, appendBefore); checks.resource_drift_blocked = true;
      await session.reload(); checks.reload = globalThis.__rotomSelected === 2;
      save(current, JSON.stringify(header) + "\n");
      assert.equal((await runtime.switchSession(current)).cancelled, false); checks.resume = true;
      const manager = runtime.session.sessionManager;
      const entry = manager.appendMessage({ role: "user", content: "Synthetic fork fixture", timestamp: Date.now() });
      assert.equal((await runtime.fork(entry)).cancelled, false); checks.fork = true;
      const { workerLoader } = await import(pathToFileURL(resolve(dirname(fileURLToPath(import.meta.url)), "../agents/pi/runtime/managed-worker.ts")).href);
      const worker = await sdk.createAgentSession({ cwd, agentDir, modelRuntime: runtime.services.modelRuntime,
        model: runtime.session.model, settingsManager: sdk.SettingsManager.inMemory(), sessionManager: sdk.SessionManager.inMemory(cwd),
        resourceLoader: workerLoader(sdk, { system_prompt: "Synthetic readonly worker" }), noTools: "builtin", tools: ["tk_read"],
        customTools: [{ name: "tk_read", label: "Synthetic read", description: "Synthetic readonly test", parameters: { type: "object", properties: {} },
          async execute() { return { content: [{ type: "text", text: "synthetic" }], details: {} }; } }] });
      assert.deepEqual(worker.session.getAllTools().map(tool => tool.name), ["tk_read"]);
      worker.session.setActiveToolsByName(["bash", "write", "tk_read"]);
      assert.deepEqual(worker.session.getActiveToolNames(), ["tk_read"]);
      await worker.session.dispose(); checks.worker_tool_registry = true;
      assert.equal((await runtime.newSession()).cancelled, false); checks.new_session = true;
      assert.deepEqual([sdk.DefaultPackageManager.prototype.resolve, sdk.DefaultResourceLoader.prototype.extendResources, sdk.SessionManager.open, sdk.ModelRuntime.prototype.streamSimple], original);
      checks.host_methods_unchanged = true;
    }
  }
  const result = await launch({ sdk: { ...sdk, InteractiveMode: Driver }, manifest, installed, instanceRoot, runtimeRoot, cwd, engine: "node", supervisor });
  assert.equal(result.code, 0);
  assert.ok(Object.values(checks).every(Boolean));
  writeFileSync(evidence, JSON.stringify({ status: "PASS", checks, platform: process.platform + "-" + process.arch,
    lock_identity: installed.lock_identity, slice_identity: installed.slice_identity, runtime_identity: installed.runtime_identity,
    sdk: installed.sdk_version, model_calls: 0, supervisor: "simulated", interaction: "controlled driver, native SDK", real_accounts: "NOT RUN" }, null, 2) + "\n", { mode: 0o600 });
} finally {
  delete globalThis.__rotomSelected;
  rmSync(root, { recursive: true, force: true });
}
