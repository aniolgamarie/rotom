// 仅在另行授权的固定RPC沙箱中运行；node --check不import官方包。
import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";
import { permissionExtension } from "./fixture/extension.mjs";

const CASES = ["timeout", "cancelled", "wrong-id", "abort-late", "confirmed"];
const ENV = { HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1",
  OTEL_SDK_DISABLED: "true", TMPDIR: "/work/tmp", XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data",
  XDG_CACHE_HOME: "/work/cache", XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8" };
let readyToSave = false;
const state = { schema_version: 1, case_id: null, versions: { pi: null, pi_ai: null, node: process.versions.node },
  phase: "prepare", native_started: false, has_ui: null, mode: null, tool_starts: 0, tool_ends: 0, tool_error: null,
  confirm_result: null, signal_aborted: false, body_count: 0, settled: false, shutdown_seen: false,
  extension_errors: 0, credentials_empty: false, active_tools_exact: false };
function save() {
  if (!readyToSave) return;
  const target = "/work/.state-tmp";
  const fd = fs.openSync(target, "wx", 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(state) + "\n"); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  fs.renameSync(target, "/work/state.json");
}
const closed = (value, keys) => assert.deepEqual(Object.keys(value).sort(), keys.slice().sort());
async function main() {
  assert.equal(process.argv.length, 4);
  assert.equal(process.argv[2], "--native-rpc-worker");
  assert(CASES.includes(process.argv[3])); state.case_id = process.argv[3];
  closed(process.env, Object.keys(ENV));
  for (const [key, value] of Object.entries(ENV)) assert.equal(process.env[key], value);
  const plan = JSON.parse(fs.readFileSync("/probe/fixture/plan.json", "utf8"));
  closed(plan, ["schema_version", "probe_id", "versions", "lock_sha256", "provider", "cases", "confirmation_timeout_ms", "files"]);
  assert.equal(plan.schema_version, 1); assert.equal(plan.probe_id, "official-rpc-1.0.1");
  assert.deepEqual(plan.cases, CASES);
  assert.deepEqual(plan.versions, { pi: "1.0.1", pi_ai: "1.0.2", node: "24.14.0" });
  assert.equal(plan.lock_sha256, "f2c0af34b3c0d9195705509c26513de7d8aeb2fa4b6f3d395a2d58ecdd82c4ac");
  assert.equal(plan.confirmation_timeout_ms, 1000);
  assert.deepEqual(plan.provider, { id: "synthetic-rpc-probe", api: "synthetic-rpc-probe", model: "synthetic-model",
    base_url: "https://synthetic.invalid/unused", api_key: "synthetic-no-account" });
  closed(plan.files, ["worker.mjs", "extension.mjs"]);
  for (const [name, file] of [["worker.mjs", "/probe/worker.mjs"], ["extension.mjs", "/probe/fixture/extension.mjs"]]) {
    assert(!fs.lstatSync(file).isSymbolicLink());
    assert.equal(createHash("sha256").update(fs.readFileSync(file)).digest("hex"), plan.files[name]);
  }
  assert.equal(createHash("sha256").update(fs.readFileSync("/candidate/package-lock.json")).digest("hex"), plan.lock_sha256);
  for (const directory of ["home", "empty-bin", "tmp", "config", "data", "cache", "state", "project", "agent"]) fs.mkdirSync(`/work/${directory}`, { mode: 0o700 });
  readyToSave = true; state.phase = "official-import"; state.native_started = true; save();
  // 不使用CLI、compat或私有模块，只通过两包根公开exports。
  const sdk = await import("@earendil-works/pi-coding-agent");
  const ai = await import("@earendil-works/pi-ai");
  state.versions.pi = sdk.VERSION;
  state.versions.pi_ai = JSON.parse(fs.readFileSync("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version;
  assert.deepEqual(state.versions, plan.versions); state.phase = "runtime"; save();
  const credentials = new ai.InMemoryCredentialStore();
  const models = await sdk.ModelRuntime.create({ credentials, modelsStore: new ai.InMemoryModelsStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  let calls = 0;
  models.registerProvider(plan.provider.id, { api: plan.provider.api, baseUrl: plan.provider.base_url,
    apiKey: plan.provider.api_key, authHeader: false,
    models: [{ id: plan.provider.model, name: "Synthetic RPC model", reasoning: false, input: ["text"], contextWindow: 8192,
      maxTokens: 256, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    streamSimple(model, _context, options) {
      const stream = ai.createAssistantMessageEventStream(); const tool = ++calls === 1;
      queueMicrotask(async () => {
        try {
          await options?.onPayload?.({ synthetic: true }, model);
          await options?.onResponse?.({ status: 200, headers: {} }, model);
          const message = { role: "assistant", api: plan.provider.api, provider: plan.provider.id, model: model.id, timestamp: Date.now(),
            content: tool ? [{ type: "toolCall", id: "synthetic-call-1", name: "probe_confirmed_body", arguments: {} }]
              : [{ type: "text", text: "synthetic complete" }], stopReason: tool ? "toolUse" : "stop",
            usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
          stream.push({ type: "start", partial: message }); stream.push({ type: "done", reason: message.stopReason, message }); stream.end(message);
        } catch { state.extension_errors++; save(); stream.end(); }
      });
      return stream;
    },
  });
  const createRuntime = async ({ cwd, agentDir, sessionManager, sessionStartEvent }) => {
    assert.equal(cwd, "/work/project"); assert.equal(agentDir, "/work/agent");
    const settings = sdk.SettingsManager.inMemory({ packages: [], extensions: [], skills: [], prompts: [], themes: [],
      compaction: { enabled: false }, retry: { enabled: false }, cacheWarming: "off" }, { projectTrusted: false });
    const services = await sdk.createAgentSessionServices({ cwd, agentDir, modelRuntime: models, settingsManager: settings,
      resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
        additionalExtensionPaths: [], additionalSkillPaths: [], additionalPromptTemplatePaths: [], additionalThemePaths: [],
        extensionFactories: [{ name: "synthetic-rpc-guard", factory: permissionExtension(state, save, fs, ai.Type, plan.confirmation_timeout_ms) }],
        systemPrompt: "Synthetic RPC probe only", appendSystemPrompt: [] } });
    assert.equal(services.diagnostics.filter((item) => item.type === "error").length, 0);
    const created = await sdk.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent,
      model: models.getModel(plan.provider.id, plan.provider.model), thinkingLevel: "off", tools: ["probe_confirmed_body"] });
    created.session.subscribe((event) => {
      if (event.type === "tool_execution_start" && event.toolName === "probe_confirmed_body") state.tool_starts++;
      if (event.type === "tool_execution_end" && event.toolName === "probe_confirmed_body") {
        state.tool_ends++; state.tool_error = event.isError;
      }
      if (event.type === "agent_settled") state.settled = true;
      save();
    });
    state.active_tools_exact = JSON.stringify(created.session.getActiveToolNames()) === JSON.stringify(["probe_confirmed_body"]);
    state.credentials_empty = (await credentials.list()).length === 0;
    save();
    return { ...created, services, diagnostics: services.diagnostics };
  };
  const runtime = await sdk.createAgentSessionRuntime(createRuntime, { cwd: "/work/project", agentDir: "/work/agent",
    sessionManager: sdk.SessionManager.inMemory("/work/project") });
  state.phase = "rpc"; save();
  // 公开runRpcMode处理stdin EOF：await runtime.dispose()后退出；parent同时核shutdown与真实exit。
  await sdk.runRpcMode(runtime);
}
const deadline = setTimeout(() => { state.phase = "deadline"; save(); process.stderr.write("RPC probe deadline\n"); process.exit(124); }, 10000);
main().catch(() => { clearTimeout(deadline); state.phase = "failed"; save(); process.stderr.write("RPC probe failed\n"); process.exit(2); });
