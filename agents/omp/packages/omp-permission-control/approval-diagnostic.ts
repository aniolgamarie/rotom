import { createHash } from "node:crypto";
import { CONTEXT_REASONS, SHELL_FAMILIES } from "./native-bash";
import { REVIEW_FAILURE_CODES, REVIEW_STAGES, REVIEW_TIMEOUT_SOURCES, TRANSPORT_CODES, type ReviewSequenceResult } from "./standalone-reviewer";
import type { SanitizedReviewPacket } from "./review-input";

export const AUDIT_TYPE = "permission-control.audit.v1";
export const GATE_CODES = ["CONFIG_UNAVAILABLE", "INVALID_PARAMETERS", "DUPLICATE_TICKET", "QUEUE_CANCELLED",
  "CONFIGURED_DENY", "NATIVE_DENY", "MANUAL_MODE", "CONFIGURED_PROMPT", "UNSUPPORTED_SYNTAX",
  "NATIVE_PROMPT", "UNSUPPORTED_STATUS_SEMANTICS", "UNSUPPORTED_NATIVE_CONTEXT", "NO_USER_MESSAGES", "SENSITIVE_INPUT", "INPUT_TOO_LARGE",
  "INVALID_TICKET", "STALE_REVIEW", "SCOPED_SETTINGS_UNAVAILABLE", "NATIVE_DELEGATE_UNAVAILABLE",
  "RUNTIME_FAILURE", "CANCELLED", "INVALIDATED", "INPUT_INVALID", "CONTEXT_TIMEOUT", "REVIEW_QUEUE_TIMEOUT"] as const;
const REASONS = ["LOW_RISK_AUTHORIZED", "USER_CONFIRMATION_REQUIRED", "NOT_AUTHORIZED", "CONFLICTING_AUTHORIZATION",
  "HIGH_RISK", "UNKNOWN_RISK", "CONFIG_UNAVAILABLE", "INVALID_OR_UNAVAILABLE", "DUPLICATE_TOOL_CALL",
  "UNSUPPORTED_EXECUTION_CONTEXT", "UNSUPPORTED_STATUS_SEMANTICS", "UNSUPPORTED_SYNTAX", "SCOPED_SETTINGS_UNAVAILABLE", "INVALID_TICKET",
  "STALE_REVIEW", "NATIVE_DELEGATE_UNAVAILABLE", "NATIVE_DENY", "NATIVE_PROMPT", "REVIEW_UNAVAILABLE",
  "NATIVE_EXECUTION_FAILED", "NATIVE_RESULT_ERROR", "RAW_EXECUTION_FAILED", "RUNTIME_FAILURE", "CANCELLED",
  "NOT_REVIEWED", "DIAGNOSTIC_UNKNOWN", "INPUT_INVALID", "RULE_TARGET_UNVERIFIED", "RULE_CONFIRMATION_REQUIRED",
  "CONTEXT_TIMEOUT", "REVIEW_QUEUE_TIMEOUT"] as const;
const PHASES = ["capture", "review-queued", "reviewing", "human-queued", "human", "recheck", "executing"] as const;
const SOURCES = ["none", "native", "human", "primary", "remote"] as const;
const DECISIONS = ["allow", "ask", "deny"] as const;
const RISKS = ["low", "medium", "high", "unknown"] as const;
const AUTHORIZATIONS = ["sufficient", "insufficient", "conflicting", "unknown"] as const;
const REVIEW_REASONS = ["LOW_RISK_AUTHORIZED", "USER_CONFIRMATION_REQUIRED", "NOT_AUTHORIZED",
  "CONFLICTING_AUTHORIZATION", "HIGH_RISK", "UNKNOWN_RISK"] as const;
const OUTCOMES = ["blocked", "cancelled", "executed", "failed", "approved"] as const;
const sensitive = /sk-|gh[opusr]_|AKIA|password|token|secret|canary|api[-_]?key/iu;

