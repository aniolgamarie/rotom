// 仓库拥有准入与生命周期组合；只调用官方SDK公开接口，不改写原生对象或原型。
import { createOfficialSessionFactory } from "./official-session.ts";
import { createOfficialFileAdmission, createOfficialShellAdmission } from "./official-file-admission.ts";
import { createOfficialShellTool } from "./official-shell-tool.ts";
import { OrdinaryOperations } from "./ordinary-operations.ts";
import { clone, reject } from "./managed-types.ts";
import { detectImageMimeType } from "./image-mime.ts";
import { createOfficialMcpController } from "./official-mcp-controller.ts";

const fileNames = ["read", "write", "edit", "rename", "ls", "find", "grep"];
const immutable = value => {
  if (value && typeof value === "object") { Object.values(value).forEach(immutable); Object.freeze(value); }
  return value;
};

// 固定1.0.1根公开AgentSession成员；仅为自有前端视图，不修改原对象/原型。
// export/share等独立前端IO不能借模型工具白名单获得写权限；这里先关闭两个公开导出入口。
const sessionProperties = [
  "agent", "sessionManager", "settingsManager", "modelRuntime", "state", "cacheWarmingStatus",
  "model", "thinkingLevel", "routedModel", "isStreaming", "isIdle", "systemPrompt",
  "retryAttempt", "isCompacting", "messages", "steeringMode", "followUpMode", "sessionFile",
  "sessionId", "sessionName", "scopedModels", "promptTemplates", "pendingMessageCount", "resourceLoader",
  "autoCompactionEnabled", "isRetrying", "autoRetryEnabled", "isBashRunning", "hasPendingBashMessages", "extensionRunner"
];
const sessionMethods = [
  "subscribe", "dispose", "refreshContext", "setCacheWarmingMode", "getActiveToolNames", "getCallableToolNames",
  "getAllTools", "getToolDefinition", "setActiveToolsByName", "setScopedModels", "prompt", "steer",
  "followUp", "sendCustomMessage", "sendUserMessage", "clearQueue", "getSteeringMessages", "getFollowUpMessages",
  "abort", "waitForIdle", "setModel", "cycleModel", "setThinkingLevel", "cycleThinkingLevel",
  "getAvailableThinkingLevels", "supportsThinking", "setSteeringMode", "setFollowUpMode", "compact", "abortCompaction",
  "abortBranchSummary", "setAutoCompactionEnabled", "bindExtensions", "reload", "abortRetry", "setAutoRetryEnabled",
  "executeBash", "recordBashResult", "abortBash", "setSessionName", "navigateTree", "getUserMessagesForForking",
  "getSessionStats", "getContextUsage", "summarizeForBugReport", "getLastAssistantText", "createReplacedSessionContext", "hasExtensionHandlers"
];
function sessionView(session, views, boundaries, resourceHooks) {
  if (!session || typeof session !== "object") reject("PI_SESSION_SDK_INCOMPATIBLE", 5);
  let view = views.get(session);
  if (view) return view;
  view = Object.create(null);
  for (const name of sessionProperties) Object.defineProperty(view, name, { enumerable: true, get: () => session[name] });
  for (const name of sessionMethods) Object.defineProperty(view, name, { enumerable: true, value: (...args) => {
    if (typeof session[name] !== "function") reject("PI_SESSION_SDK_INCOMPATIBLE", 5);
    const boundary = boundaries.get(session);
    const verifyFrontend = () => {
      if (!boundary || boundary.ready !== true || boundary.sessionId !== session.sessionManager?.getSessionId?.()) {
        reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
      }
    };
    // SDK可能记录并吞掉extension错误；成功返回不证明防护editor真的安装。
    const frontend = (name === "bindExtensions" && args[0]?.mode === "tui") || (name === "reload" && boundary?.mode === "tui");
    const observation = resourceHooks?.get(session);
    if (frontend || observation && (name === "bindExtensions" || name === "reload")) {
      if (frontend && boundary) boundary.ready = false;
      return (async () => {
        await observation?.before();
        const value = await session[name](...args);
        if (frontend) verifyFrontend();
        await observation?.after();
        return value;
      })();
    }
    return session[name](...args);
  } });
  for (const name of ["exportToHtml", "exportToJsonl"]) Object.defineProperty(view, name, { enumerable: true,
    value: () => reject("PI_EXPORT_ADMISSION_UNAVAILABLE", 5) });
  Object.freeze(view); views.set(session, view); return view;
}

