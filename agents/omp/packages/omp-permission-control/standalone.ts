import { createApprovalAudit, safeIdentity, safeAttempts, reviewFailureSummary, type ApprovalDiagnostic } from "./approval-diagnostic";
import { lstat, readFile } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { checkConfiguredRules } from "./standalone-policy";
import { prepareReviewPacket, redactReviewText } from "./review-input";
import { loadNativeBashRuntime, type NativeBashRuntime, type NativeSettingsSnapshot,
  type PlainBashParams, type NativeDiagnostics, SHELL_FAMILIES, CONTEXT_REASONS } from "./native-bash";
import { parseStandaloneJson, reviewCommand, type ReviewAttempt, type ReviewRuntime, type ReviewTarget,
  type ReviewerModel, type ReviewSequenceResult, type ReviewTimeouts, type ReviewTiming, resolveReviewTimeouts } from "./standalone-reviewer";
import { ApprovalQueue, LifecycleFailure, lifecycleLimits, waitFor, type LifecycleLimits } from "./approval-lifecycle";

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
  reviewTimeouts?: ReviewTimeouts;
}

interface LayerState {
  configured: string;
  actualModel?: string;
  calls: number;
  failureCode?: string;
  httpStatus?: number;
  timing?: ReviewTiming;
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
  lifecycle?: Partial<LifecycleLimits>;
}

interface ApprovalOutcome {
  approved: boolean;
  source: DecisionSource;
  reasonCode: string;
  chain: State["last"]["chain"];
}

interface RequestStamp {
  generation: number;
  mode: Mode;
  sessionId: string;
  model: string;
  baseCwd: string;
  authorization: string;
}

