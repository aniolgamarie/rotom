import { createApprovalAudit, safeIdentity, type ApprovalDiagnostic } from "./approval-diagnostic";
import { lstat, readFile } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { checkConfiguredRules } from "./standalone-policy";
import { prepareReviewPacket, redactReviewText } from "./review-input";
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
  failureCode?: string;
  httpStatus?: number;
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
  authorization: string;
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

// 只保留内存中的用户指令绑定，不写入审查包/状态/审计，也不生成秘密摘要。
function authorizationSignature(ctx: ExtensionContext): string | null {
  try {
    if (ctx.hasPendingMessages?.()) return null;
    return JSON.stringify(userMessages(ctx));
  } catch { return null; }
}

const redactSensitive = (value: string) => redactReviewText(value, "display");

function worktreeSummary(plan: NativeSettingsSnapshot["reviewContext"][string] | undefined): string {
  if (!plan || typeof plan !== "object" || Array.isArray(plan)) return "";
  if (plan.mayRewrite === true && plan.verified === false) return "\nPossible native worktree rewrite: analysis is incomplete; rewrite scope is unverified." +
    "\nMay copy source-checkout local/ignored data; copied set is not enumerated or guaranteed secret-free." +
    "\nFresh CLI repository-cwd configuration/backend may differ; post-checkout hooks may execute local code whose contents were not inspected." +
    "\nUnverified possible effects are not authorization or an automatic low-risk signal.";
  const operations = Array.isArray(plan.operations) ? plan.operations.filter(value =>
    value && typeof value === "object" && !Array.isArray(value)) : [];
  const items = operations as Array<Record<string, unknown>>;
  const display = (value: unknown) => typeof value === "string" ? redactSensitive(value).slice(0, 120) : "unspecified";
  const summary = items.slice(0, 3).map(value =>
    "target " + JSON.stringify(redactSensitive(display(value.target))) +
    ", branch " + JSON.stringify(redactSensitive(display(value.branch)))).join("; ");
  return "\nworktree clone effects: " + summary +
    (items.length > 3 ? ` (+${items.length - 3} more operations; see raw command)` : "") +
    `\n-B branch reset possible: ${items.some(value => value.forceBranch === true)}` +
    "\nMay copy source-checkout local/ignored data; copied set is not enumerated or guaranteed secret-free." +
    "\nbackend: " + JSON.stringify(redactSensitive(display(plan.backend))) +
    "; configured intent, not a success or copied-set guarantee; ordinary checkout fallback is possible." +
    "\nNew CLI re-resolves repository-cwd settings; actual clone/backend may differ and child settings are not protected by this fingerprint." +
    "\nPost-checkout hooks may execute local code; hook contents were not inspected or protected by this fingerprint." +
    "\nDispatch effects are not complete side-effect verification, authorization or an automatic low-risk signal.";
}

