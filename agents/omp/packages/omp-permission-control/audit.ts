import { COVERAGE_REASONS, type CoverageReason, type HealthResult } from "./controller";
import type { PolicyReasonCode, PolicySource } from "./policy";
import { REVIEW_REASONS } from "./reviewer";
import type { PermissionMode } from "./types";

export interface AuditInput {
  request_id: string;
  decision_id: string;
  operation_digest: string;
  outcome: "allow" | "ask" | "deny";
  source: PolicySource;
  reason_code: PolicyReasonCode;
  active_mode: PermissionMode;
  policy_version: string;
  actual_reviewer: string;
  reviewer_source: "explicit-profile" | "session-default" | "remote-fallback" | "fallback" | "not-called";
  primary_model?: string;
  remote_model?: string;
  fallback_model?: string;
  remote_configured?: boolean;
  remote_called?: boolean;
  fallback_configured: boolean;
  fallback_called: boolean;
  coverage: "eligible" | "manual-required";
  coverage_reasons: readonly CoverageReason[];
  health: { bridge: HealthResult; model: HealthResult | "not-called";
    tiny: HealthResult | "disabled" | "not-called"; remote?: HealthResult | "disabled" | "not-called" };
  primary_calls: number;
  remote_calls?: number;
  tiny_calls: number;
  elapsed_ms: number;
  permit: "none" | "pending" | "consumed" | "invalidated";
  human?: { human_decision_id: string; ask_decision_id: string; source: "human"; outcome: "allow" | "deny" };
  user_message_ids?: readonly string[];
}
export type RedactedAuditRecord = Readonly<Omit<AuditInput, "elapsed_ms"> & {
  schema_version: 1;
  elapsed_bucket: "under-1s" | "1-5s" | "5-25s" | "25-30s" | "over-30s";
}>;
function invalid(): never { throw new Error("PERMISSION_AUDIT_INVALID"); }
function exact(value: object, required: readonly string[], optional: readonly string[] = []): void {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      required.some(key => !Object.hasOwn(value, key)) ||
      Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) invalid();
}
const id = (value: unknown): boolean => typeof value === "string" && value.length <= 128 && /^[a-zA-Z0-9_-]+$/u.test(value);
const hash = (value: unknown): boolean => typeof value === "string" && value.length === 64 && /^[a-f0-9]{64}$/u.test(value);
function freeze<T>(value: T): T {
  if (value && typeof value === "object") { for (const item of Object.values(value)) freeze(item); Object.freeze(value); }
  return value;
}

