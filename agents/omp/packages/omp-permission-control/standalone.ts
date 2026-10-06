import { lstat, readFile } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { hasUncertainPatternMatch, matchesNativePattern, matchesNativeRaw, parseGenericCommands, privacyWords, visiblePrefixForDenial } from "./standalone-shell-analysis";
import { loadNativeBashRuntime, type NativeBashRuntime, type NativeSettingsSnapshot,
  type PlainBashParams, type NativeDiagnostics, SHELL_FAMILIES, CONTEXT_REASONS } from "./native-bash";
import { parseStandaloneJson, reviewCommand, type ReviewAttempt, type ReviewRuntime, type ReviewTarget,
  type ReviewerModel, type ReviewSequenceResult } from "./standalone-reviewer";

type Mode = "smart" | "manual";
type Approval = "allow" | "prompt" | "deny";
type DecisionSource = "primary" | "remote" | "human" | "native" | "none";

export interface StandaloneConfig {
  schemaVersion: 2;
  defaultMode: Mode;
  reviewer: "session" | ReviewTarget;
  remoteFallback?: ReviewTarget;
  fallback?: { provider: "local"; model: "lfm2.5-230m"; installedOnly: true };
  pluginId: "omp-permission-control";
  pluginDigest: string;
  policyVersion: string;
  nativePatterns: Array<{ match: string; approval: Approval }>;
  nativeBash?: boolean;
}

interface LayerState {
  configured: string;
  actualModel?: string;
  calls: number;
  health: "idle" | "ready" | "unavailable" | "unsupported" | "transport" | "invalid" | "cancelled" | "timeout";
}

interface State {
  mode: Mode;
  generation: number;
  pending: Set<AbortController>;
  primary: LayerState;
  remote: LayerState;
  human: { calls: number; health: "idle" | "approved" | "denied" | "unavailable" };
  native: { calls: number; delegateCalls: number; delegateAvailable: boolean | null;
    scopedSettingsReady: boolean; coverage: "disabled" | "initializing" | "limited" | "ready" | "unavailable";
    unsupported: string[]; diagnostics?: NativeDiagnostics };
  last: { outcome: string; source: DecisionSource; reasonCode: string;
    chain: Array<"primary" | "remote" | "human" | "native"> };
}

export interface StandaloneDependencies {
  loadConfig?: () => Promise<StandaloneConfig>;
  fetch?: typeof fetch;
  loadNativeRuntime?: () => Promise<NativeBashRuntime>;
}

interface ApprovalOutcome {
  approved: boolean;
  source: DecisionSource;
  reasonCode: string;
  chain: State["last"]["chain"];
}

interface NativeTicket {
  signature: string;
  generation: number;
  mode: Mode;
  sessionId: string;
  model: string;
  baseCwd: string;
  settings: object;
  fingerprint: string;
  nativeDecision: NativeSettingsSnapshot["decision"];
}

const HEX64 = /^[0-9a-f]{64}$/u;
const CONFIG_KEYS = new Set(["schemaVersion", "defaultMode", "reviewer", "remoteFallback", "fallback",
  "pluginId", "pluginDigest", "policyVersion", "nativePatterns", "nativeBash"]);
const TARGET_KEYS = new Set(["provider", "model"]);
const PLAIN_BASH_KEYS = new Set(["command", "cwd", "timeout"]);

function exactKeys(value: unknown, allowed: Set<string>): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every(key => allowed.has(key));
}

function target(value: unknown): value is ReviewTarget {
  return exactKeys(value, TARGET_KEYS) && Object.keys(value).length === 2 &&
    typeof value.provider === "string" && value.provider.length > 0 &&
    typeof value.model === "string" && value.model.length > 0;
}

export function validateStandaloneConfig(value: unknown): StandaloneConfig {
  if (!exactKeys(value, CONFIG_KEYS) || value.schemaVersion !== 2 ||
      (value.defaultMode !== "smart" && value.defaultMode !== "manual") ||
      !(value.reviewer === "session" || target(value.reviewer)) ||
      (value.remoteFallback !== undefined && !target(value.remoteFallback)) ||
      (value.nativeBash !== undefined && typeof value.nativeBash !== "boolean") ||
      value.pluginId !== "omp-permission-control" || !HEX64.test(String(value.pluginDigest)) ||
      !HEX64.test(String(value.policyVersion)) || !Array.isArray(value.nativePatterns))
    throw new Error("invalid permission-control configuration");
  if (value.fallback !== undefined && (!exactKeys(value.fallback, new Set(["provider", "model", "installedOnly"])) ||
      Object.keys(value.fallback).length !== 3 || value.fallback.provider !== "local" ||
      value.fallback.model !== "lfm2.5-230m" || value.fallback.installedOnly !== true))
    throw new Error("invalid permission-control configuration");
  for (const pattern of value.nativePatterns) {
    if (!exactKeys(pattern, new Set(["match", "approval"])) || Object.keys(pattern).length !== 2 ||
        typeof pattern.match !== "string" || pattern.match.length === 0 ||
        !["allow", "prompt", "deny"].includes(String(pattern.approval)))
      throw new Error("invalid permission-control configuration");
  }
  return value as unknown as StandaloneConfig;
}