async function humanApprove(ctx: ExtensionContext, toolName: string, command: string, cwd: string,
  reasonCode: string, signal?: AbortSignal, contextReason?: NativeDiagnostics["contextReason"],
  plan?: NativeSettingsSnapshot["reviewContext"][string]): Promise<boolean> {
  if (!ctx.hasUI || signal?.aborted) return false;
  try {
    const title = `Allow ${toolName}?\nreason: ${reasonCode}\n` +
      (contextReason ? `context: ${contextReason}\n` : "") + `cwd: ${JSON.stringify(redactSensitive(cwd))}\n` +
      `command: ${JSON.stringify(redactSensitive(command))}` + worktreeSummary(plan);
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
  if (!attempt) return { configured: safeIdentity(configured) ?? "unsafe-or-unavailable", calls: 0, health: configured === "disabled" ? "unavailable" : "idle" };
  return { configured: safeIdentity(configured) ?? "unsafe-or-unavailable",
    actualModel: attempt.model ? safeIdentity(`${attempt.model.provider}/${attempt.model.id}`) : undefined,
    calls: attempt.called ? 1 : 0, health: attempt.status === "valid" ? "ready" : attempt.health,
    ...(attempt.status === "failure" ? { failureCode: attempt.failureCode,
      ...(attempt.httpStatus !== undefined ? { httpStatus: attempt.httpStatus } : {}) } : {}) };
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
    const audit = createApprovalAudit(typeof omp.appendEntry === "function" ? (type, data) => omp.appendEntry(type, data) : undefined);
    const pendingDiagnostics = new Map<string, ApprovalDiagnostic>();
    let queue = Promise.resolve();

    const observationSessionId = (ctx: ExtensionContext): string | undefined => {
      try { return ctx.sessionManager.getSessionId(); } catch { return undefined; }
    };

    const invalidate = () => {
      for (const call of pendingDiagnostics.values()) {
        call.invalidated = true; call.gates("INVALIDATED", "CANCELLED");
        if (call.awaitingExecute) audit.finish(call, "invalidated", "cancelled", "CANCELLED");
      }
      pendingDiagnostics.clear();
      abortPending(state); state.generation++; tickets.clear(); rawCaptures.clear(); seenToolCallIds.clear();
    };

    const dropDiagnostic = (id: string, call: ApprovalDiagnostic) => {
      if (pendingDiagnostics.get(id) === call) pendingDiagnostics.delete(id);
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
      toolName: "bash" | "permission_bash", native?: NativeSettingsSnapshot,
      diagnostic?: ApprovalDiagnostic): Promise<ApprovalOutcome> => {
      if (!config) { diagnostic?.gates("CONFIG_UNAVAILABLE"); return { approved: false, source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] }; }
      // raw shell 不执行宿主 clone 重写；保留其旧人工边界，不借用原生计划宣称效果。
      if (toolName === "permission_bash" && (native?.reviewContext.worktreePlan || native?.reviewContext.unverifiedWorktreeEffects)) {
        const { worktreePlan: _plan, unverifiedWorktreeEffects: _unverified, ...reviewContext } = native.reviewContext;
        native = { ...native, reviewContext,
          decision: native.decision === "deny" ? "deny" : "prompt",
          reasonCode: native.decision === "allow" ? "UNSUPPORTED_EXECUTION_CONTEXT" : native.reasonCode,
          diagnostics: native.diagnostics ? { ...native.diagnostics, contextReason: "WORKTREE_CONTEXT" } : undefined };
      }
      state.native.diagnostics = nativeDiagnostics(native);
      diagnostic?.context(state.native.diagnostics);
      const cwd = effectiveCwd(ctx.cwd, params.cwd) ?? params.cwd ?? ctx.cwd;
      const rules = checkConfiguredRules(params.command, config.nativePatterns);
      const configuredGate = rules.decision;
      diagnostic?.analysis(rules.analysis, rules.matchedRuleIds, rules.uncertainRuleIds);
      if (configuredGate === "deny" || native?.decision === "deny") {
        diagnostic?.gates(...(configuredGate === "deny" ? ["CONFIGURED_DENY"] : []),
          ...(native?.decision === "deny" ? ["NATIVE_DENY"] : []));
        return { approved: false, source: "native", reasonCode: "NATIVE_DENY", chain: ["native"] };
      }
      const messages = userMessages(ctx);
      const unsupportedContext = native?.decision === "prompt" && native.reasonCode === "UNSUPPORTED_EXECUTION_CONTEXT";
      const nativePrompt = native?.decision === "prompt" && !unsupportedContext;
      const needsHuman = state.mode === "manual" || configuredGate === "prompt" || nativePrompt;
      diagnostic?.gates(...(state.mode === "manual" ? ["MANUAL_MODE"] : []),
        ...(configuredGate === "prompt" ? ["CONFIGURED_PROMPT"] : []), ...(nativePrompt ? ["NATIVE_PROMPT"] : []));
      if (needsHuman) {
        const reasonCode = nativePrompt ? "NATIVE_PROMPT" : "USER_CONFIRMATION_REQUIRED";
        const chain: ApprovalOutcome["chain"] = nativePrompt || configuredGate === "prompt" ? ["native", "human"] : ["human"];
        state.human.calls++;
        state.last = { outcome: "pending-human", source: "human", reasonCode, chain };
        if (diagnostic) diagnostic.routingComplete = true;
        const approved = await humanApprove(ctx, toolName, params.command, cwd, reasonCode, signal,
          state.native.diagnostics?.contextReason, native?.reviewContext.worktreePlan ?? native?.reviewContext.unverifiedWorktreeEffects);
        state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
        return { approved, source: "human", reasonCode, chain };
      }
      state.last = { outcome: "reviewing", source: "none", reasonCode: "REVIEW_PENDING", chain: [] };
      const prepared = prepareReviewPacket({ command: params.command, cwd, userMessages: messages,
        parameters: { cwd: params.cwd, timeout: params.timeout },
        executionContext: { entrypoint: toolName, baseCwd: ctx.cwd, ...(native?.reviewContext ?? {}),
          shellFamily: toolName === "permission_bash" ? "bash" : typeof native?.reviewContext.shellFamily === "string" ? native.reviewContext.shellFamily : "unknown",
          shellAnalysis: { status: rules.analysis },
          ...(config.nativePatterns.length ? { configuredRules: config.nativePatterns.map((rule, id) => ({
            id, match: rule.match, approval: rule.approval, uncertain: rules.uncertainRuleIds.includes(id) })) } : {}) } });
      if (prepared.status === "ready") diagnostic?.input(prepared.packet);
      else diagnostic?.gates(prepared.reasonCode);
      if (diagnostic) diagnostic.reviewStarted = prepared.status === "ready";
      const reviewMode = state.mode, reviewGeneration = state.generation, reviewSession = ctx.sessionManager.getSessionId();
      const reviewCwd = ctx.cwd, reviewAuthorization = JSON.stringify(messages);
      const isCurrent = () => !signal.aborted && state.mode === reviewMode && state.generation === reviewGeneration &&
        ctx.cwd === reviewCwd && ctx.sessionManager.getSessionId() === reviewSession && authorizationSignature(ctx) === reviewAuthorization;
      const runtime = { ...reviewRuntime(ctx, dependencies.fetch ?? globalThis.fetch), isCurrent };
      const result: ReviewSequenceResult = prepared.status === "ready"
        ? await reviewCommand(prepared.packet, { reviewer: config.reviewer, remoteFallback: config.remoteFallback },
          runtime, signal)
        : { status: prepared.status === "input-too-large" ? "input-too-large" : "failure",
          primary: { status: "failure", called: false, health: "invalid", failureCode: prepared.reasonCode } };
      diagnostic?.review(result);
      if (prepared.status === "invalid") return { approved: false, source: "none", reasonCode: "INPUT_INVALID", chain: [] };
      const chain = recordReview(state, config, result);
      if (!isCurrent()) return { approved: false, source: "none", reasonCode: signal.aborted ? "CANCELLED" : "STALE_REVIEW", chain };
      if (result.status === "valid") {
        const source = result.source ?? "primary";
        const reasonCode = result.review!.reasonCode;
        if (result.review!.decision === "deny") return { approved: false, source, reasonCode, chain };
        // 接线/设置无法绑定时，模型决定也不能绕过原生执行边界。
        if (unsupportedContext) return { approved: false, source: "native", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: [...chain, "native"] };
        if (result.review!.decision === "allow") {
          if (rules.uncertainRuleIds.some(id => config!.nativePatterns[id].approval === "deny"))
            return { approved: false, source: "native", reasonCode: "RULE_TARGET_UNVERIFIED", chain: [...chain, "native"] };
          if (!rules.uncertainRuleIds.length) return { approved: true, source, reasonCode, chain };
        }
      }
      if (unsupportedContext) return { approved: false, source: "native", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: [...chain, "native"] };
      if (rules.uncertainRuleIds.some(id => config!.nativePatterns[id].approval === "deny"))
        return { approved: false, source: "native", reasonCode: "RULE_TARGET_UNVERIFIED", chain: [...chain, "native"] };
      const rulePrompt = result.status === "valid" && result.review!.decision === "allow" && rules.uncertainRuleIds.length > 0;
      const reasonCode = rulePrompt ? "RULE_CONFIRMATION_REQUIRED" : result.review?.reasonCode ?? "REVIEW_UNAVAILABLE";
      state.human.calls++;
      state.last = { outcome: "pending-human", source: "human", reasonCode, chain: [...chain, "human"] };
      const approved = await humanApprove(ctx, toolName, params.command, cwd, reasonCode, signal,
        state.native.diagnostics?.contextReason, native?.reviewContext.worktreePlan ?? native?.reviewContext.unverifiedWorktreeEffects);
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
            rawNativeCloneCoverage: "not-applicable-raw-shell",
            coverage: state.native.coverage, nativeDelegateAvailable: state.native.delegateAvailable,
            scopedSettingsReady: state.native.scopedSettingsReady, unsupported: state.native.unsupported,
            nativeContext: state.native.diagnostics,
            nativeCalls: state.native.calls, nativeDelegateCalls: state.native.delegateCalls,
            primary: state.primary, remote: state.remote, human: state.human,
            fallback: config?.fallback ? "unavailable" : "disabled", pending: state.pending.size,
            audit: { accepted: audit.state.accepted, failed: audit.state.failed, health: audit.state.health,
              durability: audit.state.durability }, diagnostic: audit.state.last,
            nativeProtection: "configured-patterns-plus-public-native-bash-approval" }), "info");
        } else if (command === "explain") ctx.ui.notify(JSON.stringify(audit.state.last ? {
          outcome: audit.state.last.outcome, source: audit.state.last.source, reasonCode: audit.state.last.reasonCode,
          chain: audit.state.last.chain, nativeContext: audit.state.last.nativeContext, diagnostic: audit.state.last,
        } : { ...state.last, nativeContext: state.native.diagnostics }), "info");
        else ctx.ui.notify("/permission-control smart\n/permission-control manual\n/permission-control status\n/permission-control explain", "info");
      },
    });

    const Type = omp.typebox.Type;
    const parameters = Type.Object({ command: Type.String(), cwd: Type.Optional(Type.String()),
      timeout: Type.Optional(Type.Number({ minimum: 0 })) }, { additionalProperties: true });

    if (nativeRegistered && nativeRuntime) {
      omp.on("tool_call", async (event, ctx) => {
        if (event.toolName !== "bash" && event.toolName !== "permission_bash") return undefined;
        const diagnostic = audit.begin(event.toolCallId, event.toolName, state.mode, state.generation, observationSessionId(ctx));
        state.native.calls++;
        if (seenToolCallIds.has(event.toolCallId)) {
          state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.last = { outcome: "blocked", source: "none", reasonCode: "DUPLICATE_TOOL_CALL", chain: [] };
          diagnostic.gates("DUPLICATE_TICKET"); audit.finish(diagnostic, "hook", "blocked", "DUPLICATE_TOOL_CALL");
          return { block: true, reason: "bash approval ticket already used" };
        }
        seenToolCallIds.add(event.toolCallId);
        pendingDiagnostics.set(event.toolCallId, diagnostic);
        const params = plainBashParams(event.input);
        if (!config || !params) {
          state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.last = { outcome: "blocked", source: "none", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: [] };
          diagnostic.gates(!config ? "CONFIG_UNAVAILABLE" : "INVALID_PARAMETERS");
          audit.finish(diagnostic, "hook", "blocked", !config ? "CONFIG_UNAVAILABLE" : "UNSUPPORTED_EXECUTION_CONTEXT");
          dropDiagnostic(event.toolCallId, diagnostic);
          return { block: true, reason: "unsupported bash execution parameters" };
        }
        if (event.toolName === "permission_bash") {
          try {
            const stamp = { generation: state.generation, mode: state.mode, sessionId: ctx.sessionManager.getSessionId(),
              model: modelIdentity(ctx.models.current()), baseCwd: ctx.cwd, authorization: authorizationSignature(ctx) };
            const snapshot = await nativeRuntime.capture(stamp.baseCwd, params);
            state.native.scopedSettingsReady = true;
            diagnostic.context(nativeDiagnostics(snapshot));
            if (diagnostic.invalidated || state.generation !== stamp.generation || state.mode !== stamp.mode ||
                ctx.sessionManager.getSessionId() !== stamp.sessionId || modelIdentity(ctx.models.current()) !== stamp.model || ctx.cwd !== stamp.baseCwd || stamp.authorization === null || authorizationSignature(ctx) !== stamp.authorization) {
              state.native.scopedSettingsReady = false;
              diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "hook", "cancelled", "STALE_REVIEW");
              dropDiagnostic(event.toolCallId, diagnostic);
              return { block: true, reason: "stale bash review" };
            }
            diagnostic.awaitingExecute = true;
            rawCaptures.set(event.toolCallId, { signature: signature(params), ...stamp, authorization: stamp.authorization,
              settings: snapshot.settings, fingerprint: snapshot.fingerprint, nativeDecision: snapshot.decision });
            return undefined;
          } catch {
            state.native.scopedSettingsReady = false; diagnostic.context(undefined);
            diagnostic.gates("SCOPED_SETTINGS_UNAVAILABLE"); audit.finish(diagnostic, "hook", "blocked", "SCOPED_SETTINGS_UNAVAILABLE");
            dropDiagnostic(event.toolCallId, diagnostic);
            return { block: true, reason: "scoped bash settings unavailable" };
          }
        }
        const queuedGeneration = state.generation;
        const pending = new AbortController(); state.pending.add(pending);
        const release = await acquire(pending.signal);
        if (!release || state.generation !== queuedGeneration) {
          release?.();
          state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.pending.delete(pending);
          diagnostic.gates("QUEUE_CANCELLED"); audit.finish(diagnostic, "hook", "cancelled", "STALE_REVIEW");
          dropDiagnostic(event.toolCallId, diagnostic); return { block: true, reason: "stale bash review" };
        }
        let hasCurrentSnapshot = false;
        try {
          const startSession = ctx.sessionManager.getSessionId();
          const startModel = modelIdentity(ctx.models.current()); const startMode = state.mode;
          const startCwd = ctx.cwd, startAuthorization = authorizationSignature(ctx);
          const snapshot = await nativeRuntime.capture(ctx.cwd, params);
          hasCurrentSnapshot = true;
          state.native.scopedSettingsReady = true;
          const outcome = await approve(params, ctx, pending.signal, "bash", snapshot, diagnostic);
          diagnostic.approval(outcome);
          const checked = await nativeRuntime.recheck(snapshot.settings, ctx.cwd, params);
          state.native.diagnostics = nativeDiagnostics(checked); diagnostic.context(state.native.diagnostics);
          if (!outcome.approved || pending.signal.aborted || state.generation !== queuedGeneration ||
              state.mode !== startMode || ctx.sessionManager.getSessionId() !== startSession ||
              modelIdentity(ctx.models.current()) !== startModel || ctx.cwd !== startCwd || startAuthorization === null ||
              authorizationSignature(ctx) !== startAuthorization || checked.fingerprint !== snapshot.fingerprint ||
              checked.decision !== snapshot.decision) {
            state.last = { outcome: "blocked", source: outcome.source,
              reasonCode: outcome.approved ? "STALE_REVIEW" : outcome.reasonCode, chain: outcome.chain };
            if (outcome.approved) diagnostic.gates("STALE_REVIEW");
            audit.finish(diagnostic, "hook", pending.signal.aborted ? "cancelled" : "blocked",
              pending.signal.aborted ? "CANCELLED" : state.last.reasonCode);
            dropDiagnostic(event.toolCallId, diagnostic);
            return { block: true, reason: state.last.reasonCode };
          }
          diagnostic.awaitingExecute = true;
          tickets.set(event.toolCallId, { signature: signature(params), generation: queuedGeneration,
            mode: startMode, sessionId: startSession, model: startModel, baseCwd: startCwd, authorization: startAuthorization,
            settings: snapshot.settings, fingerprint: snapshot.fingerprint, nativeDecision: snapshot.decision });
          state.last = { outcome: "approved", source: outcome.source, reasonCode: outcome.reasonCode,
            chain: outcome.chain };
          return undefined;
        } catch {
          if (!hasCurrentSnapshot) state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.native.scopedSettingsReady = false;
          state.last = { outcome: "blocked", source: "none", reasonCode: "SCOPED_SETTINGS_UNAVAILABLE", chain: [] };
          diagnostic.gates("SCOPED_SETTINGS_UNAVAILABLE"); audit.finish(diagnostic, "hook", "blocked", "SCOPED_SETTINGS_UNAVAILABLE");
          dropDiagnostic(event.toolCallId, diagnostic);
          return { block: true, reason: "scoped bash settings unavailable" };
        } finally { state.pending.delete(pending); release(); }
      });

      omp.registerTool({
        name: "bash", label: "Bash", description: "Run native Bash after standalone permission review.",
        approval: { tier: "exec", policyKey: "permission_bash" }, loadMode: "essential", parameters,
        async execute(toolCallId, rawParams, signal, onUpdate, ctx) {
          const diagnostic = pendingDiagnostics.get(toolCallId) ?? audit.begin(toolCallId, "bash", state.mode, state.generation, observationSessionId(ctx));
          pendingDiagnostics.delete(toolCallId);
          const ticket = tickets.get(toolCallId); tickets.delete(toolCallId);
          const params = plainBashParams(rawParams);
          if (!ticket || !params || ticket.signature !== signature(params) || ticket.generation !== state.generation ||
              ticket.mode !== state.mode || ticket.sessionId !== ctx.sessionManager.getSessionId() ||
              ticket.model !== modelIdentity(ctx.models.current()) || ticket.baseCwd !== ctx.cwd ||
              authorizationSignature(ctx) !== ticket.authorization) {
            state.native.diagnostics = undefined; diagnostic.context(undefined);
            state.last = { outcome: "blocked", source: "none", reasonCode: "INVALID_TICKET", chain: [] };
            diagnostic.gates("INVALID_TICKET"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "INVALID_TICKET");
            return textResult("bash blocked", { reasonCode: "INVALID_TICKET" }, true);
          }
          let checked: NativeSettingsSnapshot;
          try { checked = await nativeRuntime.recheck(ticket.settings, ctx.cwd, params); }
          catch {
            state.native.diagnostics = undefined; diagnostic.context(undefined);
            state.native.scopedSettingsReady = false;
            state.last = { outcome: "blocked", source: "none", reasonCode: "SCOPED_SETTINGS_UNAVAILABLE", chain: [] };
            diagnostic.gates("SCOPED_SETTINGS_UNAVAILABLE"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "SCOPED_SETTINGS_UNAVAILABLE");
            return textResult("bash blocked", { reasonCode: "SCOPED_SETTINGS_UNAVAILABLE" }, true);
          }
          state.native.diagnostics = nativeDiagnostics(checked); diagnostic.context(state.native.diagnostics);
          if (checked.fingerprint !== ticket.fingerprint || checked.decision !== ticket.nativeDecision) {
            state.last = { outcome: "blocked", source: "native", reasonCode: "STALE_REVIEW", chain: ["native"] };
            diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "STALE_REVIEW");
            return textResult("bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          if (signal?.aborted || ticket.generation !== state.generation || ticket.mode !== state.mode ||
              ticket.sessionId !== ctx.sessionManager.getSessionId() ||
              ticket.model !== modelIdentity(ctx.models.current()) || ticket.baseCwd !== ctx.cwd ||
              authorizationSignature(ctx) !== ticket.authorization) {
            state.last = { outcome: "blocked", source: "none", reasonCode: "STALE_REVIEW", chain: [] };
            diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "STALE_REVIEW");
            return textResult("bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          if (!ctx.invokeTool) {
            state.native.delegateAvailable = false;
            state.last = { outcome: "blocked", source: "none", reasonCode: "NATIVE_DELEGATE_UNAVAILABLE", chain: [] };
            diagnostic.gates("NATIVE_DELEGATE_UNAVAILABLE"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "NATIVE_DELEGATE_UNAVAILABLE");
            return textResult("bash blocked", { reasonCode: "NATIVE_DELEGATE_UNAVAILABLE" }, true);
          }
          state.native.delegateAvailable = true; state.native.delegateCalls++;
          try {
            const result = await ctx.invokeTool(rawParams, { signal, onUpdate });
            state.native.coverage = "ready";
            state.last = { outcome: result.isError === true ? "failed" : "executed", source: diagnostic.data.source,
              reasonCode: diagnostic.data.reasonCode, chain: diagnostic.data.chain };
            audit.finish(diagnostic, "execute", result.isError === true ? "failed" : "executed",
              result.isError === true ? "NATIVE_RESULT_ERROR" : undefined);
            return result;
          } catch (error) {
            state.last = { outcome: "failed", source: "native", reasonCode: "NATIVE_EXECUTION_FAILED", chain: ["native"] };
            diagnostic.approval(state.last); audit.finish(diagnostic, "execute", "failed", "NATIVE_EXECUTION_FAILED");
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
        const diagnostic = pendingDiagnostics.get(toolCallId) ?? audit.begin(toolCallId, "permission_bash", state.mode, state.generation, observationSessionId(ctx));
        pendingDiagnostics.delete(toolCallId);
        const params = plainBashParams(rawParams);
        if (!config || !params || (params.timeout !== undefined && params.timeout > 120)) {
          diagnostic.gates(!config ? "CONFIG_UNAVAILABLE" : "INVALID_PARAMETERS");
          state.native.diagnostics = undefined; diagnostic.context(undefined);
          audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "INVALID_OR_UNAVAILABLE");
          return textResult("permission_bash blocked", { reasonCode: "INVALID_OR_UNAVAILABLE" }, true);
        }
        const queuedGeneration = state.generation;
        const pending = new AbortController(); state.pending.add(pending);
        const combined = signal ? AbortSignal.any([signal, pending.signal]) : pending.signal;
        const release = await acquire(combined);
        if (!release || combined.aborted || state.generation !== queuedGeneration) {
          release?.();
          state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.pending.delete(pending);
          diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "STALE_REVIEW");
          return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
        }
        const startSession = ctx.sessionManager.getSessionId();
        const startModel = modelIdentity(ctx.models.current()); const startMode = state.mode;
        const startCwd = ctx.cwd, startAuthorization = authorizationSignature(ctx);
        let hasCurrentSnapshot = false;
        try {
          const rawTicket = rawCaptures.get(toolCallId); rawCaptures.delete(toolCallId);
          if (config.nativeBash === true && (!rawTicket || rawTicket.signature !== signature(params) ||
              rawTicket.generation !== queuedGeneration || rawTicket.mode !== startMode ||
              rawTicket.sessionId !== startSession || rawTicket.model !== startModel || rawTicket.baseCwd !== ctx.cwd ||
              rawTicket.authorization !== startAuthorization)) {
            state.native.diagnostics = undefined; diagnostic.context(undefined);
            diagnostic.gates("INVALID_TICKET"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "INVALID_TICKET");
            return textResult("permission_bash blocked", { reasonCode: "INVALID_TICKET" }, true);
          }
          const nativeSnapshot = rawTicket ? await nativeRuntime!.recheck(rawTicket.settings, ctx.cwd, params) : undefined;
          hasCurrentSnapshot = nativeSnapshot !== undefined;
          state.native.diagnostics = nativeDiagnostics(nativeSnapshot);
          if (rawTicket && (nativeSnapshot!.fingerprint !== rawTicket.fingerprint ||
              nativeSnapshot!.decision !== rawTicket.nativeDecision)) {
            diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "STALE_REVIEW");
            return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          const outcome = await approve(params, ctx, combined, "permission_bash", nativeSnapshot, diagnostic);
          diagnostic.approval(outcome);
          const nativeChecked = rawTicket ? await nativeRuntime!.recheck(rawTicket.settings, ctx.cwd, params) : undefined;
          state.native.diagnostics = nativeDiagnostics(nativeChecked); diagnostic.context(state.native.diagnostics);
          if (!outcome.approved || combined.aborted || state.generation !== queuedGeneration || state.mode !== startMode ||
              ctx.sessionManager.getSessionId() !== startSession || modelIdentity(ctx.models.current()) !== startModel ||
              ctx.cwd !== startCwd || startAuthorization === null || authorizationSignature(ctx) !== startAuthorization ||
              (rawTicket !== undefined && ctx.cwd !== rawTicket.baseCwd)) {
            state.last = { outcome: "blocked", source: outcome.source,
              reasonCode: outcome.approved ? "STALE_REVIEW" : outcome.reasonCode, chain: outcome.chain };
            if (outcome.approved) diagnostic.gates("STALE_REVIEW");
            audit.finish(diagnostic, "execute", combined.aborted ? "cancelled" : "blocked",
              combined.aborted ? "CANCELLED" : state.last.reasonCode);
            return textResult("permission_bash blocked", { reasonCode: state.last.reasonCode }, true);
          }
          if (rawTicket && (nativeChecked!.fingerprint !== rawTicket.fingerprint ||
              nativeChecked!.decision !== rawTicket.nativeDecision)) {
            state.last = { outcome: "blocked", source: "native", reasonCode: "STALE_REVIEW", chain: ["native"] };
            diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "STALE_REVIEW");
            return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
          }
          const cwd = effectiveCwd(ctx.cwd, params.cwd);
          if (!cwd) {
            diagnostic.gates("INVALID_PARAMETERS"); audit.finish(diagnostic, "execute", "blocked", "UNSUPPORTED_EXECUTION_CONTEXT");
            return textResult("permission_bash blocked", { reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT" }, true);
          }
          const result = await omp.exec("bash", ["--noprofile", "--norc", "-c", params.command], {
            cwd, signal: combined,
            timeout: params.timeout === undefined ? undefined : params.timeout * 1000,
          });
          state.last = { outcome: result.code === 0 ? "executed" : "failed", source: outcome.source,
            reasonCode: outcome.reasonCode, chain: outcome.chain };
          const output = [result.stdout, result.stderr].filter(Boolean).map(boundedOutput).join("\n");
          audit.finish(diagnostic, "execute", result.code === 0 ? "executed" : "failed",
            result.code === 0 ? undefined : "RAW_EXECUTION_FAILED");
          return textResult(output || `(exit ${result.code})`, { code: result.code, killed: result.killed }, result.code !== 0);
        } catch {
          if (!hasCurrentSnapshot) state.native.diagnostics = undefined; diagnostic.context(undefined);
          state.last = { outcome: "blocked", source: "none", reasonCode: "RUNTIME_FAILURE", chain: [] };
          diagnostic.gates("RUNTIME_FAILURE"); audit.finish(diagnostic, "execute", signal?.aborted ? "cancelled" : "blocked", "RUNTIME_FAILURE");
          return textResult("permission_bash blocked", { reasonCode: "RUNTIME_FAILURE" }, true);
        } finally { state.pending.delete(pending); release(); }
      },
    });
  };
}

export default createStandalonePlugin();
