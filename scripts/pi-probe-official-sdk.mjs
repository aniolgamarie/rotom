// 待显式 native 授权后执行；准备/语法检查不 import 官方 SDK。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { createProbeExtension } from "./fixture/approved-extension.mjs";

const FIXTURE = "/probe/fixture";
const TOOL_NAMES = ["probe_leaf", "probe_parent", "probe_ui_required", "probe_cancel_leaf", "probe_cancel_parent"];
const CASES = ["resource-whitelist", "nested-tools", "nested-block", "cancel-propagation", "no-ui-admission", "reload-whitelist"];
const result = { schema_version: 1, probe_id: "official-sdk-1.0.1", versions: { pi: null, pi_ai: null }, status: "failed", cases: [], limitations: [
  "Synthetic stream only; no real model/account exercised",
  "No-UI assertion covers the self-owned tool admission guard, not all host UI operations",
  "Network isolation and readonly mounts require independent verification of the bwrap invocation",
  "This probe does not grant product/release acceptance",
  "Empty package selection and absent installation artifacts are observed; no installer-process trace is collected",
] };
let outputReady = false;
let phase = "setup-arguments";
const closed = (value, keys) => assert.deepEqual(Object.keys(value).sort(), keys.slice().sort());
const bounded = async (promise) => {
  let timer;
  try { return await Promise.race([promise, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(new Error("PROBE_TIMEOUT")), 5000); })]); }
  finally { clearTimeout(timer); }
};
function emit() {
  // 输出只含闭合观察，不回显 SDK 异常、模型正文或环境值。
  if (outputReady) {
    try { fs.writeFileSync("/work/probe-result.json", JSON.stringify(result) + "\n", { flag: "wx", mode: 0o600 }); }
    catch { result.status = "failed"; result.limitations.push("Output publication failed; existing output was not overwritten"); }
  }
  process.stdout.write(JSON.stringify(result) + "\n");
}
function readPlan() {
  assert.equal(process.argv.length, 3); assert.equal(process.argv[2], "--native-sdk-probe");
  phase = "environment";
  const env = { HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1", OTEL_SDK_DISABLED: "true",
    TMPDIR: "/work/tmp", XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data", XDG_CACHE_HOME: "/work/cache", XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8" };
  closed(process.env, Object.keys(env));
  for (const [name, value] of Object.entries(env)) assert.equal(process.env[name], value);
  phase = "fixture-plan";
  const plan = JSON.parse(fs.readFileSync(`${FIXTURE}/plan.json`, "utf8"));
  closed(plan, ["schema_version", "probe_id", "versions", "provider", "paths", "resources", "files", "placements"]);
  assert.equal(plan.schema_version, 1); assert.equal(plan.probe_id, result.probe_id);
  assert.deepEqual(plan.versions, { pi: "1.0.1", pi_ai: "1.0.2" });
  assert.deepEqual(plan.provider, { id: "synthetic-sdk-probe", model: "synthetic-model", api: "synthetic-sdk-probe", base_url: "https://synthetic.invalid/unused", api_key: "synthetic-no-account" });
  assert.deepEqual(plan.paths, { cwd: "/work/ancestor/project", agent_dir: "/work/agent", home: "/work/home", output: "/work/probe-result.json" });
  assert.deepEqual(plan.resources, { extension: "approved-extension.mjs", skill: "approved/skills/probe-approved/SKILL.md", prompt: "approved/prompts/approved-prompt.md" });
  phase = "fixture-hashes";
  for (const [relative, digest] of Object.entries(plan.files)) {
    assert(!path.isAbsolute(relative) && !relative.split("/").includes(".."));
    const absolute = path.join(FIXTURE, relative);
    assert(!fs.lstatSync(absolute).isSymbolicLink());
    assert.equal(createHash("sha256").update(fs.readFileSync(absolute)).digest("hex"), digest);
  }
  phase = "fixture-placement";
  for (const placement of plan.placements) {
    closed(placement, ["source", "target"]);
    assert(Object.hasOwn(plan.files, placement.source));
    assert(placement.target.startsWith("/work/") && path.normalize(placement.target) === placement.target);
    fs.mkdirSync(path.dirname(placement.target), { recursive: true });
    fs.copyFileSync(path.join(FIXTURE, placement.source), placement.target, fs.constants.COPYFILE_EXCL);
  }
  for (const directory of [plan.paths.cwd, plan.paths.agent_dir, plan.paths.home, "/work/tmp", "/work/empty-bin", "/work/config", "/work/data", "/work/cache", "/work/state"]) fs.mkdirSync(directory, { recursive: true });
  outputReady = true;
  return plan;
}
async function main() {
  const plan = readPlan();
  // 只有本函数通过固定 native 输入后才 import 两个包的根公开 exports。
  phase = "official-package-import";
  const sdk = await import("@earendil-works/pi-coding-agent");
  const ai = await import("@earendil-works/pi-ai");
  result.versions.pi = sdk.VERSION;
  result.versions.pi_ai = JSON.parse(fs.readFileSync("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version;
  assert.deepEqual(result.versions, plan.versions);
  const state = { hooks: [], starts: [], leafCalls: 0, blockLeaf: false, nextTool: null, requestCount: 0, cancelObserved: false, uiDenied: false, extensionErrors: 0 };
  const settings = sdk.SettingsManager.inMemory({ packages: [], extensions: [], skills: [], prompts: [], themes: [],
    cacheWarming: "off", compaction: { enabled: false }, retry: { enabled: false } }, { projectTrusted: false });
  phase = "model-runtime";
  const credentials = new ai.InMemoryCredentialStore();
  const runtime = await sdk.ModelRuntime.create({ credentials, modelsStore: new ai.InMemoryModelsStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  const streamSimple = (model, _context, options) => {
    state.requestCount++;
    const stream = ai.createAssistantMessageEventStream();
    queueMicrotask(async () => {
      try {
        const requested = state.nextTool; state.nextTool = null;
        await options?.onPayload?.({ synthetic: true }, model);
        await options?.onResponse?.({ status: 200, headers: {} }, model);
        const message = { role: "assistant", api: plan.provider.api, provider: plan.provider.id, model: model.id, timestamp: Date.now(),
          content: requested ? [{ type: "toolCall", id: `probe-call-${state.requestCount}`, name: requested, arguments: {} }] : [{ type: "text", text: "synthetic done" }],
          stopReason: requested ? "toolUse" : "stop", usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
        stream.push({ type: "start", partial: message });
        stream.push({ type: "done", reason: message.stopReason, message }); stream.end(message);
      } catch { stream.end(); }
    });
    return stream;
  };
  runtime.registerProvider(plan.provider.id, { api: plan.provider.api, baseUrl: plan.provider.base_url, apiKey: plan.provider.api_key, authHeader: false,
    streamSimple, models: [{ id: plan.provider.model, name: "Synthetic probe", reasoning: false, input: ["text"], contextWindow: 8192, maxTokens: 256,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
  phase = "resource-loader";
  const loader = new sdk.DefaultResourceLoader({ cwd: plan.paths.cwd, agentDir: plan.paths.agent_dir, settingsManager: settings,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [], additionalSkillPaths: [`${FIXTURE}/${plan.resources.skill}`],
    additionalPromptTemplatePaths: [`${FIXTURE}/${plan.resources.prompt}`], additionalThemePaths: [],
    extensionFactories: [{ name: "approved-probe", factory: createProbeExtension(state, ai.Type) }],
    systemPrompt: "PROBE_EXPLICIT_SYSTEM", appendSystemPrompt: ["PROBE_EXPLICIT_APPEND"] });
  await bounded(loader.reload());
  phase = "session-construction";
  const { session } = await sdk.createAgentSession({ cwd: plan.paths.cwd, agentDir: plan.paths.agent_dir, modelRuntime: runtime,
    model: runtime.getModel(plan.provider.id, plan.provider.model), thinkingLevel: "off", tools: TOOL_NAMES,
    resourceLoader: loader, settingsManager: settings, sessionManager: sdk.SessionManager.inMemory(plan.paths.cwd) });
  const events = [];
  const unsubscribe = session.subscribe((event) => {
    if (event.type.startsWith("tool_execution_")) events.push({ type: event.type, tool: event.toolName, id: event.toolCallId, parent: event.parentToolCallId ?? null, error: event.isError ?? null });
  });
  const checkResources = async () => {
    phase = "resources-extensions";
    assert.deepEqual(loader.getExtensions().extensions.map((extension) => extension.path), ["<inline:approved-probe>"]);
    assert.equal(loader.getExtensions().errors.length, 0);
    assert.equal(state.extensionErrors, 0);
    phase = "resources-skills";
    assert.deepEqual(loader.getSkills().skills.map((skill) => skill.name), ["probe-approved"]);
    phase = "resources-prompts";
    assert.deepEqual(loader.getPrompts().prompts.map((prompt) => prompt.name), ["approved-prompt"]);
    phase = "resources-context";
    assert.deepEqual(loader.getThemes().themes, []); assert.deepEqual(loader.getAgentsFiles().agentsFiles, []);
    assert.equal(loader.getSystemPrompt(), "PROBE_EXPLICIT_SYSTEM"); assert.deepEqual(loader.getAppendSystemPrompt(), ["PROBE_EXPLICIT_APPEND"]);
    phase = "resources-active-tools";
    assert.deepEqual(session.getActiveToolNames().sort(), TOOL_NAMES.slice().sort());
    phase = "resources-credentials";
    assert.deepEqual(await credentials.list(), []);
    phase = "resources-decoy-installation";
    assert(!fs.existsSync("/work/decoy-loaded"));
    assert(!fs.existsSync("/work/agent/node_modules") && !fs.existsSync(`${plan.paths.cwd}/node_modules`));
    return { extensions: 1, skills: 1, prompts: 1, themes: 0, context_files: 0, decoy_loaded: false, credentials: 0 };
  };
  const check = async (case_id, run) => {
    phase = case_id;
    try { result.cases.push({ case_id, outcome: "observed", observations: await run() }); }
    catch { result.cases.push({ case_id, outcome: "failed", observations: {} }); throw new Error("PROBE_ASSERTION"); }
  };
  try {
    phase = "extension-binding";
    // 公开 onError binding 同时确保 reload 重新绑定并派发 session_start。
    await bounded(session.bindExtensions({ mode: "json", onError: () => { state.extensionErrors++; } }));
    await check("resource-whitelist", checkResources);
    await check("nested-tools", async () => {
      state.nextTool = "probe_parent"; await bounded(session.prompt("synthetic nested", { expandPromptTemplates: false }));
      const parent = events.find((event) => event.type === "tool_execution_start" && event.tool === "probe_parent");
      const child = events.find((event) => event.type === "tool_execution_start" && event.tool === "probe_leaf");
      assert(parent && child && child.parent === parent.id && child.id.startsWith(`${parent.id}/`));
      assert(state.hooks.some((event) => event.type === "tool_call" && event.parent === parent.id));
      assert(state.leafHasSignal && state.leafCalls === 1);
      return { parent_event: true, child_event: true, parent_linked: true, extension_hook: true };
    });
    await check("nested-block", async () => {
      const before = state.leafCalls;
      const offset = events.length;
      state.blockLeaf = true; state.nextTool = "probe_parent";
      try { await bounded(session.prompt("synthetic nested denial", { expandPromptTemplates: false })); }
      finally { state.blockLeaf = false; }
      const denied = events.slice(offset).find((event) => event.type === "tool_execution_end" && event.tool === "probe_leaf");
      assert(state.leafCalls === before && state.nestedError === true && denied?.error === true);
      return { body_blocked: true, nested_error: true, host_error_event: true, leaf_calls: state.leafCalls };
    });
    await check("cancel-propagation", async () => {
      const ready = new Promise((resolve) => { state.cancelReady = resolve; });
      state.nextTool = "probe_cancel_parent";
      const prompting = session.prompt("synthetic cancel", { expandPromptTemplates: false });
      await bounded(ready); await bounded(session.abort()); await bounded(prompting);
      assert(state.cancelObserved && state.parentAborted);
      const parent = events.find((event) => event.type === "tool_execution_start" && event.tool === "probe_cancel_parent");
      const child = events.find((event) => event.type === "tool_execution_start" && event.tool === "probe_cancel_leaf");
      assert(parent && child && child.parent === parent.id);
      return { inherited_signal_aborted: true, parent_signal_aborted: true, nested_parent_linked: true };
    });
    await check("no-ui-admission", async () => {
      state.nextTool = "probe_ui_required"; await bounded(session.prompt("synthetic UI denial", { expandPromptTemplates: false }));
      assert.equal(state.uiHasUI, false); assert(state.uiDenied);
      assert(events.some((event) => event.type === "tool_execution_end" && event.tool === "probe_ui_required" && event.error === true));
      return { hasUI: false, required_operation_denied: true, native_error_result: true };
    });
    await check("reload-whitelist", async () => {
      await bounded(session.reload()); const observations = await checkResources();
      phase = "reload-session-context";
      assert(state.starts.length >= 2 && state.starts.every((start) => start.hasUI === false && start.mode === "json"));
      assert.equal(state.extensionErrors, 0);
      observations.session_start_events = state.starts.length; observations.extension_errors = state.extensionErrors; return observations;
    });
    result.status = "observed";
  } finally { unsubscribe(); session.dispose(); }
}
const hardDeadline = setTimeout(() => {
  for (const case_id of CASES) if (!result.cases.some((item) => item.case_id === case_id)) result.cases.push({ case_id, outcome: "not-run", observations: {} });
  emit(); process.exit(2);
}, 30000);
try { await main(); }
catch (error) {
  result.limitations.push(`Failure phase: ${phase}`);
  if (["ERR_MODULE_NOT_FOUND", "MODULE_NOT_FOUND", "ERR_PACKAGE_PATH_NOT_EXPORTED", "ERR_ASSERTION", "EACCES", "ENOENT", "EROFS"].includes(error?.code)) {
    result.limitations.push(`Failure code: ${error.code}`);
  }
  for (const case_id of CASES) if (!result.cases.some((item) => item.case_id === case_id)) result.cases.push({ case_id, outcome: "not-run", observations: {} });
} finally { clearTimeout(hardDeadline); emit(); }
process.exitCode = result.status === "observed" ? 0 : 2;
