import { createHash } from "node:crypto";
import type { PolicyAssessment, PolicyReasonCode, PolicySource } from "./policy";
import type { ModelReview } from "./reviewer";
import { REVIEW_REASONS } from "./reviewer";
import type { NativeReviewer, PermissionMode } from "./types";

export interface ReviewerModel { provider: string; id: string; api: string }
export interface ReviewerSelection {
  state: "ready" | "unavailable" | "unsupported";
  source: "explicit-profile" | "session-default";
  model?: Readonly<ReviewerModel>;
}
/** registry 的凭据和其它任意字段不复制到选定模型身份。 */
export function selectReviewer(configured: "session" | NativeReviewer,
    sessionModel: ReviewerModel | undefined, selectedModels: readonly ReviewerModel[]): Readonly<ReviewerSelection> {
  const source = configured === "session" ? "session-default" : "explicit-profile";
  const requested = configured === "session" ? sessionModel : { provider: configured.provider, id: configured.model };
  if (!requested) return Object.freeze({ state: "unavailable", source });
  const matches = selectedModels.filter(model => model.provider === requested.provider && model.id === requested.id);
  if (matches.length !== 1) return Object.freeze({ state: "unavailable", source });
  const { provider, id, api } = matches[0];
  if (![provider, id, api].every(value => typeof value === "string" && value.length > 0 &&
    value.length <= 256 && !/[\s\u0000-\u001f]/u.test(value))) return Object.freeze({ state: "unavailable", source });
  if (!["anthropic-messages", "openai-completions"].includes(api)) return Object.freeze({ state: "unsupported", source });
  return Object.freeze({ state: "ready", source, model: Object.freeze({ provider, id, api }) });
}

/** 本模块由构建器嵌入宿主；实例仅由宿主持有，不交给扩展或模型。 */
export interface ExecutionBinding {
  request_id: string;
  session_id: string;
  generation: number;
  prepared_execution_id: object;
  execution_ref: object;
  execution_digest: string;
  operation_digest: string;
  argv_digest: string;
  cwd: string;
  shell_digest: string;
  backend: string;
  target_digest: string;
  authorization_digest: string;
  mode: PermissionMode;
  policy_version: string;
  reviewer_identity: string;
  plugin_digest: string;
  runtime_identity: string;
  health_digest: string;
}
export type InvalidReason = "cancelled" | "mode-changed" | "binding-changed" |
  "authorization-changed" | "model-changed" | "policy-changed" | "health-changed" |
  "session-changed" | "request-edited" | "disposed";