export async function loadStandaloneConfig(): Promise<StandaloneConfig> {
  const { getAgentDir } = await import("@oh-my-pi/pi-coding-agent");
  const path = join(getAgentDir(), "permission-control.json");
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("invalid permission-control configuration");
  return validateStandaloneConfig(parseStandaloneJson(await readFile(path, "utf8"), 64 * 1024));
}

function textResult(text: string, details: Record<string, unknown> = {}, isError = false) {
  return { content: [{ type: "text" as const, text }], details, ...(isError ? { isError: true } : {}) };
}

function boundedOutput(value: string): string {
  const limit = 64 * 1024;
  const encoded = new TextEncoder().encode(value);
  return encoded.length <= limit ? value : `${new TextDecoder().decode(encoded.slice(0, limit))}\n[output truncated]`;
}

function userMessages(ctx: ExtensionContext): string[] {
  const messages: string[] = [];
  for (const entry of ctx.sessionManager.getBranch()) {
    if (entry.type !== "message" || entry.message.role !== "user" || entry.message.synthetic ||
        entry.message.attribution === "agent") continue;
    const content = entry.message.content;
    const text = typeof content === "string" ? content : content
      .filter(part => part.type === "text").map(part => part.text).join("\n");
    if (text) messages.push(text);
  }
  return messages;
}

const SECRET_FIELD = "(?:(?:token|password|passwd|secret|api[_-]?key|credential|authorization|cookie)[A-Za-z0-9_-]*)";
const SECRET_VALUE = "(?:'[^'\\n]*'|\"[^\"\\n]*\"|[^\\s;&|<>]+)+";