function denyUserBash() { reject("PI_COMMAND_ADMISSION_UNAVAILABLE", 5); }
function commandBoundary(pi, sdk, boundary) {
  // noTools仅控制模型工具；直接用户Bash仍拒绝，TUI提交另经公开editor factory。
  pi.on("user_bash", denyUserBash);
  let detach;
  // shutdown可能仍有后续异步handler；不能提前移除仍在使用的TUI输入保护。
  // 原TUI在beforeSessionInvalidate重置时负责清除此公开UI listener。
  pi.on("session_shutdown", () => { boundary.ready = false; });
  pi.on("session_start", (_event, ctx) => {
    boundary.ready = false; boundary.mode = ctx.mode; boundary.sessionId = ctx.sessionManager?.getSessionId?.();
    if (ctx.mode !== "tui") return;
    if (typeof sdk.CustomEditor !== "function" || typeof ctx.ui?.setEditorComponent !== "function"
        || typeof ctx.ui?.onTerminalInput !== "function" || typeof ctx.ui?.notify !== "function") reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
    const deny = () => ctx.ui.notify("此入口尚未接入受管权限，当前不可用。", "warning");
    ctx.ui.setEditorComponent((tui, theme, keybindings) => {
      const editor = new sdk.CustomEditor(tui, theme, keybindings), view = Object.create(null);
      let submit;
      const guardedSubmit = text => {
        if (typeof text !== "string") reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
        // 与原TUI trim后的分发一致；路径/参数不改变这些原生直接IO入口的禁用。
        if (/^\/(?:export|share|bug|debug|copy)(?:\s|$)/u.test(text.trim())) { deny(); return; }
        return submit?.(text);
      };
      Object.defineProperty(view, "onSubmit", { get: () => guardedSubmit, set: callback => {
        if (callback !== undefined && typeof callback !== "function") reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
        submit = callback;
      } });
      // onSubmit是公开可配置callback；这里为新建editor配置它，不改SDK实现/原型。
      editor.onSubmit = guardedSubmit;
      for (const name of ["render", "invalidate", "handleInput", "getText", "setText", "getExpandedText", "addToHistory",
        "insertTextAtCursor", "setAutocompleteProvider", "setPaddingX", "setAutocompleteMaxVisible", "setWorkingStatusIndicator"]) {
        if (typeof editor[name] === "function") Object.defineProperty(view, name, { value: (...args) => editor[name](...args) });
      }
      for (const name of ["onChange", "borderColor", "focused", "onEscape", "onCtrlD", "onExtensionShortcut"]) {
        Object.defineProperty(view, name, { get: () => editor[name], set: value => { editor[name] = value; } });
      }
      for (const name of ["actionHandlers", "embedWorkingStatus"]) Object.defineProperty(view, name, { get: () => editor[name] });
      Object.defineProperty(view, "onPasteImage", { value: deny }); editor.onPasteImage = deny;
      if (typeof keybindings?.matches !== "function") reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
      const nextDetach = ctx.ui.onTerminalInput(data => {
        if (["app.editor.external", "app.clipboard.pasteImage", "app.message.copy"].some(action => keybindings.matches(data, action))
            || typeof data === "string" && data.includes("\x1b[<")) {
          // 鼠标事件也会触发独立复制/右键剪贴板路径；此候选只开放键盘操作。
          deny(); return { consume: true };
        }
        return undefined;
      });
      if (typeof nextDetach !== "function") reject("PI_FRONTEND_BOUNDARY_UNAVAILABLE", 5);
      detach?.(); detach = nextDetach;
      boundary.ready = true;
      return view;
    });
  });
}