/** 仅接收宿主固定字段；未知字段失败，绝不对任意上下文做通用序列化。 */
export function createAuditRecord(input: AuditInput): RedactedAuditRecord {
  exact(input, ["request_id", "decision_id", "operation_digest", "outcome", "source", "reason_code", "active_mode",
    "policy_version", "actual_reviewer", "reviewer_source", "fallback_configured", "fallback_called", "coverage",
    "coverage_reasons", "health", "primary_calls", "tiny_calls", "elapsed_ms", "permit"],
    ["primary_model", "remote_model", "fallback_model", "remote_configured", "remote_called", "remote_calls",
      "human", "user_message_ids"]);
  exact(input.health, Object.hasOwn(input.health, "remote") ? ["bridge", "model", "tiny", "remote"] : ["bridge", "model", "tiny"]);
  if (![input.request_id, input.decision_id].every(id) || ![input.operation_digest, input.policy_version].every(hash) ||
      !["allow", "ask", "deny"].includes(input.outcome) ||
      !["hard-rule", "low-risk-rule", "reviewer", "remote-fallback", "fallback", "manual-boundary", "native-protection", "system-failure"].includes(input.source) ||
      ![...REVIEW_REASONS, "DETERMINISTIC_LOW_RISK"].includes(input.reason_code) ||
      !["smart", "manual"].includes(input.active_mode) ||
      !["explicit-profile", "session-default", "remote-fallback", "fallback", "not-called"].includes(input.reviewer_source) ||
      typeof input.actual_reviewer !== "string" || !input.actual_reviewer || input.actual_reviewer.length > 512 ||
      /[\s\u0000-\u001f]/u.test(input.actual_reviewer) ||
      [input.primary_model, input.remote_model, input.fallback_model].some(model => model !== undefined &&
        (typeof model !== "string" || !model || model.length > 512 || /[\s\u0000-\u001f]/u.test(model))) ||
      typeof input.fallback_configured !== "boolean" || typeof input.fallback_called !== "boolean" ||
      (input.remote_configured !== undefined && typeof input.remote_configured !== "boolean") ||
      (input.remote_called !== undefined && typeof input.remote_called !== "boolean") ||
      !["eligible", "manual-required"].includes(input.coverage) ||
      !Array.isArray(input.coverage_reasons) || new Set(input.coverage_reasons).size !== input.coverage_reasons.length ||
      !input.coverage_reasons.every(reason => (COVERAGE_REASONS as readonly string[]).includes(reason)) ||
      !["healthy", "degraded", "unavailable"].includes(input.health.bridge) ||
      !["healthy", "degraded", "unavailable", "not-called"].includes(input.health.model) ||
      !["healthy", "degraded", "unavailable", "disabled", "not-called"].includes(input.health.tiny) ||
      (input.health.remote !== undefined && !["healthy", "degraded", "unavailable", "disabled", "not-called"].includes(input.health.remote)) ||
      ![0, 1].includes(input.primary_calls) || ![0, 1].includes(input.remote_calls ?? 0) || ![0, 1].includes(input.tiny_calls) ||
      !Number.isFinite(input.elapsed_ms) || input.elapsed_ms < 0 ||
      !["none", "pending", "consumed", "invalidated"].includes(input.permit)) invalid();
  const totalCalls = input.primary_calls + (input.remote_calls ?? 0) + input.tiny_calls;
  if ((totalCalls === 0) !== (input.actual_reviewer === "not-called") ||
      (totalCalls === 0) !== (input.reviewer_source === "not-called") ||
      input.remote_called !== undefined && input.remote_called !== ((input.remote_calls ?? 0) === 1) ||
      (input.remote_calls ?? 0) === 1 && input.remote_configured !== true ||
      input.primary_model !== undefined && input.primary_calls !== 1 ||
      input.remote_model !== undefined && (input.remote_calls ?? 0) !== 1 ||
      input.fallback_model !== undefined && input.tiny_calls !== 1 ||
      input.fallback_called !== (input.tiny_calls === 1) ||
      input.tiny_calls === 1 && !input.fallback_configured ||
      input.source === "fallback" && (input.outcome === "allow" || !input.fallback_called)) invalid();
  if (input.human) {
    exact(input.human, ["human_decision_id", "ask_decision_id", "source", "outcome"]);
    if (!id(input.human.human_decision_id) || input.human.ask_decision_id !== input.decision_id ||
        input.human.source !== "human" || !["allow", "deny"].includes(input.human.outcome) || input.outcome !== "ask") invalid();
  }
  if (input.user_message_ids && (!Array.isArray(input.user_message_ids) || input.user_message_ids.length > 16 ||
      !input.user_message_ids.every(id) || new Set(input.user_message_ids).size !== input.user_message_ids.length)) invalid();
  const { elapsed_ms, ...fields } = structuredClone(input);
  return freeze({ schema_version: 1, ...fields, elapsed_bucket: elapsed_ms < 1000 ? "under-1s" :
    elapsed_ms < 5000 ? "1-5s" : elapsed_ms < 25000 ? "5-25s" : elapsed_ms <= 30000 ? "25-30s" : "over-30s" });
}

export async function appendAudit(record: RedactedAuditRecord,
    append: (record: RedactedAuditRecord) => Promise<void>, onFailure: () => void):
    Promise<{ stored: boolean; health: "healthy" | "degraded" }> {
  try { await append(record); return { stored: true, health: "healthy" }; }
  catch {
    // 不带异常正文；宿主回调同步降级并撤销尚未消费的许可。
    onFailure();
    return { stored: false, health: "degraded" };
  }
}