function containsSensitiveText(command: string, cwd: string, messages: string[]): boolean {
  const raw = [command, cwd, ...messages].join("\n");
  const text = raw + "\n" + privacyWords(raw).map(t => t.value).join(" ");
  return new RegExp(SECRET_FIELD + "[\"']?\\s*[:=]\\s*\\S+|--[A-Za-z0-9_-]*" + SECRET_FIELD + "\\s+\\S+", "iu").test(text) ||
    /\b(?:Bearer|Basic)\s+\S+|[A-Za-z][A-Za-z0-9+.-]*:\/\/[^\s/"'<>]+@/iu.test(text) ||
    (/\bcurl\b/u.test(text) && /(?<![\w-])(?:--(?:user|proxy-user|oauth2-bearer)(?:=|\s+)|-[uU]\s*)\S+/u.test(text)) ||
    /\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b/u.test(text);
}

function configuredNativeApproval(config: StandaloneConfig, command: string): Approval | "unsupported" {
  // 硬拒绝不能因后续语法不支持而降成可手工覆盖的提示。
  if (config.nativePatterns.some(p => p.approval === "deny" && matchesNativeRaw(command, p.match))) return "deny";
  const parsed = parseGenericCommands(command);
  if (parsed.status !== "complete") {
    const denies = config.nativePatterns.filter(p => p.approval === "deny");
    if (denies.length && visiblePrefixForDenial(command).some(c => denies.some(p => matchesNativePattern(c, p.match) || hasUncertainPatternMatch(c, p.match)))) return "deny";
    return "unsupported";
  }
  let result: Approval = "allow";
  for (const simple of parsed.commands) {
    for (const pattern of config.nativePatterns) {
      if (!matchesNativePattern(simple, pattern.match) && !matchesNativeRaw(command, pattern.match)) {
        if (pattern.approval !== "allow" && hasUncertainPatternMatch(simple, pattern.match)) {
          if (pattern.approval === "deny") return "deny";
          result = "prompt";
        }
        continue;
      }
      if (pattern.approval === "deny") return "deny";
      if (pattern.approval === "prompt") result = "prompt";
    }
  }
  return result;
}

function redactSensitive(value: string): string {
  const words = privacyWords(value);
  const curl = /\bcurl\b/u.test(value);
  for (let i = words.length-1; i >= 0; i--) {
    const word = words[i];
    const previous = words[i-1]?.value ?? "";
    const credentialFlag = (curl && /^--(?:user|proxy-user|oauth2-bearer)$|^-[uU]$/u.test(previous)) ||
      new RegExp("^--[A-Za-z0-9_-]*" + SECRET_FIELD + "$", "iu").test(previous) || /^(?:Bearer|Basic)$/iu.test(previous);
    const foldedSensitive = word.raw !== word.value && (containsSensitiveText(word.value, "", []) ||
      (curl && /^(?:-[uU]|--(?:user|proxy-user|oauth2-bearer)=).+/u.test(word.value)));
    if (credentialFlag || foldedSensitive)
      value = value.slice(0, word.start) + (word.raw.startsWith("#") ? "# [REDACTED]" : "[REDACTED]") + value.slice(word.end);
  }
  return value
    .replace(new RegExp("((?:-H|--header)\\s+)" + SECRET_VALUE, "gu"), "$1[REDACTED]")
    .replace(new RegExp("(\\b(?:Bearer|Basic)\\s+)" + SECRET_VALUE, "giu"), "$1[REDACTED]")
    .replace(/([A-Za-z][A-Za-z0-9+.-]*:\/\/)[^\s/"'<>]+@/gu, "$1[REDACTED]@")
    .replace(new RegExp(curl ? "((?<![\\w-])(?:--(?:user|proxy-user|oauth2-bearer)(?:=|\\s+)|-[uU]\\s*))" + SECRET_VALUE : "(?!)", "gu"), "$1[REDACTED]")
    .replace(new RegExp("(" + SECRET_FIELD + "[\"']?\\s*[:=]\\s*)" + SECRET_VALUE, "giu"), "$1[REDACTED]")
    .replace(new RegExp("(--[A-Za-z0-9_-]*" + SECRET_FIELD + "\\s+)" + SECRET_VALUE, "giu"), "$1[REDACTED]")
    .replace(/\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b/gu, "[REDACTED]");
}

async function humanApprove(ctx: ExtensionContext, toolName: string, command: string, cwd: string,
  reasonCode: string, signal?: AbortSignal, contextReason?: NativeDiagnostics["contextReason"]): Promise<boolean> {
  if (!ctx.hasUI || signal?.aborted) return false;
  try {
    const title = `Allow ${toolName}?\nreason: ${reasonCode}\n` +
      (contextReason ? `context: ${contextReason}\n` : "") + `cwd: ${JSON.stringify(redactSensitive(cwd))}\n` +
      `command: ${JSON.stringify(redactSensitive(command))}`;
    return await ctx.ui.select(title, ["Approve", "Deny"], { signal }) === "Approve";
  } catch {
    return false;
  }
}

function nativeDiagnostics(snapshot: NativeSettingsSnapshot | undefined): NativeDiagnostics | undefined {
  const value = snapshot?.diagnostics;
  if (!value || !SHELL_FAMILIES.includes(value.shellFamily) ||
      !["local-embedded", "unverified"].includes(value.executionRoute) ||
      !CONTEXT_REASONS.includes(value.contextReason)) return undefined;
  return { shellFamily: value.shellFamily, executionRoute: value.executionRoute, contextReason: value.contextReason };
}

function configuredTarget(value: "session" | ReviewTarget | undefined): string {
  if (!value) return "disabled";
  return value === "session" ? "session" : `${value.provider}/${value.model}`;
}

function attemptState(configured: string, attempt: ReviewAttempt | undefined): LayerState {
  if (!attempt) return { configured, calls: 0, health: configured === "disabled" ? "unavailable" : "idle" };
  return { configured, actualModel: attempt.model ? `${attempt.model.provider}/${attempt.model.id}` : undefined,
    calls: attempt.called ? 1 : 0, health: attempt.status === "valid" ? "ready" : attempt.health };
}

function recordReview(state: State, config: StandaloneConfig, result: ReviewSequenceResult):
  Array<"primary" | "remote"> {
  const primary = attemptState(configuredTarget(config.reviewer), result.primary);
  state.primary = { ...primary, calls: state.primary.calls + primary.calls };
  if (result.remote) {
    const remote = attemptState(configuredTarget(config.remoteFallback), result.remote);
    state.remote = { ...remote, calls: state.remote.calls + remote.calls };
  }
  return ["primary", ...(result.remote ? ["remote" as const] : [])];
}

function modelIdentity(model: { provider: string; id: string } | undefined): string {
  return model ? `${model.provider}/${model.id}` : "unavailable";
}

function abortPending(state: State): void {
  for (const controller of state.pending) controller.abort();
  state.pending.clear();
}

function reviewRuntime(ctx: ExtensionContext, fetchImpl: typeof fetch): ReviewRuntime {
  const adapt = (model: ReturnType<typeof ctx.models.current>): ReviewerModel | undefined => model && ({
    provider: model.provider, id: model.id, api: model.api, baseUrl: model.baseUrl,
    requestModelId: model.requestModelId,
  });
  return {
    current: () => adapt(ctx.models.current()), resolve: spec => adapt(ctx.models.resolve(spec)),
    getApiKey: async (model, signal) => {
      const resolved = ctx.models.resolve(`${model.provider}/${model.id}`);
      return resolved ? ctx.modelRegistry.getApiKey(resolved, ctx.sessionManager.getSessionId(), { signal }) : undefined;
    },
    fetch: (input, init) => fetchImpl(input, init),
  };
}

function plainBashParams(value: unknown): PlainBashParams | undefined {
  if (!exactKeys(value, PLAIN_BASH_KEYS) || typeof value.command !== "string" || value.command.length === 0 ||
      (value.cwd !== undefined && typeof value.cwd !== "string") ||
      (value.timeout !== undefined && (typeof value.timeout !== "number" || !Number.isFinite(value.timeout) ||
        value.timeout < 0))) return undefined;
  return value as unknown as PlainBashParams;
}

function signature(params: PlainBashParams): string {
  return JSON.stringify({ command: params.command, cwd: params.cwd ?? null, timeout: params.timeout ?? null });
}

function effectiveCwd(baseCwd: string, requested: string | undefined): string | undefined {
  if (!requested) return baseCwd;
  if (/^[a-z][a-z0-9+.-]*:\/\//iu.test(requested)) return undefined;
  return isAbsolute(requested) ? requested : resolve(baseCwd, requested);
}

export function createStandalonePlugin(dependencies: StandaloneDependencies = {}) {
  return async function standalonePermissionControl(omp: ExtensionAPI): Promise<void> {
    const load = dependencies.loadConfig ?? loadStandaloneConfig;
    let initialConfig: StandaloneConfig | undefined;
    let nativeRuntime: NativeBashRuntime | undefined;
    let nativeLoadFailed = false;
    try {
      initialConfig = await load();
      if (initialConfig.nativeBash === true) {
        try { nativeRuntime = await (dependencies.loadNativeRuntime ?? loadNativeBashRuntime)(); }
        catch { nativeLoadFailed = true; }
      }
    } catch { initialConfig = undefined; }
    const nativeRegistered = initialConfig?.nativeBash === true && nativeRuntime !== undefined;
    let config: StandaloneConfig | undefined;
    const tickets = new Map<string, NativeTicket>();
    const rawCaptures = new Map<string, NativeTicket>();
    const seenToolCallIds = new Set<string>();
    const state: State = {
      mode: "manual", generation: 0, pending: new Set(),
      primary: { configured: "unavailable", calls: 0, health: "unavailable" },
      remote: { configured: "disabled", calls: 0, health: "unavailable" },
      human: { calls: 0, health: "idle" },
      native: { calls: 0, delegateCalls: 0, delegateAvailable: null, scopedSettingsReady: false,
        coverage: initialConfig?.nativeBash === true ? (nativeRegistered ? "initializing" : "unavailable") : "disabled",
        unsupported: nativeLoadFailed ? ["native-runtime-load"] :
          ["async", "service", "pty", "preexisting-shell-snapshot-cache"] },
      last: { outcome: "unavailable", source: "none", reasonCode: "NOT_REVIEWED", chain: [] },
    };
    let queue = Promise.resolve();

    const invalidate = () => {
      abortPending(state); state.generation++; tickets.clear(); rawCaptures.clear(); seenToolCallIds.clear();
    };

    const acquire = async (signal: AbortSignal): Promise<(() => void) | undefined> => {
      const previous = queue;
      let release!: () => void;
      const gate = new Promise<void>(resolve => { release = resolve; });
      queue = previous.then(() => gate);
      if (signal.aborted) { void previous.then(release); return undefined; }
      try {
        await new Promise<void>((resolve, reject) => {
          const abort = () => reject(new Error("cancelled"));
          signal.addEventListener("abort", abort, { once: true });
          previous.then(() => { signal.removeEventListener("abort", abort); resolve(); });
        });
      } catch { void previous.then(release); return undefined; }
      if (signal.aborted) { release(); return undefined; }
      return release;
    };

    const approve = async (params: PlainBashParams, ctx: ExtensionContext, signal: AbortSignal,
      toolName: "bash" | "permission_bash", native?: NativeSettingsSnapshot): Promise<ApprovalOutcome> => {
      if (!config) return { approved: false, source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] };
      state.native.diagnostics = nativeDiagnostics(native);
      const cwd = effectiveCwd(ctx.cwd, params.cwd) ?? params.cwd ?? ctx.cwd;
      const configuredGate = configuredNativeApproval(config, params.command);
      if (configuredGate === "deny" || native?.decision === "deny")
        return { approved: false, source: "native", reasonCode: "NATIVE_DENY", chain: ["native"] };
      const messages = userMessages(ctx);
      const nativePrompt = native?.decision === "prompt";
      const needsHuman = state.mode === "manual" || configuredGate === "prompt" ||
        configuredGate === "unsupported" || nativePrompt || messages.length === 0 ||
        containsSensitiveText(params.command, cwd, messages);
      if (needsHuman) {
        const reasonCode = native?.reasonCode === "UNSUPPORTED_EXECUTION_CONTEXT" ? native.reasonCode :
          configuredGate === "unsupported" ? "UNSUPPORTED_SYNTAX" :
            nativePrompt ? "NATIVE_PROMPT" : "USER_CONFIRMATION_REQUIRED";
        const chain: ApprovalOutcome["chain"] = nativePrompt || configuredGate === "prompt" ?
          ["native", "human"] : ["human"];
        state.human.calls++;
        state.last = { outcome: "pending-human", source: "human", reasonCode, chain };
        const approved = await humanApprove(ctx, toolName, params.command, cwd, reasonCode, signal,
          state.native.diagnostics?.contextReason);
        state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
        return { approved, source: "human", reasonCode,
          chain };
      }
      state.last = { outcome: "reviewing", source: "none", reasonCode: "REVIEW_PENDING", chain: [] };
      const result = await reviewCommand({ command: params.command, cwd, userMessages: messages,
        parameters: { cwd: params.cwd, timeout: params.timeout }, reviewer: config.reviewer,
        executionContext: { entrypoint: toolName, baseCwd: ctx.cwd, ...(native?.reviewContext ?? {}) },
        remoteFallback: config.remoteFallback }, reviewRuntime(ctx, dependencies.fetch ?? globalThis.fetch), signal);
      const chain = recordReview(state, config, result);
      if (result.status === "valid") {
        const source = result.source ?? "primary";
        const reasonCode = result.review!.reasonCode;
        if (result.review!.decision === "allow") return { approved: true, source, reasonCode, chain };
        if (result.review!.decision === "deny") return { approved: false, source, reasonCode, chain };
      }
      const reasonCode = result.review?.reasonCode ?? "REVIEW_UNAVAILABLE";
      state.human.calls++;
      state.last = { outcome: "pending-human", source: "human", reasonCode, chain: [...chain, "human"] };
      const approved = await humanApprove(ctx, toolName, params.command, cwd, reasonCode, signal,
        state.native.diagnostics?.contextReason);
      state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
      return { approved, source: "human", reasonCode,
        chain: [...chain, "human"] };
    };

    const reset = async () => {
      invalidate();
      try {
        const next = await load();
        if ((next.nativeBash === true) !== nativeRegistered || (nativeRegistered && !nativeRuntime))
          throw new Error("native bash registration does not match configuration");
        if (omp.getAllTools().filter(tool => tool.name === "permission_bash").length !== 1)
          throw new Error("permission_bash registration conflict");
        if (nativeRegistered && omp.getAllTools().filter(tool => tool.name === "bash").length !== 1)
          throw new Error("bash registration conflict");
        config = next; state.mode = config.defaultMode;
        state.primary = attemptState(configuredTarget(config.reviewer), undefined);
        state.remote = attemptState(configuredTarget(config.remoteFallback), undefined);
        state.human = { calls: 0, health: "idle" };
        state.native.coverage = nativeRegistered ? "limited" : "disabled";
        state.native.scopedSettingsReady = false;
        state.native.diagnostics = undefined;
        state.last = { outcome: "ready", source: "none", reasonCode: "NOT_REVIEWED", chain: [] };
        const active = omp.getActiveTools();
        const nextActive = nativeRegistered ? [...new Set([...active, "permission_bash"])] :
          [...new Set([...active.filter(name => name !== "bash"), "permission_bash"])];
        await omp.setActiveTools(nextActive);
      } catch {
        config = undefined; state.mode = "manual";
        state.native.diagnostics = undefined;
        state.primary = { configured: "unavailable", calls: 0, health: "unavailable" };
        state.remote = { configured: "disabled", calls: 0, health: "unavailable" };
        state.native.coverage = nativeRegistered ? "unavailable" : "disabled";
        state.last = { outcome: "blocked", source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] };
      }
    };

    omp.on("session_start", reset); omp.on("session_switch", reset); omp.on("session_branch", reset);
    omp.on("session_shutdown", () => { invalidate(); });

    omp.registerCommand("permission-control", {
      description: "Set or inspect standalone permission control",
      handler: async (args, ctx) => {
        const command = args.trim();
        if (command === "smart" || command === "manual") {
          invalidate(); state.mode = command;
          ctx.ui.notify(JSON.stringify({ mode: state.mode, generation: state.generation }), "info");
        } else if (command === "status") {
          ctx.ui.notify(JSON.stringify({ mode: state.mode, generation: state.generation,
            configuration: config ? "ready" : "unavailable",
            entrypoints: { raw: "permission_bash", native: nativeRegistered ? "bash" : "disabled" },
            coverage: state.native.coverage, nativeDelegateAvailable: state.native.delegateAvailable,
            scopedSettingsReady: state.native.scopedSettingsReady, unsupported: state.native.unsupported,
            nativeContext: state.native.diagnostics,
            nativeCalls: state.native.calls, nativeDelegateCalls: state.native.delegateCalls,
            primary: state.primary, remote: state.remote, human: state.human,
            fallback: config?.fallback ? "unavailable" : "disabled", pending: state.pending.size,
            nativeProtection: "configured-patterns-plus-public-native-bash-approval" }), "info");
        } else if (command === "explain") ctx.ui.notify(JSON.stringify({ ...state.last,
          nativeContext: state.native.diagnostics }), "info");
        else ctx.ui.notify("/permission-control smart\n/permission-control manual\n/permission-control status\n/permission-control explain", "info");
      },
    });

    const Type = omp.typebox.Type;
    const parameters = Type.Object({ command: Type.String(), cwd: Type.Optional(Type.String()),
      timeout: Type.Optional(Type.Number({ minimum: 0 })) }, { additionalProperties: true });

    if (nativeRegistered && nativeRuntime) {
      omp.on("tool_call", async (event, ctx) => {
        if (event.toolName !== "bash" && event.toolName !== "permission_bash") return undefined;
        state.native.calls++;
        if (seenToolCallIds.has(event.toolCallId)) {
          state.native.diagnostics = undefined;
          state.last = { outcome: "blocked", source: "none", reasonCode: "DUPLICATE_TOOL_CALL", chain: [] };
          return { block: true, reason: "bash approval ticket already used" };
        }
        seenToolCallIds.add(event.toolCallId);
        const params = plainBashParams(event.input);
        if (!config || !params) {
          state.native.diagnostics = undefined;
          state.last = { outcome: "blocked", source: "none", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: [] };
          return { block: true, reason: "unsupported bash execution parameters" };
        }
        if (event.toolName === "permission_bash") {
          try {
            const snapshot = await nativeRuntime.capture(ctx.cwd, params);
            state.native.scopedSettingsReady = true;
            rawCaptures.set(event.toolCallId, { signature: signature(params), generation: state.generation,
              mode: state.mode, sessionId: ctx.sessionManager.getSessionId(), model: modelIdentity(ctx.models.current()),
              baseCwd: ctx.cwd, settings: snapshot.settings, fingerprint: snapshot.fingerprint,
              nativeDecision: snapshot.decision });
            return undefined;
          } catch {
            state.native.scopedSettingsReady = false;
            return { block: true, reason: "scoped bash settings unavailable" };
          }
        }
        const queuedGeneration = state.generation;
        const pending = new AbortController(); state.pending.add(pending);
        const release = await acquire(pending.signal);
        if (!release || state.generation !== queuedGeneration) {
          release?.();
          state.native.diagnostics = undefined;
          state.pending.delete(pending); return { block: true, reason: "stale bash review" };
        }
        let hasCurrentSnapshot = false;
        try {
          const startSession = ctx.sessionManager.getSessionId();
          const startModel = modelIdentity(ctx.models.current()); const startMode = state.mode;
          const snapshot = await nativeRuntime.capture(ctx.cwd, params);
          hasCurrentSnapshot = true;
          state.native.scopedSettingsReady = true;
          const outcome = await approve(params, ctx, pending.signal, "bash", snapshot);
          const checked = await nativeRuntime.recheck(snapshot.settings, ctx.cwd, params);
          state.native.diagnostics = nativeDiagnostics(checked);
          if (!outcome.approved || pending.signal.aborted || state.generation !== queuedGeneration ||
              state.mode !== startMode || ctx.sessionManager.getSessionId() !== startSession ||
              modelIdentity(ctx.models.current()) !== startModel || checked.fingerprint !== snapshot.fingerprint ||
              checked.decision !== snapshot.decision) {
            state.last = { outcome: "blocked", source: outcome.source,
              reasonCode: outcome.approved ? "STALE_REVIEW" : outcome.reasonCode, chain: outcome.chain };
            return { block: true, reason: state.last.reasonCode };
          }
          tickets.set(event.toolCallId, { signature: signature(params), generation: queuedGeneration,
            mode: startMode, sessionId: startSession, model: startModel, baseCwd: ctx.cwd,
            settings: snapshot.settings, fingerprint: snapshot.fingerprint, nativeDecision: snapshot.decision });
          state.last = { outcome: "approved", source: outcome.source, reasonCode: outcome.reasonCode,
            chain: outcome.chain };
          return undefined;
        } catch {
          if (!hasCurrentSnapshot) state.native.diagnostics = undefined;
          state.native.scopedSettingsReady = false;
          state.last = { outcome: "blocked", source: "none", reasonCode: "SCOPED_SETTINGS_UNAVAILABLE", chain: [] };
          return { block: true, reason: "scoped bash settings unavailable" };
        } finally { state.pending.delete(pending); release(); }
      });

      omp.registerTool({
        name: "bash", label: "Bash", description: "Run native Bash after standalone permission review.",
        approval: { tier: "exec", policyKey: "permission_bash" }, loadMode: "essential", parameters,
        async execute(toolCallId, rawParams, signal, onUpdate, ctx) {
          const ticket = tickets.get(toolCallId); tickets.delete(toolCallId);
          const params = plainBashParams(rawParams);
          if (!ticket || !params || ticket.signature !== signature(params) || ticket.generation !== state.generation ||
              ticket.mode !== state.mode || ticket.sessionId !== ctx.sessionManager.getSessionId() ||
              ticket.model !== modelIdentity(ctx.models.current()) || ticket.baseCwd !== ctx.cwd) {
            state.native.diagnostics = undefined;
            state.last = { outcome: "blocked", source: "none", reasonCode: "INVALID_TICKET", chain: [] };
            return textResult("bash blocked", { reasonCode: "INVALID_TICKET" }, true);
          }
          let checked: NativeSettingsSnapshot;
          try { checked = await nativeRuntime.recheck(ticket.settings, ctx.cwd, params); }
          catch {
            state.native.diagnostics = undefined;
            state.native.scopedSettingsReady = false;
            state.last = { outcome: "blocked", source: "none", reasonCode: "SCOPED_SETTINGS_UNAVAILABLE", chain: [] };
            return textResult("bash blocked", { reasonCode: "SCOPED_SETTINGS_UNAVAILABLE" }, true);
          }
          state.native.diagnostics = nativeDiagnostics(checked);
          if (checked.fingerprint !== ticket.fingerprint || checked.decision !== ticket.nativeDecision) {
            state.last = { outcome: "blocked", source: "native", reasonCode: "STALE_REVIEW", chain: ["native"] };
            return textResult("bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          if (signal?.aborted || ticket.generation !== state.generation || ticket.mode !== state.mode ||
              ticket.sessionId !== ctx.sessionManager.getSessionId() ||
              ticket.model !== modelIdentity(ctx.models.current()) || ticket.baseCwd !== ctx.cwd) {
            state.last = { outcome: "blocked", source: "none", reasonCode: "STALE_REVIEW", chain: [] };
            return textResult("bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          if (!ctx.invokeTool) {
            state.native.delegateAvailable = false;
            state.last = { outcome: "blocked", source: "none", reasonCode: "NATIVE_DELEGATE_UNAVAILABLE", chain: [] };
            return textResult("bash blocked", { reasonCode: "NATIVE_DELEGATE_UNAVAILABLE" }, true);
          }
          state.native.delegateAvailable = true; state.native.delegateCalls++;
          try {
            const result = await ctx.invokeTool(rawParams, { signal, onUpdate });
            state.native.coverage = "ready";
            state.last = { outcome: result.isError === true ? "failed" : "executed", source: state.last.source,
              reasonCode: state.last.reasonCode, chain: state.last.chain };
            return result;
          } catch (error) {
            state.last = { outcome: "failed", source: "native", reasonCode: "NATIVE_EXECUTION_FAILED", chain: ["native"] };
            throw error;
          }
        },
      });
    }

    omp.registerTool({
      name: "permission_bash", label: "Permission Bash",
      description: "Run raw non-interactive Bash after standalone permission review. Service, job, PTY, and native Bash behavior are separate.",
      approval: { tier: "exec", policy: "allow" }, loadMode: "essential", parameters,
      async execute(toolCallId, rawParams, signal, _onUpdate, ctx) {
        const params = plainBashParams(rawParams);
        if (!config || !params || (params.timeout !== undefined && params.timeout > 120)) {
          state.native.diagnostics = undefined;
          return textResult("permission_bash blocked", { reasonCode: "INVALID_OR_UNAVAILABLE" }, true);
        }
        const queuedGeneration = state.generation;
        const pending = new AbortController(); state.pending.add(pending);
        const combined = signal ? AbortSignal.any([signal, pending.signal]) : pending.signal;
        const release = await acquire(combined);
        if (!release || combined.aborted || state.generation !== queuedGeneration) {
          release?.();
          state.native.diagnostics = undefined;
          state.pending.delete(pending);
          return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
        }
        const startSession = ctx.sessionManager.getSessionId();
        const startModel = modelIdentity(ctx.models.current()); const startMode = state.mode;
        let hasCurrentSnapshot = false;
        try {
          const rawTicket = rawCaptures.get(toolCallId); rawCaptures.delete(toolCallId);
          if (config.nativeBash === true && (!rawTicket || rawTicket.signature !== signature(params) ||
              rawTicket.generation !== queuedGeneration || rawTicket.mode !== startMode ||
              rawTicket.sessionId !== startSession || rawTicket.model !== startModel || rawTicket.baseCwd !== ctx.cwd)) {
            state.native.diagnostics = undefined;
            return textResult("permission_bash blocked", { reasonCode: "INVALID_TICKET" }, true);
          }
          const nativeSnapshot = rawTicket ? await nativeRuntime!.recheck(rawTicket.settings, ctx.cwd, params) : undefined;
          hasCurrentSnapshot = nativeSnapshot !== undefined;
          state.native.diagnostics = nativeDiagnostics(nativeSnapshot);
          if (rawTicket && (nativeSnapshot!.fingerprint !== rawTicket.fingerprint ||
              nativeSnapshot!.decision !== rawTicket.nativeDecision))
            return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          const outcome = await approve(params, ctx, combined, "permission_bash", nativeSnapshot);
          const nativeChecked = rawTicket ? await nativeRuntime!.recheck(rawTicket.settings, ctx.cwd, params) : undefined;
          state.native.diagnostics = nativeDiagnostics(nativeChecked);
          if (!outcome.approved || combined.aborted || state.generation !== queuedGeneration || state.mode !== startMode ||
              ctx.sessionManager.getSessionId() !== startSession || modelIdentity(ctx.models.current()) !== startModel ||
              (rawTicket !== undefined && ctx.cwd !== rawTicket.baseCwd)) {
            state.last = { outcome: "blocked", source: outcome.source,
              reasonCode: outcome.approved ? "STALE_REVIEW" : outcome.reasonCode, chain: outcome.chain };
            return textResult("permission_bash blocked", { reasonCode: state.last.reasonCode }, true);
          }
          if (rawTicket && (nativeChecked!.fingerprint !== rawTicket.fingerprint ||
              nativeChecked!.decision !== rawTicket.nativeDecision)) {
            state.last = { outcome: "blocked", source: "native", reasonCode: "STALE_REVIEW", chain: ["native"] };
            return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          const cwd = effectiveCwd(ctx.cwd, params.cwd);
          if (!cwd) return textResult("permission_bash blocked", { reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT" }, true);
          const result = await omp.exec("bash", ["--noprofile", "--norc", "-c", params.command], {
            cwd, signal: combined,
            timeout: params.timeout === undefined ? undefined : params.timeout * 1000,
          });
          state.last = { outcome: result.code === 0 ? "executed" : "failed", source: outcome.source,
            reasonCode: outcome.reasonCode, chain: outcome.chain };
          const output = [result.stdout, result.stderr].filter(Boolean).map(boundedOutput).join("\n");
          return textResult(output || `(exit ${result.code})`, { code: result.code, killed: result.killed }, result.code !== 0);
        } catch {
          if (!hasCurrentSnapshot) state.native.diagnostics = undefined;
          state.last = { outcome: "blocked", source: "none", reasonCode: "RUNTIME_FAILURE", chain: [] };
          return textResult("permission_bash blocked", { reasonCode: "RUNTIME_FAILURE" }, true);
        } finally { state.pending.delete(pending); release(); }
      },
    });
  };
}

export default createStandalonePlugin();
