// 准备/语法检查不import SDK；只有另获授权的固定隔离入口才运行公开SDK。
import assert from "node:assert/strict";
import fs from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const probeId = "confirmed-intent-public-sdk-async-v2";
const cases = ["confirmed-idle", "declined", "no-ui", "base", "off", "unrelated-input",
  "nested-follow-up", "handled-input", "canceled", "settling-deferred", "async-confirmed", "async-late-resolve", "async-late-reject"];
const result = { schema_version: 1, probe_id: probeId, status: "failed", cases: [], product_gate: false };
const environment = { HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", TMPDIR: "/work/tmp",
  XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data", XDG_CACHE_HOME: "/work/cache",
  XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1",
  PI_SKIP_VERSION_CHECK: "1", OTEL_SDK_DISABLED: "true" };
const bounded = async promise => {
  let timer;
  try { return await Promise.race([promise, new Promise((_, fail) => { timer = setTimeout(() => fail(new Error("PROBE_TIMEOUT")), 5000); })]); }
  finally { clearTimeout(timer); }
};
const equalBinding = value => assert.deepEqual(value, { session_scope: "a".repeat(32), intent_ref: "b".repeat(32), request_ref: "c".repeat(32) });
export async function observeCase(report, caseId, body) {
  assert(cases.includes(caseId));
  assert(!report.cases.some(value => value.case_id === caseId));
  const state = { case_id: caseId, outcome: "failed", confirm_calls: 0, intent_allocations: 0, request_allocations: 0,
    model_requests: 0, scoped_tool_calls: 0, unscoped_tool_calls: 0, command_status: null, extension_errors: 0, async_binding_waits: 0, async_late_results: 0 };
  // 开始即留失败行；中途抛错仍保留已知计数，不能把已执行场景写成not-run。
  report.cases.push(state);
  await body(state);
  state.outcome = "observed";
  return state;
}
export async function observeAsyncTool(scope, id, state, onWaiting = () => {}) {
  assert(["async-confirmed", "async-late-resolve", "async-late-reject"].includes(state.case_id));
  assert(/^scope-call\/[1-9][0-9]*$/.test(id));
  const waits = state.case_id === "async-confirmed" ? 2 : 1;
  const pending = [];
  for (let i=0;i<waits;i++) { state.async_binding_waits++; pending.push(scope.bindingForToolAsync(id)); }
  // 两个请求均在execute原ID下进入allocator后才通知外侧失效，不验证仅早停。
  onWaiting();
  const bindings = await Promise.all(pending);
  if (state.case_id === "async-confirmed") {
    for (const binding of bindings) { equalBinding(binding); assert(Object.isFrozen(binding)); }
    assert.equal(bindings[0], bindings[1]); equalBinding(await scope.bindingForToolAsync(id));
    state.scoped_tool_calls++;
  } else {
    assert(bindings.every(binding => binding === null)); assert.equal(await scope.bindingForToolAsync(id), null);
    state.unscoped_tool_calls++;
  }
  return bindings;
}
function syntheticUI(confirm) {
  // 完整公开UI形状；只有confirm用于本探针，其余接口无终端/编辑器/外部动作。
  const noop = () => {};
  return { confirm, select: async () => undefined, input: async () => undefined, notify: noop,
    onTerminalInput: () => noop, setStatus: noop, setWorkingMessage: noop, setWorkingVisible: noop,
    setWorkingIndicator: noop, setHiddenThinkingLabel: noop, setWidget: noop, setFooter: noop, setHeader: noop,
    setTitle: noop, custom: async () => undefined, pasteToEditor: noop, setEditorText: noop,
    getEditorText: () => "", editor: async () => undefined, addAutocompleteProvider: noop,
    setEditorComponent: noop, getEditorComponent: () => undefined, theme: Object.freeze({}),
    getAllThemes: () => [], getTheme: () => undefined, setTheme: () => ({ success: false }),
    getToolsExpanded: () => false, setToolsExpanded: noop };
}