const HEX64 = /^[0-9a-f]{64}$/u;
const CONFIG_KEYS = new Set(["schemaVersion", "defaultMode", "reviewer", "remoteFallback", "fallback",
  "pluginId", "pluginDigest", "policyVersion", "nativePatterns", "nativeBash", "reviewTimeouts"]);
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
  resolveReviewTimeouts(value.reviewTimeouts, value.remoteFallback !== undefined);
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
  plan?: NativeSettingsSnapshot["reviewContext"][string], reviewSummary = ""): Promise<boolean> {
  if (!ctx.hasUI || signal?.aborted) return false;
  try {
    const title = `Allow ${toolName}?\nreason: ${reasonCode}\n` +
      (contextReason ? `context: ${contextReason}\n` : "") + `cwd: ${JSON.stringify(redactSensitive(cwd))}\n` +
      `command: ${JSON.stringify(redactSensitive(command))}` + worktreeSummary(plan) + (reviewSummary ? "\n" + reviewSummary : "");
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
  const timing = safeAttempts({ status: "failure", primary: attempt })[0]?.timing;
  return { configured: safeIdentity(configured) ?? "unsafe-or-unavailable",
    actualModel: attempt.model ? safeIdentity(`${attempt.model.provider}/${attempt.model.id}`) : undefined,
    calls: attempt.called ? 1 : 0, health: attempt.status === "valid" ? "ready" : attempt.health,
    ...(attempt.status === "failure" ? { failureCode: attempt.failureCode,
      ...(attempt.httpStatus !== undefined ? { httpStatus: attempt.httpStatus } : {}) } : {}),
    ...(timing ? { timing } : {}) };
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

function liveCwd(ctx: ExtensionContext): string {
  // 官方ctx.cwd是创建时快照；等待审批时需通过公开SessionManager重查。
  return typeof ctx.sessionManager.getCwd === "function" ? ctx.sessionManager.getCwd() : ctx.cwd;
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
  if (!exactKeys(value, PLAIN_BASH_KEYS) || ![Object.prototype, null].includes(Object.getPrototypeOf(value)) ||
      Reflect.ownKeys(value).some(key => typeof key !== "string") ||
      Object.values(Object.getOwnPropertyDescriptors(value)).some(d => !("value" in d) || !d.enumerable) ||
      typeof value.command !== "string" || value.command.length === 0 ||
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
    const limits = lifecycleLimits(dependencies.lifecycle);
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
    const seenToolCallIds = new Set<string>();
    const running = new Set<AbortController>();
    const state: State = {
      mode: "manual", generation: 0, pending: new Set(),
      primary: { configured: "unavailable", calls: 0, health: "unavailable" },
      remote: { configured: "disabled", calls: 0, health: "unavailable" },
      human: { calls: 0, health: "idle" },
      native: { calls: 0, delegateCalls: 0, delegateAvailable: null, scopedSettingsReady: false,
        coverage: initialConfig?.nativeBash === true ? (nativeRegistered ? "initializing" : "unavailable") : "disabled",
        unsupported: nativeLoadFailed ? ["native-runtime-load"] :
          ["async", "service", "pty"] },
      last: { outcome: "unavailable", source: "none", reasonCode: "NOT_REVIEWED", chain: [] },
    };
    const audit = createApprovalAudit(typeof omp.appendEntry === "function" ? (type, data) => omp.appendEntry(type, data) : undefined);
    const pendingDiagnostics = new Map<AbortController, ApprovalDiagnostic>();
    const runningDiagnostics = new Map<AbortController, ApprovalDiagnostic>();
    let modelQueue = new ApprovalQueue(limits.reviewConcurrency);
    let humanQueue = new ApprovalQueue(1);

    const observationSessionId = (ctx: ExtensionContext): string | undefined => {
      try { return ctx.sessionManager.getSessionId(); } catch { return undefined; }
    };

    const invalidate = () => {
      for (const call of pendingDiagnostics.values()) {
        call.invalidated = true; call.gates("INVALIDATED", "CANCELLED");
      }
      abortPending(state); state.generation++;
      // 新代不等旧检查的 opaque Promise；旧 permit 只释放自己的队列。
      modelQueue = new ApprovalQueue(limits.reviewConcurrency);
      humanQueue = new ApprovalQueue(1);
    };

    const askHuman = async (ctx: ExtensionContext, toolName: string, command: string, cwd: string,
      reasonCode: string, signal: AbortSignal, diagnostic?: ApprovalDiagnostic,
      contextReason?: NativeDiagnostics["contextReason"], plan?: NativeSettingsSnapshot["reviewContext"][string], review?: ReviewSequenceResult) => {
      diagnostic?.phase("human-queued");
      const release = await humanQueue.acquire(signal, limits.queueTimeoutMs);
      try {
        diagnostic?.phase("human");
        return await waitFor(() => humanApprove(ctx, toolName, command, cwd, reasonCode, signal, contextReason, plan, reviewFailureSummary(review)), signal);
      } finally { release(); }
    };

    const approve = async (params: PlainBashParams, ctx: ExtensionContext, signal: AbortSignal,
      toolName: "bash" | "permission_bash", native?: NativeSettingsSnapshot,
      diagnostic?: ApprovalDiagnostic): Promise<ApprovalOutcome> => {
      if (!config) { diagnostic?.gates("CONFIG_UNAVAILABLE"); return { approved: false, source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] }; }
      // raw shell 不执行宿主 clone 重写；保留其旧人工边界，不借用原生计划宣称效果。
      if (toolName === "permission_bash" && (native?.reviewContext.worktreePlan || native?.reviewContext.unverifiedWorktreeEffects)) {
        const { worktreePlan: _plan, unverifiedWorktreeEffects: _unverified, ...reviewContext } = native.reviewContext;
        native = { ...native, reviewContext,
          bindingSupported: native.bindingSupported !== false && native.reasonCode !== "UNSUPPORTED_EXECUTION_CONTEXT",
          decision: native.decision === "deny" ? "deny" : "prompt",
          reasonCode: native.decision === "allow" ? "NATIVE_PROMPT" : native.reasonCode,
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
      const unsupportedContext = native?.bindingSupported === false || native?.reasonCode === "UNSUPPORTED_EXECUTION_CONTEXT";
      const nativePrompt = native?.decision === "prompt" && native.reasonCode === "NATIVE_PROMPT";
      const needsHuman = state.mode === "manual" || configuredGate === "prompt" || nativePrompt;
      diagnostic?.gates(...(state.mode === "manual" ? ["MANUAL_MODE"] : []),
        ...(configuredGate === "prompt" ? ["CONFIGURED_PROMPT"] : []), ...(nativePrompt ? ["NATIVE_PROMPT"] : []));
      const prepared = prepareReviewPacket({ command: params.command, cwd, userMessages: messages,
        parameters: { cwd: params.cwd, timeout: params.timeout },
        executionContext: { entrypoint: toolName, baseCwd: ctx.cwd, ...(native?.reviewContext ?? {}),
          shellFamily: toolName === "permission_bash" ? "bash" : typeof native?.reviewContext.shellFamily === "string" ? native.reviewContext.shellFamily : "unknown",
          shellAnalysis: { status: rules.analysis },
          ...(config.nativePatterns.length ? { configuredRules: config.nativePatterns.map((rule, id) => ({
            id, match: rule.match, approval: rule.approval, uncertain: rules.uncertainRuleIds.includes(id) })) } : {}) } });
      if (prepared.status === "ready") diagnostic?.input(prepared.packet);
      else diagnostic?.gates(prepared.reasonCode);
      if (prepared.status === "invalid") return { approved: false, source: "none", reasonCode: "INPUT_INVALID", chain: [] };
      if (needsHuman) {
        if (unsupportedContext) {
          diagnostic?.gates("UNSUPPORTED_NATIVE_CONTEXT");
          return { approved: false, source: "native", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: ["native"] };
        }
        const reasonCode = nativePrompt ? "NATIVE_PROMPT" : "USER_CONFIRMATION_REQUIRED";
        const chain: ApprovalOutcome["chain"] = nativePrompt || configuredGate === "prompt" ? ["native", "human"] : ["human"];
        state.human.calls++;
        state.last = { outcome: "pending-human", source: "human", reasonCode, chain };
        diagnostic?.approval(state.last);
        if (diagnostic) diagnostic.routingComplete = true;
        const humanGeneration = state.generation;
        const approved = await askHuman(ctx, toolName, params.command, cwd, reasonCode, signal, diagnostic,
          nativeDiagnostics(native)?.contextReason, native?.reviewContext.worktreePlan ?? native?.reviewContext.unverifiedWorktreeEffects);
        if (state.generation === humanGeneration && !signal.aborted)
          state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
        return { approved, source: "human", reasonCode, chain };
      }
      state.last = { outcome: "reviewing", source: "none", reasonCode: "REVIEW_PENDING", chain: [] };
      const reviewMode = state.mode, reviewGeneration = state.generation, reviewSession = ctx.sessionManager.getSessionId();
      const reviewCwd = ctx.cwd, reviewAuthorization = JSON.stringify(messages);
      const isCurrent = () => !signal.aborted && state.mode === reviewMode && state.generation === reviewGeneration &&
        ctx.cwd === reviewCwd && liveCwd(ctx) === reviewCwd && ctx.sessionManager.getSessionId() === reviewSession && authorizationSignature(ctx) === reviewAuthorization;
      const runtime = { ...reviewRuntime(ctx, dependencies.fetch ?? globalThis.fetch), isCurrent,
        deadlines: resolveReviewTimeouts(config.reviewTimeouts, config.remoteFallback !== undefined) };
      let result: ReviewSequenceResult;
      if (prepared.status === "ready") {
        diagnostic?.phase("review-queued");
        const release = await modelQueue.acquire(signal, limits.queueTimeoutMs);
        try {
          diagnostic?.phase("reviewing");
          if (diagnostic) diagnostic.reviewStarted = true;
          result = await reviewCommand(prepared.packet, { reviewer: config.reviewer, remoteFallback: config.remoteFallback }, runtime, signal);
        } finally { release(); }
      } else result = { status: prepared.status === "input-too-large" ? "input-too-large" : "failure",
        primary: { status: "failure", called: false, health: "invalid", failureCode: prepared.reasonCode } };
      diagnostic?.review(result);
      if (!isCurrent()) return { approved: false, source: "none", reasonCode: signal.aborted ? "CANCELLED" : "STALE_REVIEW",
        chain: ["primary", ...(result.remote ? ["remote" as const] : [])] };
      const chain = recordReview(state, config, result);
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
      diagnostic?.approval(state.last);
      const approved = await askHuman(ctx, toolName, params.command, cwd, reasonCode, signal, diagnostic,
        nativeDiagnostics(native)?.contextReason, native?.reviewContext.worktreePlan ?? native?.reviewContext.unverifiedWorktreeEffects, result);
      if (isCurrent()) state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
      return { approved, source: "human", reasonCode,
        chain: [...chain, "human"] };
    };

    const reset = async (_event: unknown, ctx: ExtensionContext) => {
      invalidate();
      const resetGeneration = state.generation;
      // 按session分区的消费记录贯穿插件生命；A→B→A不能重放A中的旧调用。
      try {
        const next = await load();
        if (state.generation !== resetGeneration) return;
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
        if (state.generation !== resetGeneration) return;
        config = undefined; state.mode = "manual";
        state.native.diagnostics = undefined;
        state.primary = { configured: "unavailable", calls: 0, health: "unavailable" };
        state.remote = { configured: "disabled", calls: 0, health: "unavailable" };
        state.native.coverage = nativeRegistered ? "unavailable" : "disabled";
        state.last = { outcome: "blocked", source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] };
      }
    };

    omp.on("session_start", reset); omp.on("session_switch", reset); omp.on("session_branch", reset);
    omp.on("session_shutdown", () => {
      invalidate();
      for (const controller of running) controller.abort();
    });

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
            reviewTimeouts: config ? resolveReviewTimeouts(config.reviewTimeouts, config.remoteFallback !== undefined) : undefined,
            entrypoints: { raw: "permission_bash", native: nativeRegistered ? "bash" : "disabled" },
            rawNativeCloneCoverage: "not-applicable-raw-shell",
            coverage: state.native.coverage, nativeDelegateAvailable: state.native.delegateAvailable,
            scopedSettingsReady: state.native.scopedSettingsReady, unsupported: state.native.unsupported,
            nativeContext: state.native.diagnostics,
            nativeCalls: state.native.calls, nativeDelegateCalls: state.native.delegateCalls,
            primary: state.primary, remote: state.remote, human: state.human,
            fallback: config?.fallback ? "unavailable" : "disabled", pending: state.pending.size, running: running.size, queues: { model: modelQueue.status, human: humanQueue.status },
            audit: { accepted: audit.state.accepted, failed: audit.state.failed, health: audit.state.health,
              durability: audit.state.durability }, diagnostic: audit.state.last,
            nativeProtection: "configured-patterns-plus-public-native-bash-approval" }), "info");
        } else if (command === "explain") {
          const active = [...pendingDiagnostics.values(), ...runningDiagnostics.values()]
            .filter(call => !call.invalidated && !call.done).sort((a, b) => a.data.sequence - b.data.sequence).at(-1);
          ctx.ui.notify(JSON.stringify(active ? active.current : audit.state.last ? {
          outcome: audit.state.last.outcome, source: audit.state.last.source, reasonCode: audit.state.last.reasonCode,
          chain: audit.state.last.chain, nativeContext: audit.state.last.nativeContext, diagnostic: audit.state.last,
        } : { ...state.last, nativeContext: state.native.diagnostics }), "info");
        }
        else ctx.ui.notify("/permission-control smart\n/permission-control manual\n/permission-control status\n/permission-control explain", "info");
      },
    });

    const Type = omp.typebox.Type;
    const parameters = Type.Object({ command: Type.String(), cwd: Type.Optional(Type.String()),
      timeout: Type.Optional(Type.Number({ minimum: 0 })) }, { additionalProperties: true });

    // 该钩子不等待 capture、模型或 UI；长期审批属于 execute 的生命周期。
    if (nativeRegistered) omp.on("tool_call", (event, ctx) => {
      if (event.toolName !== "bash" && event.toolName !== "permission_bash") return undefined;
      const params = plainBashParams(event.input);
      if (config && params && (event.toolName !== "permission_bash" || params.timeout === undefined || params.timeout <= 120)) return undefined;
      const diagnostic = audit.begin(event.toolCallId, event.toolName, state.mode, state.generation, observationSessionId(ctx));
      diagnostic.gates(config ? "INVALID_PARAMETERS" : "CONFIG_UNAVAILABLE");
      audit.finish(diagnostic, "hook", "blocked", config ? "UNSUPPORTED_EXECUTION_CONTEXT" : "CONFIG_UNAVAILABLE");
      return { block: true, reason: config ? "unsupported bash execution parameters" : "permission configuration unavailable" };
    });

    const execute = async (toolName: "bash" | "permission_bash", toolCallId: string,
      rawParams: unknown, signal: AbortSignal | undefined, onUpdate: any, ctx: ExtensionContext) => {
      const diagnostic = audit.begin(toolCallId, toolName, state.mode, state.generation, observationSessionId(ctx));
      const parsed = plainBashParams(rawParams);
      if (!config || !parsed || (toolName === "permission_bash" && parsed.timeout !== undefined && parsed.timeout > 120)) {
        diagnostic.gates(config ? "INVALID_PARAMETERS" : "CONFIG_UNAVAILABLE");
        audit.finish(diagnostic, "execute", "blocked", "INVALID_OR_UNAVAILABLE");
        return textResult(`${toolName} blocked`, { reasonCode: "INVALID_OR_UNAVAILABLE" }, true);
      }
      const params = Object.freeze({ ...parsed });
      const parameterSignature = signature(params);
      let stamp: RequestStamp;
      try {
        stamp = { generation: state.generation, mode: state.mode, sessionId: ctx.sessionManager.getSessionId(),
          model: modelIdentity(ctx.models.current()), baseCwd: ctx.cwd, authorization: authorizationSignature(ctx) ?? "" };
      } catch {
        diagnostic.gates("STALE_REVIEW"); audit.finish(diagnostic, "execute", "blocked", "STALE_REVIEW");
        return textResult(`${toolName} blocked`, { reasonCode: "STALE_REVIEW" }, true);
      }
      const key = JSON.stringify([stamp.sessionId, toolCallId]);
      if (!toolCallId || seenToolCallIds.has(key)) {
        diagnostic.gates("DUPLICATE_TICKET"); audit.finish(diagnostic, "execute", "blocked", "DUPLICATE_TOOL_CALL");
        return textResult(`${toolName} blocked`, { reasonCode: "DUPLICATE_TOOL_CALL" }, true);
      }
      // 入口占位同时防并发重入；失败/取消后的同一调用也不能被隐式重放。
      seenToolCallIds.add(key);
      const pending = new AbortController();
      const combined = signal ? AbortSignal.any([signal, pending.signal]) : pending.signal;
      state.pending.add(pending); pendingDiagnostics.set(pending, diagnostic);
      if (nativeRegistered) state.native.calls++;
      let executing = false;
      let hasSnapshot = false;
      let executionController: AbortController | undefined;
      let outcome: ApprovalOutcome | undefined;
      let cancelReason = "CANCELLED";
      const current = () => {
        const actual = plainBashParams(rawParams);
        return !combined.aborted && state.generation === stamp.generation && state.mode === stamp.mode &&
          ctx.sessionManager.getSessionId() === stamp.sessionId && ctx.cwd === stamp.baseCwd && liveCwd(ctx) === stamp.baseCwd &&
          modelIdentity(ctx.models.current()) === stamp.model && authorizationSignature(ctx) === stamp.authorization &&
          actual !== undefined && signature(actual) === parameterSignature;
      };
      const monitor = setInterval(() => {
        try { if (!current()) { cancelReason = "STALE_REVIEW"; pending.abort(); } }
        catch { cancelReason = "STALE_REVIEW"; pending.abort(); }
      }, limits.pollIntervalMs);
      const updateLast = (value: State["last"]) => {
        if (state.generation === stamp.generation) state.last = value;
      };
      const blocked = (reasonCode: string, cancelled = combined.aborted) => {
        const source = outcome?.source ?? "none", chain = outcome?.chain ?? [];
        updateLast({ outcome: "blocked", source, reasonCode, chain });
        audit.finish(diagnostic, "execute", cancelled ? "cancelled" : "blocked", reasonCode);
        return textResult(`${toolName} blocked`, { reasonCode }, true);
      };
      try {
        if (!current()) { diagnostic.gates("STALE_REVIEW"); return blocked("STALE_REVIEW"); }
        let snapshot: NativeSettingsSnapshot | undefined;
        if (nativeRuntime && config.nativeBash === true) {
          diagnostic.phase("capture");
          snapshot = await waitFor(() => nativeRuntime!.capture(stamp.baseCwd, params), combined, limits.contextTimeoutMs);
          hasSnapshot = true;
          if (!current()) return blocked("STALE_REVIEW");
          state.native.scopedSettingsReady = true;
        }
        outcome = await approve(params, ctx, combined, toolName, snapshot, diagnostic);
        diagnostic.approval(outcome);
        if (!outcome.approved) return blocked(outcome.reasonCode);
        if (!current()) return blocked("STALE_REVIEW");
        if (snapshot) {
          diagnostic.phase("recheck");
          const checked = await waitFor(() => nativeRuntime!.recheck(snapshot!.settings, stamp.baseCwd, params),
            combined, limits.contextTimeoutMs);
          diagnostic.context(nativeDiagnostics(checked));
          if (checked.fingerprint !== snapshot.fingerprint || checked.decision !== snapshot.decision ||
              checked.bindingSupported === false || checked.reasonCode === "UNSUPPORTED_EXECUTION_CONTEXT") {
            diagnostic.gates("STALE_REVIEW"); return blocked("STALE_REVIEW");
          }
        }
        if (!current()) { diagnostic.gates("STALE_REVIEW"); return blocked("STALE_REVIEW"); }
        const cwd = effectiveCwd(stamp.baseCwd, params.cwd);
        if (!cwd) { diagnostic.gates("INVALID_PARAMETERS"); return blocked("UNSUPPORTED_EXECUTION_CONTEXT"); }
        if (toolName === "bash" && !ctx.invokeTool) {
          state.native.delegateAvailable = false; diagnostic.gates("NATIVE_DELEGATE_UNAVAILABLE");
          return blocked("NATIVE_DELEGATE_UNAVAILABLE");
        }
        // 不含 await 的消费边界：模式撤销仅影响尚未消费的操作。
        clearInterval(monitor); state.pending.delete(pending); pendingDiagnostics.delete(pending);
        executing = true; executionController = new AbortController(); running.add(executionController);
        runningDiagnostics.set(executionController, diagnostic);
        const executionSignal = signal ? AbortSignal.any([signal, executionController.signal]) : executionController.signal;
        diagnostic.phase("executing");
        if (toolName === "bash") {
          state.native.delegateAvailable = true; state.native.delegateCalls++;
          const result = await ctx.invokeTool!(rawParams as Record<string, unknown>, { signal: executionSignal, onUpdate });
          if (state.generation === stamp.generation) state.native.coverage = "ready";
          updateLast({ outcome: result.isError === true ? "failed" : "executed", source: outcome.source,
            reasonCode: outcome.reasonCode, chain: outcome.chain });
          audit.finish(diagnostic, "execute", result.isError === true ? "failed" : "executed",
            result.isError === true ? "NATIVE_RESULT_ERROR" : undefined);
          return result;
        }
        const result = await omp.exec("bash", ["--noprofile", "--norc", "-c", params.command], {
          cwd, signal: executionSignal, timeout: params.timeout === undefined ? undefined : params.timeout * 1000,
        });
        updateLast({ outcome: result.code === 0 ? "executed" : "failed", source: outcome.source,
          reasonCode: outcome.reasonCode, chain: outcome.chain });
        audit.finish(diagnostic, "execute", result.code === 0 ? "executed" : "failed", result.code === 0 ? undefined : "RAW_EXECUTION_FAILED");
        const output = [result.stdout, result.stderr].filter(Boolean).map(boundedOutput).join("\n");
        return textResult(output || `(exit ${result.code})`, { code: result.code, killed: result.killed }, result.code !== 0);
      } catch (error) {
        if (executing) {
          const cancelled = executionController?.signal.aborted === true || signal?.aborted === true;
          const reasonCode = toolName === "bash" ? "NATIVE_EXECUTION_FAILED" : "RAW_EXECUTION_FAILED";
          updateLast({ outcome: cancelled ? "cancelled" : "failed", source: outcome?.source ?? "native",
            reasonCode, chain: outcome?.chain ?? ["native"] });
          audit.finish(diagnostic, "execute", cancelled ? "cancelled" : "failed", reasonCode);
          if (toolName === "bash") throw error;
          return textResult("permission_bash execution failed", { reasonCode }, true);
        }
        const reason = error instanceof LifecycleFailure
          ? error.reasonCode === "CANCELLED" ? cancelReason : error.reasonCode
          : combined.aborted ? cancelReason : "SCOPED_SETTINGS_UNAVAILABLE";
        if (!executing && state.generation === stamp.generation) {
          state.native.scopedSettingsReady = false;
          if (!hasSnapshot) state.native.diagnostics = undefined;
        }
        diagnostic.gates(reason); return blocked(reason);
      } finally {
        clearInterval(monitor); state.pending.delete(pending); pendingDiagnostics.delete(pending);
        if (executionController) { running.delete(executionController); runningDiagnostics.delete(executionController); }
        if (!diagnostic.done) audit.finish(diagnostic, "execute", combined.aborted ? "cancelled" : "blocked", "CANCELLED");
      }
    };

    if (nativeRegistered) omp.registerTool({
      name: "bash", label: "Bash", description: "Run native Bash after standalone permission review.",
      approval: { tier: "exec", policyKey: "permission_bash" }, loadMode: "essential", parameters,
      execute: (id, params, signal, onUpdate, ctx) => execute("bash", id, params, signal, onUpdate, ctx),
    });
    omp.registerTool({
      name: "permission_bash", label: "Permission Bash",
      description: "Run raw non-interactive Bash after standalone permission review. Service, job, PTY, and native Bash behavior are separate.",
      approval: { tier: "exec", policy: "allow" }, loadMode: "essential", parameters,
      execute: (id, params, signal, onUpdate, ctx) => execute("permission_bash", id, params, signal, onUpdate, ctx),
    });
  };
}

export default createStandalonePlugin();