export async function createOfficialFileRuntime(options, target) {
  const { sdk, supervisor, policySnapshot } = options;
  if (typeof sdk?.createAgentSessionRuntime !== "function" || typeof policySnapshot !== "function"
      || typeof supervisor?.call !== "function") reject("PI_SESSION_SDK_INCOMPATIBLE", 5);
  const manifest = immutable(clone(options.manifest)), owner = immutable(clone(options.owner));
  const fixed = { ...options, manifest, installed: immutable(clone(options.installed)),
    commandGuard: Object.freeze({ name: "rotom-command-boundary", handler: denyUserBash }),
    extensionFactories: (options.extensionFactories ?? []).map(value => ({ ...value })) };
  let active = null, busy = false, disposed = false, beforeInvalidate, disposal;
  const sessionViews = new WeakMap(), frontendBoundaries = new WeakMap(), resourceHooks = new WeakMap();
  const observationsEnabled = fixed.installed.schema_version === 2 && ["pi-base", "pi-full"].includes(manifest.profile_id);
  let observationGeneration = 0;
  const cleanups = new Set();
  let cleanupFailed = false;
  const retire = () => {
    if (!active) return;
    const current = active; active = null;
    // retire同步本地关闭所有旧工具；RPC失败保留为drain错误，不妨碍先关闭其他本地入口。
    current.retire();
    const pending = current.drain().catch(() => { cleanupFailed = true; }).finally(() => cleanups.delete(pending));
    cleanups.add(pending);
  };
  const drain = async () => {
    while (cleanups.size) await Promise.all([...cleanups]);
    if (cleanupFailed) reject("OPERATION_RETIRE_INCOMPLETE", 4);
  };
  const observationAck = (value, generation) => {
    if (!value || typeof value !== "object" || Object.keys(value).sort().join() !== "accepted,generation,schema_version"
        || value.schema_version !== 1 || value.accepted !== true || value.generation !== generation) reject("RESOURCE_OBSERVATION_INVALID", 4);
  };
  const retireObservation = current => {
    if (!observationsEnabled || !current.observation) return Promise.resolve();
    if (current.metadataRetirement) return current.metadataRetirement;
    const captured = current.observation;
    current.metadataRetirement = (async () => {
      let publicationError;
      try { await current.publication; } catch (error) { publicationError = error; }
      try {
        const reply = await supervisor.call("diagnostic_resource_observation", { kind: "retired",
          session_id: captured.sessionId, generation: captured.generation });
        observationAck(reply, captured.generation);
      } finally {
        // 权限/传输错误保持失败；成功retire也不能把原publication拒绝变成功。
        if (publicationError) throw publicationError;
      }
    })();
    return current.metadataRetirement;
  };
  const publishObservation = async current => {
    if (!observationsEnabled) return;
    if (disposed || current !== active || current.retired || !current.session || native.session !== current.session) reject("RESOURCE_OBSERVATION_STALE", 4);
    if (current.metadataRetirement) await current.metadataRetirement;
    if (current.publication) await current.publication;
    const sessionId = current.sessionManager.getSessionId();
    const snapshot = await current.resourceSnapshot();
    if (disposed || current !== active || current.retired || native.session !== current.session
        || current.sessionManager.getSessionId() !== sessionId) reject("RESOURCE_OBSERVATION_STALE", 4);
    const generation = ++observationGeneration;
    if (!Number.isSafeInteger(generation)) reject("RESOURCE_OBSERVATION_INVALID", 4);
    current.observation = { sessionId, generation }; current.metadataRetirement = null;
    current.publication = Promise.resolve().then(() => supervisor.call("diagnostic_resource_observation",
      { kind: "loaded", session_id: sessionId, generation, snapshot }));
    const reply = await current.publication; observationAck(reply, generation);
    if (disposed || current !== active || current.retired || native.session !== current.session
        || current.sessionManager.getSessionId() !== sessionId) reject("RESOURCE_OBSERVATION_STALE", 4);
  };
  const createSession = async sessionTarget => {
    // 官方替换流程已先触发退役回调；首次调用无active，旁路重复工厂调用也不能复活旧工具。
    retire();
    if (disposed) reject("PI_SESSION_RETIRED", 4);
    const { cwd, sessionManager } = sessionTarget;
    const frontendBoundary = { ready: false, mode: null, sessionId: null };
    let snapshot,modelDescriptions;
    const admissionOptions = { supervisor, owner, manifest, cwd, sessionManager,
      configurationSnapshot: async () => {
        if (!snapshot) reject("PI_SESSION_NOT_READY", 4);
        return snapshot();
      }, policySnapshot: () => policySnapshot(cwd, sessionManager) };
    const admission = createOfficialFileAdmission(admissionOptions);
    const shellAdmission = Object.hasOwn(manifest.options?.external_tools ?? {}, "shell")
      ? createOfficialShellAdmission(admissionOptions) : null;
    const admissions = [admission, ...(shellAdmission ? [shellAdmission] : [])];
    let mcp, delegate, taskKeeper;
    const current = {
      session: null, resourceSnapshot: null, sessionManager, observation: null, publication: null, metadataRetirement: null,
      retired: false,
      retire() { this.retired = true; admissions.forEach(controller => controller.retire()); mcp?.retire(); delegate?.retire(); taskKeeper?.retire(); },
      async drain() {
        // 任一清理失败也等全部已发清理完成，不能在另一个控制器仍有请求时返回。
        const results = await Promise.allSettled([retireObservation(current), ...admissions.map(controller => controller.drain()), ...(mcp ? [mcp.close()] : []), ...(delegate ? [delegate.drain()] : []), ...(taskKeeper ? [taskKeeper.close()] : [])]);
        if (results.some(result => result.status === "rejected")) reject("OPERATION_RETIRE_INCOMPLETE", 4);
      },
    };
    active = current;
    try {
      if (manifest.native_mcp) {
        const runtime = { owner, manifest, installed: fixed.installed, supervisor, instanceRoot: fixed.instanceRoot,
          runtimeRoot: fixed.runtimeRoot, managedRequestScope: options.managedRequestScope };
        mcp = await createOfficialMcpController({ sdk, runtime, admissionOptions, checkDeployment: () => policySnapshot(cwd, sessionManager) });
      }
      const ordinary = new OrdinaryOperations(sdk, { supervisor, manifest, instanceRoot: fixed.instanceRoot }, { fileAdmission: admission, mime: detectImageMimeType });
      const toolDefinitions = ordinary.tools(cwd, "main", { filesOnly: true });
      if (toolDefinitions.length !== fileNames.length || fileNames.some(name => !toolDefinitions.some(tool => tool.name === name))) {
        reject("PI_SESSION_FILE_TOOLS_INCOMPLETE", 5);
      }
      if (manifest.profile_id === "pi-full" && manifest.plugins?.includes("model-delegate")
          && manifest.plugin_capabilities?.["model-delegate"]?.capability_id === "unified-delegate") {
        const { createOfficialDelegate } = await import("./official-delegate.ts");
        delegate = createOfficialDelegate({ manifest, supervisor, sessionManager,
          configurationSnapshot: admissionOptions.configurationSnapshot, policySnapshot: () => policySnapshot(cwd, sessionManager) });
        toolDefinitions.push(delegate.tool);
      }
      if (manifest.profile_id === "pi-full" && manifest.plugins?.includes("task-keeper")
          && manifest.plugin_capabilities?.["task-keeper"]?.capability_id === "task-workflow"
          && manifest.options.task_keeper?.enabled === true) {
        const { createOfficialTaskKeeper } = await import("./official-task-keeper.ts");
        taskKeeper = createOfficialTaskKeeper({ manifest, installed: fixed.installed, runtimeRoot: fixed.runtimeRoot,
          instanceRoot: fixed.instanceRoot, cwd, sessionManager, supervisor, issuer: options.taskKeeperIssuer,
          configurationSnapshot: admissionOptions.configurationSnapshot,
          semanticModelDescriptions: async()=>{if(!modelDescriptions)reject("PI_SESSION_NOT_READY",4);return modelDescriptions();},
          policySnapshot: () => policySnapshot(cwd, sessionManager) });
        toolDefinitions.push(taskKeeper.tool);
      }
      if (shellAdmission) toolDefinitions.push(createOfficialShellTool({ sdk, cwd, admission: shellAdmission, supervisor }));
      const result = await createOfficialSessionFactory({ ...fixed, toolDefinitions,
        extensionFactories: [{ name: "rotom-command-boundary", factory: pi => commandBoundary(pi, sdk, frontendBoundary) },
          ...fixed.extensionFactories, ...(mcp?.extensionFactories ?? []), ...(taskKeeper ? [{ name: "rotom-task-keeper", factory: taskKeeper.factory }] : [])], nativeMcp: mcp })(sessionTarget);
      snapshot = result.configurationSnapshot;modelDescriptions=result.semanticModelDescriptions;
      // 仅登记于本次自有记录；SDK不需要保留工厂custom返回字段。
      current.session = result.session;
      frontendBoundaries.set(result.session, frontendBoundary);
      current.resourceSnapshot = result.resourceSnapshot;
      if (observationsEnabled) resourceHooks.set(result.session, {
        before: () => retireObservation(current),
        after: () => busy ? undefined : publishObservation(current),
      });
      return result;
    } catch (error) { retire(); throw error; }
  };
  let native;
  try {
    native = await sdk.createAgentSessionRuntime(createSession, target);
    native.setBeforeSessionInvalidate(() => {
      retire();
      // UI回调仍保留官方异常语义；仓库准入总是在UI执行前已同步退役。
      beforeInvalidate?.();
    });
    await publishObservation(active);
  } catch (error) { retire(); await drain(); throw error; }
  const transition = async (method, args) => {
    if (disposed) reject("PI_SESSION_RETIRED", 4);
    if (busy) reject("PI_SESSION_TRANSITION_BUSY", 4);
    busy = true;
    try {
      const value = await native[method](...args);
      busy = false;
      await publishObservation(active);
      return value;
    } catch (error) {
      retire();
      await drain();
      throw error;
    } finally { busy = false; }
  };
  // TUI会设置自己的beforeSessionInvalidate；用自有公开facade组合它，不能覆盖准入退役。
  // 原始runtime只在闭包内；这里不修改它的任何方法，也不访问私有字段。
  return Object.freeze({
    get session() { return sessionView(native.session, sessionViews, frontendBoundaries, resourceHooks); },
    get services() { return native.services; },
    get cwd() { return native.cwd; },
    get diagnostics() { return native.diagnostics; },
    get modelFallbackMessage() { return native.modelFallbackMessage; },
    setBeforeSessionInvalidate(callback) {
      if (callback !== undefined && typeof callback !== "function") reject("PI_SESSION_CALLBACK_INVALID", 2);
      beforeInvalidate = callback;
    },
    setRebindSession(callback) {
      if (callback !== undefined && typeof callback !== "function") reject("PI_SESSION_CALLBACK_INVALID", 2);
      native.setRebindSession(callback === undefined ? undefined : session => callback(sessionView(session, sessionViews, frontendBoundaries, resourceHooks)));
    },
    switchSession(...args) { return transition("switchSession", args); },
    newSession(...args) { return transition("newSession", args); },
    fork(...args) { return transition("fork", args); },
    importFromJsonl(...args) { return transition("importFromJsonl", args); },
    async resourceSnapshot() {
      if (disposed) reject("PI_SESSION_RETIRED", 4);
      if (busy) reject("PI_SESSION_TRANSITION_BUSY", 4);
      const current = active;
      if (!current?.session || typeof current.resourceSnapshot !== "function") reject("PI_SESSION_NOT_READY", 4);
      const sameCurrent = () => {
        if (disposed || busy || active !== current) return false;
        try { return native.session === current.session; }
        catch { return false; }
      };
      if (!sameCurrent()) reject("PI_SESSION_RESOURCE_STALE", 4);
      try { return await current.resourceSnapshot(); }
      finally {
        // 成功/失败均重验；失效覆盖旧快照或旧错误，不改变retire/drain顺序。
        if (!sameCurrent()) reject("PI_SESSION_RESOURCE_STALE", 4);
      }
    },
    async dispose() {
      if (disposal) return disposal;
      if (busy) reject("PI_SESSION_TRANSITION_BUSY", 4);
      disposed = true;
      retire();
      // 官方runtime.dispose本身不先abort；退出必须把取消交给仍在执行的原生工具signal。
      disposal = (async () => {
        try { await native.session.abort(); await native.dispose(); }
        finally { await drain(); }
      })();
      return disposal;
    },
    drain,
  });
}