async function runCase(caseId, sdk, ai, createConfirmedIntentScope, state) {
  const cwd = "/work/case-" + caseId, agentDir = cwd + "/agent";
  fs.mkdirSync(agentDir, { recursive: true, mode: 0o700 });
  let session, scope, extensionApi, executeId, lateResolve, lateReject;
  const asynchronous = caseId.startsWith("async-");
  let nextTools = [], deferredRequested = false;
  let ready;
  const toolReady = new Promise(resolve => { ready = resolve; });
  let nestedObserved;
  const nestedInput = new Promise(resolve => { nestedObserved = resolve; });
  const sessionManager = sdk.SessionManager.inMemory(cwd);
  scope = createConfirmedIntentScope({ enabled: caseId !== "off",
    current: () => ({ profile: caseId === "base" ? "pi-base" : "pi-full", session_id: sessionManager.getSessionId(), cwd,
      runtime_identity: "d".repeat(64), config_identity: "e".repeat(64), policy_generation: 1, cancel_epoch: 0 }),
    allocateIntent: async () => {
      state.intent_allocations++;
      return { session_scope: "a".repeat(32), intent_ref: "b".repeat(32) };
    },
    ...(asynchronous ? { allocateRequestAsync: request => {
      state.request_allocations++;
      assert(Object.isFrozen(request)); assert.equal(request.tool_call_id, executeId);
      assert.equal(request.session_scope, "a".repeat(32)); assert.equal(request.intent_ref, "b".repeat(32));
      if (caseId === "async-confirmed") return Promise.resolve("c".repeat(32));
      return new Promise((done, fail) => { lateResolve=done; lateReject=fail; });
    } } : { allocateRequest: () => { state.request_allocations++; return "c".repeat(32); } }),
    submit: objective => session.prompt(objective, { source: "extension", expandPromptTemplates: false }),
    confirmationMessage: "Synthetic intent probe. No real model or account is used.",
    confirmTimeoutMs: 2000, scopeTimeoutMs: 10000 });

  const factory = pi => {
    extensionApi = pi;
    pi.registerCommand("scope-probe", { description: "Synthetic confirmed intent probe", handler: async (args, ctx) => {
      const status = await scope.run(args, ctx);
      assert.deepEqual(Object.keys(status).sort(), ["code", "status"]);
      state.command_status = status.status;
    } });
    pi.on("input", event => {
      scope.onInput(event);
      if (event.text === "synthetic nested follow-up") nestedObserved();
      return { action: caseId === "handled-input" ? "handled" : "continue" };
    });
    pi.on("agent_start", () => { scope.onAgentStart(); });
    pi.on("session_shutdown", () => { scope.retire(); });
    pi.on("agent_settled", async (_event, ctx) => {
      scope.onAgentSettled();
      if (caseId === "settling-deferred" && !deferredRequested) {
        deferredRequested = true;
        assert.equal(ctx.isIdle(), true);
        nextTools = ["scope_leaf"];
        const status = await scope.run("synthetic deferred objective", ctx);
        state.command_status = status.status;
        assert.equal(status.status, "not-started");
      }
    });
    const observe = id => {
      const binding = scope.bindingForTool(id);
      if (binding === null) state.unscoped_tool_calls++;
      else { equalBinding(binding); state.scoped_tool_calls++; }
      return binding;
    };
    pi.registerTool({ name: "scope_leaf", label: "Synthetic scope leaf", description: "Observes an internal synthetic scope only.",
      parameters: ai.Type.Object({}), async execute(id) {
        if (asynchronous) {
          executeId=id;
          await observeAsyncTool(scope,id,state,ready);
          return { content: [{ type: "text", text: "synthetic async leaf" }], details: {} };
        }
        const binding = observe(id);
        if (binding !== null) equalBinding(scope.bindingForTool(id));
        return { content: [{ type: "text", text: "synthetic leaf" }], details: {} };
      } });
    pi.registerTool({ name: "scope_nested", label: "Synthetic nested scope", description: "Queues one synthetic message to test invalidation.",
      parameters: ai.Type.Object({}), async execute(id) {
        equalBinding(observe(id));
        // 只使用公开扩展API；这个void调用不能续签原用户范围。
        extensionApi.sendUserMessage("synthetic nested follow-up", { deliverAs: "followUp" });
        await bounded(nestedInput);
        assert.equal(scope.bindingForTool(id), null);
        return { content: [{ type: "text", text: "synthetic nested" }], details: {} };
      } });
    pi.registerTool({ name: "scope_cancel", label: "Synthetic cancel scope", description: "Waits only for the public tool AbortSignal.",
      parameters: ai.Type.Object({}), async execute(id, _params, signal) {
        equalBinding(observe(id));
        assert(signal && !signal.aborted);
        const stopped = new Promise(resolve => { signal.addEventListener("abort", resolve, { once: true }); });
        ready();
        await bounded(stopped);
        assert.equal(scope.bindingForTool(id), null);
        return { content: [{ type: "text", text: "synthetic canceled" }], details: {} };
      } });
  };
  const settings = sdk.SettingsManager.inMemory({ packages: [], extensions: [], skills: [], prompts: [], themes: [],
    cacheWarming: "off", compaction: { enabled: false }, retry: { enabled: false } }, { projectTrusted: false });
  const credentials = new ai.InMemoryCredentialStore();
  const modelRuntime = await sdk.ModelRuntime.create({ credentials, modelsStore: new ai.InMemoryModelsStore(), modelsPath: null,
    allowModelNetwork: false, refreshOnCreate: false });
  // 每case独立Provider/API名，避免跨case全局注册残留改变合成oracle。
  const provider = "synthetic-intent-probe-" + caseId, api = provider, modelId = "synthetic-model";
  const streamSimple = (model, _context, options) => {
    state.model_requests++;
    assert(state.model_requests <= 8);
    const stream = ai.createAssistantMessageEventStream();
    queueMicrotask(async () => {
      try {
        await options?.onPayload?.({ synthetic: true }, model);
        await options?.onResponse?.({ status: 200, headers: {} }, model);
        const requested = nextTools.shift();
        const message = { role: "assistant", api, provider, model: model.id, timestamp: Date.now(),
          content: requested ? [{ type: "toolCall", id: (asynchronous ? "scope-call/" : "scope-call-") + state.model_requests, name: requested, arguments: {} }]
            : [{ type: "text", text: "synthetic done" }], stopReason: requested ? "toolUse" : "stop",
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
        stream.push({ type: "start", partial: message });
        stream.push({ type: "done", reason: message.stopReason, message });
        stream.end(message);
      } catch { stream.end(); }
    });
    return stream;
  };
  modelRuntime.registerProvider(provider, { api, baseUrl: "https://synthetic.invalid/unused", apiKey: "synthetic-no-account",
    authHeader: false, streamSimple, models: [{ id: modelId, name: "Synthetic intent probe", reasoning: false, input: ["text"],
      contextWindow: 8192, maxTokens: 256, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
  const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager: settings, noExtensions: true, noSkills: true,
    noPromptTemplates: true, noThemes: true, noContextFiles: true, additionalExtensionPaths: [], additionalSkillPaths: [],
    additionalPromptTemplatePaths: [], additionalThemePaths: [], systemPrompt: "SYNTHETIC_INTENT_PROBE",
    extensionFactories: [{ name: "synthetic-confirmed-intent", factory }] });
  await bounded(loader.reload());
  const created = await sdk.createAgentSession({ cwd, agentDir, modelRuntime, model: modelRuntime.getModel(provider, modelId),
    thinkingLevel: "off", noTools: "all", tools: ["scope_leaf", "scope_nested", "scope_cancel"],
    resourceLoader: loader, settingsManager: settings, sessionManager });
  session = created.session;
  try {
    assert.equal(created.modelFallbackMessage, undefined);
    assert.deepEqual(loader.getExtensions().errors, []);
    assert.deepEqual(loader.getExtensions().extensions.map(value => value.path), ["<inline:synthetic-confirmed-intent>"]);
    assert.deepEqual(session.getActiveToolNames().sort(), ["scope_cancel", "scope_leaf", "scope_nested"]);
    assert.deepEqual(await credentials.list(), []);
    const confirm = async (_title, _message, options) => {
      assert(options?.signal instanceof AbortSignal);
      assert.equal(options.timeout, 2000);
      assert.equal(options.signal.aborted, false);
      state.confirm_calls++;
      return caseId !== "declined";
    };
    // uiContext只在public binding中提供；无UI场景不提供，不修改上游对象。
    const cancelled = async () => ({ cancelled: true });
    await bounded(session.bindExtensions({ mode: caseId === "no-ui" ? "json" : "tui",
      ...(caseId === "no-ui" ? {} : { uiContext: syntheticUI(confirm) }),
      commandContextActions: { waitForIdle: () => session.waitForIdle(), newSession: cancelled, fork: cancelled,
        navigateTree: cancelled, switchSession: cancelled, reload: () => session.reload() },
      onError: () => { state.extension_errors++; } }));
    if (caseId === "unrelated-input") {
      nextTools = ["scope_leaf"];
      await bounded(session.prompt("synthetic unrelated objective", { expandPromptTemplates: false }));
    } else if (caseId === "settling-deferred") {
      nextTools = [];
      await bounded(session.prompt("synthetic first turn", { expandPromptTemplates: false }));
      await bounded(session.waitForIdle());
      assert(deferredRequested);
    } else {
      nextTools = caseId === "nested-follow-up" ? ["scope_nested", "scope_leaf"]
        : caseId === "canceled" ? ["scope_cancel"] : ["scope_leaf"];
      const command = session.prompt("/scope-probe synthetic confirmed objective");
      if (caseId === "async-late-resolve" || caseId === "async-late-reject") {
        await bounded(toolReady);
        assert.equal(state.request_allocations,1);
        scope.invalidate();
        // 只完成fake分配结果；不声称底层任务/SDK被物理取消。
        if(caseId === "async-late-resolve") lateResolve("c".repeat(32));
        else { const marker="SYNTHETIC_PRIVATE_ALLOCATION_ERROR"; lateReject(new Error(marker)); }
        state.async_late_results++;
      }
      if (caseId === "canceled") {
        await bounded(toolReady);
        scope.invalidate();
        await bounded(session.abort());
      }
      await bounded(command);
    }
    assert.equal(scope.bindingForTool("outside-run"), null);
    assert.equal(await scope.bindingForToolAsync("outside-run"), null);
    assert.equal(state.extension_errors, 0);
  } finally {
    scope.retire();
    await session.abort();
    session.dispose();
  }
}

async function main() {
  assert.equal(process.argv.length, 3);
  assert.equal(process.argv[2], "--native-intent-scope-probe");
  assert.deepEqual({ ...process.env }, environment);
  assert(process.execArgv.includes("--experimental-import-meta-resolve"));
  const sdk = await import(import.meta.resolve("@earendil-works/pi-coding-agent", "file:///candidate/package.json"));
  const ai = await import(import.meta.resolve("@earendil-works/pi-ai", "file:///candidate/package.json"));
  assert.equal(sdk.VERSION, "1.0.1");
  assert.equal(JSON.parse(fs.readFileSync("/candidate/node_modules/@earendil-works/pi-ai/package.json", "utf8")).version, "1.0.2");
  const { createConfirmedIntentScope } = await import("../agents/pi/runtime/confirmed-intent-scope.ts");
  for (const caseId of cases) await observeCase(result, caseId, state => runCase(caseId, sdk, ai, createConfirmedIntentScope, state));
  result.status = "observed";
}
let emitted = false;
function emit() {
  if (emitted) return;
  emitted = true;
  for (const caseId of cases) {
    if (!result.cases.some(value => value.case_id === caseId)) result.cases.push({ case_id: caseId, outcome: "not-run" });
  }
  try { fs.writeFileSync("/work/intent-scope-result.json", JSON.stringify(result) + "\n", { flag: "wx", mode: 0o600 }); }
  catch { result.status = "failed"; }
  process.stdout.write(JSON.stringify({ schema_version: 1, status: result.status, cases: result.cases.length, product_gate: false }) + "\n");
}
// 默认测试可只import纯记录函数；不触发SDK、环境读取、文件输出或watchdog。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const watchdog = setTimeout(() => { process.exitCode = 2; emit(); process.exit(2); }, 80000);
  try { await main(); }
  catch { result.status = "failed"; }
  finally { clearTimeout(watchdog); emit(); }
  process.exitCode = result.status === "observed" ? 0 : 2;
}
