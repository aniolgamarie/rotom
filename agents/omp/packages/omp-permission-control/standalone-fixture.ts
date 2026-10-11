import { createStandalonePlugin, type StandaloneConfig } from "./standalone";
import type { NativeBashRuntime, NativeSettingsSnapshot } from "./native-bash";
import type { LifecycleLimits } from "./approval-lifecycle";

const digest = "a".repeat(64);
export const baseConfig: StandaloneConfig = {
  schemaVersion: 2,
  defaultMode: "smart",
  reviewer: "session",
  pluginId: "omp-permission-control",
  pluginDigest: digest,
  policyVersion: digest,
  nativePatterns: [],
};

export function model(provider = "primary", id = "reviewer") {
  return { provider, id, api: "openai-completions", baseUrl: "https://invalid.test/v1",
    requestModelId: undefined };
}

export async function fakeHost(options: {
  config?: StandaloneConfig;
  loadConfig?: () => Promise<StandaloneConfig>;
  response?: object | Error;
  fetchImpl?: (input: string, init: RequestInit) => Promise<Response>;
  currentModel?: ReturnType<typeof model>;
  select?: string | undefined;
  hasUI?: boolean;
  messages?: unknown[];
  loadingActionsThrow?: boolean;
  nativeRuntime?: any;
  nativeLoadError?: boolean;
  invokeImpl?: (...args: any[]) => Promise<any>;
  appendFailure?: boolean;
  lifecycle?: Partial<LifecycleLimits>;
  execImpl?: (...args: any[]) => Promise<any>;
  selectImpl?: (...args: any[]) => Promise<string | undefined>;
} = {}) {
  const auditEntries: any[] = [];
  const tools = new Map<string, any>();
  const commands = new Map<string, any>();
  const events = new Map<string, any>();
  const execCalls: any[] = [];
  const fetchCalls: any[] = [];
  const selectCalls: any[] = [];
  const notices: string[] = [];
  const invokeCalls: any[] = [];
  let current = options.currentModel ?? model();
  let loading = true;
  const branch = options.messages ?? [{ type: "message", message: { role: "user", content: "Run ls -la", timestamp: 1 } }];
  const host: any = {
    typebox: { Type: {
      String: (value?: unknown) => ({ type: "string", ...value as object }),
      Number: (value?: unknown) => ({ type: "number", ...value as object }),
      Optional: (value: unknown) => value,
      Object: (properties: unknown, extra: unknown) => ({ properties, ...extra as object }),
    } },
    appendEntry: (type: string, data: unknown) => {
      if (options.appendFailure) throw new Error("SENSITIVE_CANARY_WRITER_ERROR");
      auditEntries.push({ type, data });
    },
    getAllTools: () => {
      if (loading && options.loadingActionsThrow) throw new Error("runtime not initialized");
      return [...tools.values()];
    },
    getActiveTools: () => {
      if (loading && options.loadingActionsThrow) throw new Error("runtime not initialized");
      return ["bash", "read"];
    },
    setActiveTools: async (names: string[]) => { host.active = names; },
    registerTool: (tool: any) => tools.set(tool.name, tool),
    registerCommand: (name: string, command: any) => commands.set(name, command),
    on: (name: string, handler: any) => events.set(name, handler),
    exec: async (...args: any[]) => { execCalls.push(args); if (options.execImpl) return options.execImpl(...args); return { stdout: "ok", stderr: "", code: 0, killed: false }; },
  };
  await createStandalonePlugin({
    loadConfig: options.loadConfig ?? (async () => options.config ?? baseConfig),
    lifecycle: options.lifecycle,
    fetch: (async (input: string, init: RequestInit) => {
      fetchCalls.push([input, init]);
      if (options.fetchImpl) return options.fetchImpl(input, init);
      if (options.response instanceof Error) throw options.response;
      return new Response(JSON.stringify(options.response ?? {
        choices: [{ message: { content: JSON.stringify({ decision: "allow", risk: "low",
          authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" }) } }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch,
    loadNativeRuntime: options.nativeLoadError ? async () => { throw new Error("fixture load failure"); } :
      options.nativeRuntime ? async () => options.nativeRuntime : undefined,
  })(host);
  loading = false;
  const ctx: any = {
    hasUI: options.hasUI ?? true,
    cwd: "/repo",
    ui: { select: async (...args: any[]) => { selectCalls.push(args); return options.selectImpl ? options.selectImpl(...args) : options.select; },
      notify: (message: string) => notices.push(message) },
    models: {
      current: () => current,
      resolve: (spec: string) => spec === `${current.provider}/${current.id}` ? current :
        spec === "remote/fallback" ? model("remote", "fallback") : undefined,
    },
    modelRegistry: { getApiKey: async () => "test-key" },
    sessionManager: { getBranch: () => branch, getSessionId: () => "session-1" },
    invokeTool: async (...args: any[]) => {
      invokeCalls.push(args);
      if (options.invokeImpl) return options.invokeImpl(...args);
      return { content: [{ type: "text", text: "native-ok" }], details: { native: true } };
    },
  };
  return { host, ctx, auditEntries, tools, commands, events, execCalls, fetchCalls, selectCalls, notices, invokeCalls,
    setCurrent: (value: any) => { current = value; } };
}

export async function ready(harness: Awaited<ReturnType<typeof fakeHost>>) {
  await harness.events.get("session_start")({}, harness.ctx);
  return harness.tools.get("permission_bash");
}

export function fakeNativeRuntime(initial: Partial<NativeSettingsSnapshot> = {}) {
  const settings = {};
  let fingerprint = initial.fingerprint ?? "settings-1";
  let decision = initial.decision ?? "allow";
  let reasonCode = initial.reasonCode ?? (decision === "deny" ? "NATIVE_DENY" : decision === "prompt" ? "NATIVE_PROMPT" : "NATIVE_ALLOW");
  let diagnostics = initial.diagnostics;
  let recheckWait: Promise<void> | undefined;
  let captureFailure = false;
  let recheckFailure = false;
  const snapshot = (): NativeSettingsSnapshot => ({ settings, fingerprint, decision, reasonCode,
    bindingSupported: initial.bindingSupported,
    diagnostics,
    reviewContext: initial.reviewContext ?? { sameSettingsInstance: true, nativeDecision: decision, shellContext: "standard" } });
  const runtime: NativeBashRuntime = {
    capture: async () => { if (captureFailure) throw new Error("fixture capture unavailable"); return snapshot(); },
    recheck: async () => {
      await recheckWait;
      if (recheckFailure) throw new Error("fixture recheck unavailable");
      return snapshot();
    },
  };
  return { runtime,
    setFingerprint: (value: string) => { fingerprint = value; },
    setDiagnostics: (value: NativeSettingsSnapshot["diagnostics"]) => { diagnostics = value; },
    setDecision: (value: NativeSettingsSnapshot["decision"], reason: NativeSettingsSnapshot["reasonCode"]) => {
      decision = value; reasonCode = reason;
    },
    setRecheckWait: (value: Promise<void> | undefined) => { recheckWait = value; },
    setCaptureFailure: () => { captureFailure = true; },
    setRecheckFailure: () => { recheckFailure = true; },
  };
}

export async function nativeReady(harness: Awaited<ReturnType<typeof fakeHost>>) {
  await ready(harness);
  const hook = harness.events.get("tool_call");
  const dispatch = async (event: any, ctx = harness.ctx, signal?: AbortSignal) => {
    const result = await hook(event, ctx);
    if (result?.block) return { isError: true, details: { reasonCode: result.reason }, hookResult: result };
    return harness.tools.get(event.toolName).execute(event.toolCallId, event.input, signal, undefined, ctx);
  };
  return { tool: harness.tools.get("bash"), hook, dispatch };
}