export type HealthResult = "healthy" | "degraded" | "unavailable";
export interface PermissionDecision {
  readonly decision_id: string;
  readonly request_id: string;
  readonly outcome: "allow" | "ask" | "deny";
  readonly source: PolicySource;
  readonly reason_code: PolicyReasonCode;
  readonly model_result?: ModelReview;
  readonly actual_model: string;
  readonly model_source: "not-called" | "explicit" | "session-default" | "remote-fallback" | "fallback";
  readonly fallback_result?: "ask" | "deny";
  readonly health_result: HealthResult;
  readonly created_at_monotonic: number;
}
export interface HumanDecision {
  readonly human_decision_id: string;
  readonly ask_decision_id: string;
  readonly request_id: string;
  readonly outcome: "allow" | "deny";
  readonly source: "human";
  readonly generation: number;
  readonly binding_digest: string;
}
export interface ExecutionPermit {
  readonly permit_id: string;
  readonly request_id: string;
  readonly decision_id: string;
  readonly grant_source: "automatic" | "human";
  readonly ask_decision_id?: string;
  readonly human_decision_id?: string;
  readonly binding_digest: string;
  readonly state: "pending" | "consumed" | "invalidated";
  readonly invalid_reason?: InvalidReason;
}
export interface RequestHandle {
  readonly request_id: string;
  readonly signal: AbortSignal;
}
interface RequestRecord {
  binding: Readonly<ExecutionBinding>;
  digest: string;
  abort: AbortController;
  decision?: PermissionDecision;
  human?: HumanDecision;
  permit?: ExecutionPermit;
  cleanup: () => void;
}
interface PermitRecord {
  request: RequestHandle;
  state: ExecutionPermit["state"];
  invalid_reason?: InvalidReason;
}
export interface DecisionDetails {
  model_result?: ModelReview;
  actual_model?: string;
  model_source?: "explicit" | "session-default" | "remote-fallback" | "fallback";
  fallback_result?: "ask" | "deny";
  health_result?: HealthResult;
}
export interface HostPermissionState {
  reviewer_selection: "session-default" | "explicit";
  reviewer: string | "unavailable";
  reviewer_state?: "ready" | "unavailable" | "unsupported";
  remote_fallback?: string | "unavailable";
  remote_fallback_state?: "disabled" | "ready" | "unavailable" | "unhealthy";
  fallback_state: "disabled" | "ready" | "unavailable" | "unhealthy";
  bridge_health: HealthResult;
  identity_verified: boolean;
  policy_version: string;
  native_protection: { bashPrompt: boolean; denyPreserved: boolean; commandPromptPreserved: boolean;
    criticalSafetyPreserved: boolean; taskPrompt: boolean; evalPrompt: boolean; noYolo: boolean };
  coverage: { tool: "bash"; session: "main"; shell: "bash"; platform: "linux";
    backend: "native"; execution: "foreground"; eligible: boolean; reasons: readonly CoverageReason[] };
}
export const COVERAGE_REASONS = ["direnv", "devenv", "prefix", "service", "async", "pty", "acp-terminal",
  "use-user-shell", "startup-script", "bash-env", "exported-function", "internal-url", "worktree-rewrite",
  "interceptor", "auto-background", "persistent-shell-state", "non-native-backend", "cold-initialization",
  "unverified-shell-state", "plugin-unavailable", "unknown-target"] as const;
export type CoverageReason = typeof COVERAGE_REASONS[number];
export interface SessionPermissionState extends HostPermissionState {
  session_id: string;
  generation: number;
  configured_mode: PermissionMode;
  active_mode: PermissionMode;
  mode_source: "profile-default" | "session-command";
  last_decision_id?: string;
  pending_permit_id?: string;
  pending: "none" | "reviewing" | "awaiting-human" | "permitted";
}
function defaultHostState(): HostPermissionState {
  return freeze({ reviewer_selection: "session-default", reviewer: "unavailable", reviewer_state: "unavailable",
    fallback_state: "disabled",
    bridge_health: "unavailable", identity_verified: false, policy_version: "unavailable",
    native_protection: { bashPrompt: false, denyPreserved: false, commandPromptPreserved: false,
      criticalSafetyPreserved: false, taskPrompt: false, evalPrompt: false, noYolo: false },
    coverage: { tool: "bash", session: "main", shell: "bash", platform: "linux", backend: "native",
      execution: "foreground", eligible: false, reasons: ["plugin-unavailable"] } });
}
function invalid(): never { throw new Error("PERMISSION_REQUEST_INVALID"); }
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
const HASH_FIELDS = ["execution_digest", "operation_digest", "argv_digest", "shell_digest",
  "target_digest", "authorization_digest", "policy_version", "plugin_digest", "health_digest"] as const;
const TEXT_FIELDS = ["request_id", "session_id", "cwd", "backend", "reviewer_identity", "runtime_identity"] as const;
const INVALID_REASONS = new Set<InvalidReason>(["cancelled", "mode-changed", "binding-changed",
  "authorization-changed", "model-changed", "policy-changed", "health-changed", "session-changed",
  "request-edited", "disposed"]);
const SOURCES = new Set<PolicySource>(["hard-rule", "low-risk-rule", "reviewer", "remote-fallback", "fallback",
  "manual-boundary", "native-protection", "system-failure"]);