export function safeIdentity(value: unknown): string | undefined {
  return typeof value === "string" && /^[a-z0-9][a-z0-9._/:\-]{0,95}$/u.test(value) && !sensitive.test(value) && !value.includes("://") && !/^[a-f0-9]{32,}$/u.test(value)
    ? value : undefined;
}
export function toolCallIdDigest(value: unknown): string | null {
  if (typeof value !== "string" || value.length < 1 || value.length > 512) return null;
  return createHash("sha256").update("rotom.permission-control.toolCallId.v1\0").update(value, "utf8").digest("hex");
}
export function sessionIdDigest(value: unknown): string | null {
  if (typeof value !== "string" || !/^[A-Za-z0-9_.:-]{1,512}$/u.test(value)) return null;
  return createHash("sha256").update("rotom.permission-control.sessionId.v1\0").update(value, "utf8").digest("hex");
}
function safeCallId(value: unknown): string | null {
  return typeof value === "string" && /^(?:call_|toolu_|tool_)[A-Za-z0-9_-]{1,80}$/u.test(value) && !sensitive.test(value)
    ? value : null;
}
function one<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? value as T : fallback;
}
function ruleIds(value: unknown): number[] {
  return Array.isArray(value) ? [...new Set(value.filter(id => Number.isSafeInteger(id) && id >= 0 && id < 10000))].slice(0, 64) : [];
}
function analysis(value: any) {
  return value ? { status: one(value.status, ["complete", "unsupported", "error"] as const, "error"),
    matchedRuleIds: ruleIds(value.matchedRuleIds), uncertainRuleIds: ruleIds(value.uncertainRuleIds) } : undefined;
}
function inputMetadata(value: any) {
  return value ? { redacted: value.redacted === true,
    omittedMessages: Number.isSafeInteger(value.omittedMessages) && value.omittedMessages >= 0 ? value.omittedMessages : 0,
    authorizationHistoryComplete: value.authorizationHistoryComplete === true } : undefined;
}
function nativeContext(value: any) {
  if (!value) return undefined;
  const shellFamily = one(value.shellFamily, SHELL_FAMILIES, "unknown");
  const executionRoute = one(value.executionRoute, ["local-embedded", "unverified"] as const, "unverified");
  const contextReason = one(value.contextReason, CONTEXT_REASONS, "CWD_UNCERTAIN");
  return { shellFamily, executionRoute, contextReason };
}
// 不调用外来 getter，也不遍历未知字段。
function dataField(value: unknown, key: string): any {
  try {
    if (!value || (typeof value !== "object" && typeof value !== "function")) return undefined;
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return descriptor && "value" in descriptor ? descriptor.value : undefined;
  } catch { return undefined; }
}
function bounded(value: unknown, maximum: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= maximum;
}
function safeUsage(value: unknown) {
  const usage: Record<string, number> = {};
  for (const key of ["inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "reasoningTokens"] as const) {
    const count = dataField(value, key);
    if (bounded(count, Number.MAX_SAFE_INTEGER)) usage[key] = count;
  }
  return Object.keys(usage).length ? usage : undefined;
}
function safeTiming(value: unknown) {
  const budgetMs = dataField(value, "budgetMs"), remainingTotalMs = dataField(value, "remainingTotalMs");
  const elapsedMs = dataField(value, "elapsedMs"), lastStage = dataField(value, "lastStage");
  const stages = dataField(value, "stages"), requestBytes = dataField(value, "requestBytes");
  const timeoutSource = dataField(value, "timeoutSource");
  if (!bounded(budgetMs, 240000) || !bounded(remainingTotalMs, 240000) || !bounded(elapsedMs, 86400000) ||
      !REVIEW_STAGES.includes(lastStage) || !Array.isArray(stages)) return undefined;
  const length = dataField(stages, "length");
  if (!bounded(length, 6)) return undefined;
  const safeStages: Array<{ stage: typeof REVIEW_STAGES[number]; durationMs: number }> = [];
  for (let index = 0; index < length; index++) {
    const item = dataField(stages, String(index)), stage = dataField(item, "stage"), durationMs = dataField(item, "durationMs");
    if (REVIEW_STAGES.includes(stage) && bounded(durationMs, 86400000)) safeStages.push({ stage, durationMs });
  }
  return { budgetMs, remainingTotalMs, elapsedMs, lastStage, stages: safeStages,
    ...(bounded(requestBytes, 65536) ? { requestBytes } : {}),
    ...(REVIEW_TIMEOUT_SOURCES.includes(timeoutSource) ? { timeoutSource } : {}) };
}
function safeAttempt(value: unknown, target: "primary" | "remote", flattened = false) {
  const get = (key: string) => dataField(value, key);
  const model = get("model"), review = flattened ? value : get("review");
  const provider = safeIdentity(flattened ? get("provider") : dataField(model, "provider"));
  const modelId = safeIdentity(flattened ? model : dataField(model, "id"));
  const decision = dataField(review, "decision"), risk = dataField(review, "risk");
  const authorization = dataField(review, "authorization"), reasonCode = dataField(review, "reasonCode");
  const transportCode = get("transportCode"), httpStatus = get("httpStatus"), timing = safeTiming(get("timing"));
  const usage = safeUsage(get("usage"));
  const common = { target, called: get("called") === true,
    ...(provider ? { provider } : {}), ...(modelId ? { model: modelId } : {}),
    ...(timing ? { timing } : {}), ...(usage ? { usage } : {}) };
  if (get("status") === "valid") return { ...common, status: "valid" as const,
    ...(DECISIONS.includes(decision) ? { decision } : {}), ...(RISKS.includes(risk) ? { risk } : {}),
    ...(AUTHORIZATIONS.includes(authorization) ? { authorization } : {}),
    ...(REVIEW_REASONS.includes(reasonCode) ? { reasonCode } : {}) };
  return { ...common, status: "failure" as const,
    failureCode: one(get("failureCode"), REVIEW_FAILURE_CODES, "REQUEST_FAILED"),
    ...(TRANSPORT_CODES.includes(transportCode) ? { transportCode } : {}),
    ...(Number.isInteger(httpStatus) && httpStatus >= 100 && httpStatus <= 599 ? { httpStatus } : {}) };

}
export function safeAttempts(result?: ReviewSequenceResult) {
  return (["primary", "remote"] as const).flatMap(target => {
    const attempt = dataField(result, target);
    return attempt ? [safeAttempt(attempt, target)] : [];
  });
}
const STAGE_LABELS = { "resolve-target": "解析审查目标", "key-lookup": "查找凭据", "response-headers": "等待响应头",
  "response-body": "读取响应体", "response-parse": "解析响应", "decision-parse": "解析决定" } as const;
const FAILURE_LABELS: Record<typeof REVIEW_FAILURE_CODES[number], string> = {
  TARGET_UNAVAILABLE: "审查目标不可用", API_UNSUPPORTED: "接口不支持", KEY_UNAVAILABLE: "凭据不可用",
  HTTP_NON_OK: "响应状态异常", FETCH_FAILED: "请求失败", RESPONSE_READ_FAILED: "响应读取失败",
  RESPONSE_TOO_LARGE: "响应过大", RESPONSE_JSON_INVALID: "响应格式无效", RESPONSE_SHAPE_INVALID: "响应结构无效",
  REVIEW_JSON_INVALID: "决定格式无效", REVIEW_SCHEMA_INVALID: "决定结构无效", REVIEW_OUTPUT_TRUNCATED: "决定输出截断",
  INPUT_TOO_LARGE: "输入过大", INPUT_INVALID: "输入无效", REQUEST_FAILED: "请求失败", CANCELLED: "审查取消", TIMEOUT: "审查超时",
};
export function reviewFailureSummary(result?: ReviewSequenceResult): string {
  return safeAttempts(result).map(attempt => {
    const label = attempt.target === "primary" ? "主审" : "备用";
    if (attempt.status === "valid") return `${label}：${attempt.decision === "allow" ? "允许" : attempt.decision === "deny" ? "拒绝" : "需人工确认"}`;
    const timing = attempt.timing;
    const timeout = timing?.timeoutSource === "primary-budget" ? "主审预算到期" :
      timing?.timeoutSource === "remote-budget" ? "备用预算到期" : timing?.timeoutSource === "total-budget" ? "总预算到期" : undefined;
    const details = timing ? `${STAGE_LABELS[timing.lastStage as keyof typeof STAGE_LABELS]}，${(timing.elapsedMs / 1000).toFixed(1)}s，` : "";
    return `${label}：${details}${timeout ?? FAILURE_LABELS[attempt.failureCode]}`;
  }).join("；");
}

export class ApprovalDiagnostic {
  readonly data: any;
  done = false;
  awaitingExecute = false;
  invalidated = false;
  reviewStarted = false;
  approvalRecorded = false;
  routingComplete = false;
  private phaseStarted = Date.now();
  private currentPhase: string | undefined;
  get current() {
    return { toolCallId: safeCallId(this.data.toolCallId), toolCallIdDigest: this.data.toolCallIdDigest,
      outcome: this.currentPhase === "human" || this.currentPhase === "human-queued" ? "pending-human" :
        this.currentPhase === "executing" ? "executing" : "reviewing",
      source: this.data.source, reasonCode: this.data.reasonCode, chain: [...this.data.chain],
      nativeContext: nativeContext(this.data.nativeContext), phase: this.currentPhase };
  }
  constructor(sequence: number, id: unknown, entrypoint: string, mode: string, generation: number, sessionId?: unknown) {
    this.data = { version: 1, sequence, toolCallId: safeCallId(id), toolCallIdDigest: toolCallIdDigest(id), sessionIdDigest: sessionIdDigest(sessionId),
      entrypoint: one(entrypoint, ["bash", "permission_bash"] as const, "permission_bash"),
      mode: one(mode, ["smart", "manual"] as const, "manual"),
      generation: Number.isSafeInteger(generation) && generation >= 0 ? generation : 0,
      source: "none", outcome: "blocked", reasonCode: "NOT_REVIEWED", chain: [], preModelGates: [], attempts: [] };
  }
  gates(...values: string[]) {
    for (const value of values) if ((value === "INPUT_TOO_LARGE" ||
        (!this.reviewStarted && !this.approvalRecorded && !this.routingComplete)) && GATE_CODES.includes(value as never) && !this.data.preModelGates.includes(value))
      this.data.preModelGates.push(value);
  }
  phase(value: typeof PHASES[number]) {
    const now = Date.now();
    if (this.currentPhase) {
      (this.data.timings ??= []).push({ phase: this.currentPhase, durationMs: Math.max(0, now - this.phaseStarted) });
    }
    this.currentPhase = value; this.phaseStarted = now;
  }
  finishTiming() {
    if (this.currentPhase) {
      (this.data.timings ??= []).push({ phase: this.currentPhase, durationMs: Math.max(0, Date.now() - this.phaseStarted) });
      this.currentPhase = undefined;
    }
  }
  context(value: unknown) { try { this.data.nativeContext = nativeContext(value); } catch { this.data.nativeContext = undefined; } }
  analysis(status: string, matchedRuleIds: number[], uncertainRuleIds: number[]) {
    this.data.analysis = analysis({ status, matchedRuleIds, uncertainRuleIds });
  }
  input(packet: SanitizedReviewPacket) {
    this.data.reviewInput = inputMetadata({ redacted: packet.privacy.redacted,
      omittedMessages: packet.contextSelection.omittedMessages,
      authorizationHistoryComplete: packet.contextSelection.authorizationHistoryComplete });
  }
  review(result: ReviewSequenceResult) { try { this.data.attempts = safeAttempts(result); } catch { this.data.attempts = []; } }
  approval(value: { source: string; reasonCode: string; chain: string[] }) {
    this.approvalRecorded = true;
    this.data.source = one(value.source, SOURCES, "none");
    this.data.reasonCode = one(value.reasonCode, REASONS, "DIAGNOSTIC_UNKNOWN");
    this.data.chain = value.chain.filter(item => SOURCES.includes(item as never) && item !== "none");
  }
}

export function createApprovalAudit(append?: (type: string, data: unknown) => void) {
  let sequence = 0;
  const state = { accepted: 0, failed: 0, health: append ? "idle" : "unavailable",
    durability: "not-attested", last: undefined as any };
  return { state, begin: (id: unknown, entrypoint: string, mode: string, generation: number, sessionId?: unknown) =>
    new ApprovalDiagnostic(++sequence, id, entrypoint, mode, generation, sessionId),
    finish(call: ApprovalDiagnostic, stage: string, outcome: string, reasonCode?: string) {
      if (call.done) return;
      call.done = true;
      call.finishTiming();
      try {
        const record = { version: 1, sequence: Number.isSafeInteger(call.data.sequence) ? call.data.sequence : 0,
          toolCallId: safeCallId(call.data.toolCallId),
          toolCallIdDigest: typeof call.data.toolCallIdDigest === "string" && /^[a-f0-9]{64}$/u.test(call.data.toolCallIdDigest)
            ? call.data.toolCallIdDigest : null,
          sessionIdDigest: typeof call.data.sessionIdDigest === "string" && /^[a-f0-9]{64}$/u.test(call.data.sessionIdDigest)
          ? call.data.sessionIdDigest : null,
        entrypoint: one(call.data.entrypoint, ["bash", "permission_bash"] as const, "permission_bash"),
          mode: one(call.data.mode, ["smart", "manual"] as const, "manual"),
          generation: Number.isSafeInteger(call.data.generation) && call.data.generation >= 0 ? call.data.generation : 0,
          source: one(call.data.source, SOURCES, "none"), nativeContext: nativeContext(call.data.nativeContext), stage: one(stage, ["hook", "execute", "invalidated"] as const, "execute"),
          outcome: one(outcome, OUTCOMES, "blocked"),
          reasonCode: reasonCode === undefined ? one(call.data.reasonCode, REASONS, "DIAGNOSTIC_UNKNOWN") : one(reasonCode, REASONS, "DIAGNOSTIC_UNKNOWN"),
          chain: call.data.chain.filter((item: unknown) => SOURCES.includes(item as never) && item !== "none"),
          preModelGates: call.data.preModelGates.filter((item: unknown) => GATE_CODES.includes(item as never)),
          attempts: call.data.attempts.map((item: unknown) => safeAttempt(item,
            one(dataField(item, "target"), ["primary", "remote"] as const, "primary"), true)), ...(call.data.analysis ? { analysis: analysis(call.data.analysis) } : {}),
          ...(call.data.reviewInput ? { reviewInput: inputMetadata(call.data.reviewInput) } : {}),
          ...(Array.isArray(call.data.timings) ? { timings: call.data.timings.filter((item: any) =>
            PHASES.includes(item.phase) && Number.isSafeInteger(item.durationMs) && item.durationMs >= 0)
            .slice(0, 32).map((item: any) => ({ phase: item.phase, durationMs: Math.min(item.durationMs, 86400000) })) } : {}) };
        state.last = record;
        if (!append) throw new Error("audit unavailable");
        append(AUDIT_TYPE, record); state.accepted++; state.health = "accepted";
      } catch { state.failed++; state.health = append ? "failed" : "unavailable"; }
    } };
}