const REASONS = new Set<string>([...REVIEW_REASONS, "DETERMINISTIC_LOW_RISK"]);

export class PermissionLedger {
  #generation = 0;
  #mode: PermissionMode;
  #requests = new WeakMap<RequestHandle, RequestRecord>();
  #permits = new WeakMap<ExecutionPermit, PermitRecord>();
  #identities = new WeakMap<object, string>();
  #active = new Set<RequestHandle>();
  #requestIds = new Set<string>();
  #pending?: ExecutionPermit;
  #queue: Promise<void> = Promise.resolve();
  #processing = new Set<AbortController>();
  #disposed = false;
  #modeSource: SessionPermissionState["mode_source"] = "profile-default";
  #host = defaultHostState();
  #last?: RequestHandle;
  constructor(readonly sessionId: string, readonly configuredMode: PermissionMode,
      private readonly clock: () => number = () => performance.now()) {
    if (!sessionId || (configuredMode !== "smart" && configuredMode !== "manual")) invalid();
    this.#mode = configuredMode;
  }
  get generation(): number { return this.#generation; }
  get mode(): PermissionMode { return this.#mode; }
  get pendingPermit(): ExecutionPermit | undefined { return this.#pending; }
  hostState(): Readonly<HostPermissionState> { return this.#host; }
  /** 只由宿主更新：状态查询自身不会解析模型、探测 tiny 或读取环境。 */
  setHostState(value: HostPermissionState): void {
    const next = structuredClone(value);
    const exact = (value: object, names: readonly string[]) => value !== null && typeof value === "object" &&
      Object.keys(value).length === names.length && Object.keys(value).every(key => names.includes(key));
    const hostFields = ["reviewer_selection", "reviewer", "fallback_state", "bridge_health", "identity_verified",
      "policy_version", "native_protection", "coverage"];
    const hasRemote = Object.hasOwn(next, "remote_fallback") || Object.hasOwn(next, "remote_fallback_state");
    const hasReviewerState = Object.hasOwn(next, "reviewer_state");
    const optionalFields = [...(hasReviewerState ? ["reviewer_state"] : []),
      ...(hasRemote ? ["remote_fallback", "remote_fallback_state"] : [])];
    if (!exact(next, [...hostFields, ...optionalFields]) ||
      !exact(next.native_protection, ["bashPrompt", "denyPreserved", "commandPromptPreserved",
        "criticalSafetyPreserved", "taskPrompt", "evalPrompt", "noYolo"]) ||
      !exact(next.coverage, ["tool", "session", "shell", "platform", "backend", "execution", "eligible", "reasons"])) invalid();
    if (!["session-default", "explicit"].includes(next.reviewer_selection) ||
        typeof next.reviewer !== "string" || !next.reviewer ||
        (hasReviewerState && !["ready", "unavailable", "unsupported"].includes(next.reviewer_state!)) ||
        (hasRemote && (typeof next.remote_fallback !== "string" || !next.remote_fallback ||
          !["disabled", "ready", "unavailable", "unhealthy"].includes(next.remote_fallback_state!))) ||
        !["disabled", "ready", "unavailable", "unhealthy"].includes(next.fallback_state) ||
        !["healthy", "degraded", "unavailable"].includes(next.bridge_health) ||
        typeof next.identity_verified !== "boolean" ||
        !(next.policy_version === "unavailable" || next.policy_version.length === 64 && /^[a-f0-9]{64}$/u.test(next.policy_version)) ||
        Object.values(next.native_protection).some((item) => typeof item !== "boolean") ||
        next.coverage.tool !== "bash" || next.coverage.session !== "main" || next.coverage.shell !== "bash" ||
        next.coverage.platform !== "linux" || next.coverage.backend !== "native" || next.coverage.execution !== "foreground" ||
        typeof next.coverage.eligible !== "boolean" ||
        !Array.isArray(next.coverage.reasons) || new Set(next.coverage.reasons).size !== next.coverage.reasons.length ||
        !next.coverage.reasons.every((reason) => (COVERAGE_REASONS as readonly string[]).includes(reason))) invalid();
    if (JSON.stringify(this.#host) !== JSON.stringify(next)) {
      this.invalidate("health-changed");
      this.#host = freeze(next);
    }
  }
  snapshot(): Readonly<SessionPermissionState> {
    const last = this.#last && this.#requests.get(this.#last);
    const awaitingHuman = [...this.#active].some((handle) => {
      const record = this.#requests.get(handle)!;
      return record.decision?.outcome === "ask" && !record.human && !record.abort.signal.aborted;
    });
    return freeze({ ...this.#host, session_id: this.sessionId, generation: this.#generation,
      configured_mode: this.configuredMode, active_mode: this.#mode, mode_source: this.#modeSource,
      ...(last?.decision ? { last_decision_id: last.decision.decision_id } : {}),
      ...(this.#pending ? { pending_permit_id: this.#pending.permit_id } : {}),
      pending: this.#pending ? "permitted" : awaitingHuman ? "awaiting-human" :
        this.#processing.size > 0 ? "reviewing" : "none" });
  }
  explain(): Readonly<Record<string, unknown>> {
    const record = this.#last && this.#requests.get(this.#last);
    if (!record?.decision) return Object.freeze({ state: "no-decision-in-session" });
    const decision = record.decision;
    const permit = record.permit;
    const human = record.human;
    return freeze({ requestId: decision.request_id, decisionId: decision.decision_id,
      outcome: decision.outcome, source: decision.source, reasonCode: decision.reason_code,
      mode: record.binding.mode, policyVersion: record.binding.policy_version,
      operationDigest: record.binding.operation_digest.slice(0, 12), actualModel: decision.actual_model,
      modelSource: decision.model_source, health: decision.health_result,
      fallback: decision.fallback_result ?? "not-called",
      ...(decision.fallback_result ? { fallbackLimit: "ask-or-deny-only; installed-only; never-allow" } : {}),
      ...(human ? { human: { askDecisionId: human.ask_decision_id, humanDecisionId: human.human_decision_id,
        outcome: human.outcome, source: "human" }, chain: `ask → human ${human.outcome}` } : {}),
      permit: permit ? { permitId: permit.permit_id, state: permit.state,
        ...(permit.invalid_reason ? { invalidReason: permit.invalid_reason } : {}) } : "none" });
  }
  #identity(value: object): string {
    if (!value || typeof value !== "object") return invalid();
    let identity = this.#identities.get(value);
    if (!identity) { identity = crypto.randomUUID(); this.#identities.set(value, identity); }
    return identity;
  }
  #digest(binding: ExecutionBinding): string {
    if (TEXT_FIELDS.some((key) => typeof binding[key] !== "string" || !binding[key]) ||
        HASH_FIELDS.some((key) => typeof binding[key] !== "string" || binding[key].length !== 64 ||
          !/^[a-f0-9]{64}$/u.test(binding[key])) ||
        binding.session_id !== this.sessionId || binding.generation !== this.#generation ||
        binding.mode !== this.#mode || !Number.isSafeInteger(binding.generation)) invalid();
    const fields: Record<string, unknown> = {};
    for (const key of [...TEXT_FIELDS, ...HASH_FIELDS]) fields[key] = binding[key];
    fields.generation = binding.generation;
    fields.mode = binding.mode;
    fields.prepared_execution_id = this.#identity(binding.prepared_execution_id);
    fields.execution_ref = this.#identity(binding.execution_ref);
    return createHash("sha256").update(JSON.stringify(fields)).digest("hex");
  }
  #live(handle: RequestHandle): RequestRecord {
    const record = this.#requests.get(handle);
    if (this.#disposed || !record || record.abort.signal.aborted ||
        record.binding.generation !== this.#generation || record.binding.mode !== this.#mode) invalid();
    return record;
  }
  beginRequest(binding: ExecutionBinding, signal?: AbortSignal): RequestHandle {
    if (this.#disposed || signal?.aborted || this.#requestIds.has(binding.request_id)) invalid();
    const digest = this.#digest(binding);
    const abort = new AbortController();
    const handle = Object.freeze({ request_id: binding.request_id, signal: abort.signal });
    const cancel = () => this.#cancelRequest(handle, "cancelled");
    this.#requests.set(handle, {
      binding: Object.freeze({ ...binding }), digest, abort,
      cleanup: () => signal?.removeEventListener("abort", cancel),
    });
    this.#active.add(handle);
    this.#requestIds.add(binding.request_id);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    return handle;
  }
  recordDecision(handle: RequestHandle,
      assessment: Pick<PolicyAssessment, "outcome" | "source" | "reason_code">,
      details: DecisionDetails = {}): PermissionDecision {
    const record = this.#live(handle);
    if (record.decision || !["allow", "ask", "deny"].includes(assessment.outcome) ||
        !SOURCES.has(assessment.source) || !REASONS.has(assessment.reason_code) ||
        (details.health_result !== undefined && !["healthy", "degraded", "unavailable"].includes(details.health_result)) ||
        (details.fallback_result !== undefined && !["ask", "deny"].includes(details.fallback_result)) ||
        (assessment.outcome === "allow" && (details.fallback_result !== undefined ||
          (details.health_result !== undefined && details.health_result !== "healthy")))) invalid();
    const called = details.actual_model !== undefined;
    if (called !== (details.model_source !== undefined) || (called && !details.actual_model) ||
        (details.model_source !== undefined && !["explicit", "session-default", "remote-fallback", "fallback"].includes(details.model_source))) invalid();
    const created = this.clock();
    if (!Number.isFinite(created) || created < 0) invalid();
    const decision: PermissionDecision = freeze({
      decision_id: crypto.randomUUID(), request_id: handle.request_id,
      outcome: assessment.outcome as PermissionDecision["outcome"], source: assessment.source,
      reason_code: assessment.reason_code,
      ...(details.model_result === undefined ? {} : { model_result: structuredClone(details.model_result) }),
      actual_model: details.actual_model ?? "not-called", model_source: details.model_source ?? "not-called",
      ...(details.fallback_result === undefined ? {} : { fallback_result: details.fallback_result }),
      health_result: details.health_result ?? "healthy", created_at_monotonic: created,
    });
    record.decision = decision;
    this.#last = handle;
    return decision;
  }
  /** 仅宿主真实 UI 回调可调用；不暴露为扩展服务或模型工具。 */
  recordHuman(handle: RequestHandle, ask: PermissionDecision, outcome: "allow" | "deny",
      current: ExecutionBinding): HumanDecision {
    const record = this.#live(handle);
    if (record.human || record.decision !== ask || ask.outcome !== "ask" ||
        !["allow", "deny"].includes(outcome)) invalid();
    try {
      if (this.#digest(current) !== record.digest) invalid();
    } catch {
      this.#cancelRequest(handle, "binding-changed");
      return invalid();
    }
    const human: HumanDecision = Object.freeze({ human_decision_id: crypto.randomUUID(),
      ask_decision_id: ask.decision_id, request_id: handle.request_id, outcome, source: "human",
      generation: this.#generation, binding_digest: record.digest });
    record.human = human;
    return human;
  }
  createPermit(handle: RequestHandle, decision: PermissionDecision, human?: HumanDecision): ExecutionPermit {
    const record = this.#live(handle);
    if (this.#pending || record.permit || record.decision !== decision ||
        !(decision.outcome === "allow" && human === undefined || decision.outcome === "ask" &&
          human !== undefined && record.human === human && human.outcome === "allow")) invalid();
    const state: PermitRecord = { request: handle, state: "pending" };
    const permit: ExecutionPermit = Object.freeze({
      permit_id: crypto.randomUUID(), request_id: handle.request_id, decision_id: decision.decision_id,
      grant_source: human ? "human" : "automatic",
      ...(human ? { ask_decision_id: decision.decision_id, human_decision_id: human.human_decision_id } : {}),
      binding_digest: record.digest,
      get state() { return state.state; },
      get invalid_reason() { return state.invalid_reason; },
    });
    this.#permits.set(permit, state);
    this.#pending = record.permit = permit;
    return permit;
  }
  /** current 必须由宿主同步重新读取；start 只调用已经 stage 的 native 启动入口。 */
  consume<T>(permit: ExecutionPermit, current: ExecutionBinding, start: () => T): T {
    const state = this.#permits.get(permit);
    if (!state || state.state !== "pending" || this.#pending !== permit) invalid();
    let record: RequestRecord;
    try {
      record = this.#live(state.request);
      if (record.digest !== this.#digest(current) || record.permit !== permit) invalid();
    } catch {
      this.#cancelRequest(state.request, "binding-changed");
      return invalid();
    }
    state.state = "consumed";
    this.#pending = undefined;
    this.#active.delete(state.request);
    record.cleanup();
    // 不插入 await、hook、环境计算或日志回调；即使启动抛错也不恢复许可。
    return start();
  }
  #cancelRequest(handle: RequestHandle, reason: InvalidReason): void {
    const record = this.#requests.get(handle);
    if (!record) return;
    const permit = record.permit;
    const state = permit && this.#permits.get(permit);
    if (state?.state === "pending") {
      state.state = "invalidated"; state.invalid_reason = reason;
      if (this.#pending === permit) this.#pending = undefined;
    }
    this.#active.delete(handle);
    record.cleanup();
    record.abort.abort();
  }
  invalidate(reason: InvalidReason): void {
    if (!INVALID_REASONS.has(reason) || this.#generation >= Number.MAX_SAFE_INTEGER) invalid();
    this.#generation++;
    for (const handle of this.#active) this.#cancelRequest(handle, reason);
    for (const abort of this.#processing) abort.abort();
  }
  setMode(mode: PermissionMode): void {
    if (this.#disposed || (mode !== "smart" && mode !== "manual")) invalid();
    this.invalidate("mode-changed");
    this.#mode = mode;
    this.#modeSource = "session-command";
  }
  dispose(): void { this.#disposed = true; this.invalidate("disposed"); }
  async runSerialized<T>(operation: (signal: AbortSignal) => Promise<{ completion: Promise<T> }>,
      callerSignal?: AbortSignal): Promise<T> {
    const processing = this.#queue.then(async () => {
      if (this.#disposed || callerSignal?.aborted) invalid();
      const abort = new AbortController();
      this.#processing.add(abort);
      const cancel = () => abort.abort();
      callerSignal?.addEventListener("abort", cancel, { once: true });
      let rejectAbort!: () => void;
      const cancelled = new Promise<never>((_, reject) => {
        rejectAbort = () => reject(new Error("PERMISSION_REQUEST_INVALID"));
        abort.signal.addEventListener("abort", rejectAbort, { once: true });
      });
      try {
        const result = await Promise.race([operation(abort.signal), cancelled]);
        if (abort.signal.aborted) invalid();
        return result;
      } catch (error) {
        // 失败只撤销本次请求；成功启动后不触碰执行器可能仍持有的 signal。
        abort.abort();
        throw error;
      } finally {
        this.#processing.delete(abort);
        callerSignal?.removeEventListener("abort", cancel);
        abort.signal.removeEventListener("abort", rejectAbort);
      }
    });
    this.#queue = processing.then(() => {}, () => {});
    return (await processing).completion;
  }
}
