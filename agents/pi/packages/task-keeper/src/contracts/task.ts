import { ContractError, finiteInteger, identifier, object, canonical } from "./primitives.ts";

export const JOB_STATES = ["QUEUED", "RUNNING", "WAITING_QUOTA", "PAUSED", "BLOCKED", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"] as const;
export type JobState = typeof JOB_STATES[number];
export const TERMINAL = new Set<JobState>(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]);
const NEXT: Record<JobState, readonly JobState[]> = {
  QUEUED: ["RUNNING", "PAUSED", "BLOCKED", "CANCELLED"],
  RUNNING: ["WAITING_QUOTA", "PAUSED", "BLOCKED", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"],
  WAITING_QUOTA: ["RUNNING", "PAUSED", "BLOCKED", "CANCELLED"],
  PAUSED: ["QUEUED", "RUNNING", "WAITING_QUOTA", "BLOCKED", "CANCELLED"],
  BLOCKED: ["QUEUED", "RUNNING", "WAITING_QUOTA", "PAUSED", "FAILED", "CANCELLED"],
  COMPLETED: [], PARTIAL: [], FAILED: [], CANCELLED: [],
};

export function transition(current: JobState, next: JobState): JobState {
  if (current === next) return current;
  if (!NEXT[current]?.includes(next)) throw new ContractError("ILLEGAL_TRANSITION", `${current} -> ${next}`);
  return next;
}

export interface TaskSpec {
  id: string;
  workScope: string;
  version: number;
  objective: string;
  workflow: "inspect" | "fix";
  required: string[];
  optional: string[];
  allowPartial: boolean;
  risk?: "low" | "medium" | "high" | "unknown";
  policyDigest: string;
  snapshot: string;
  maxSteps: number;
  maxSemanticAttempts: number;
  maxSemanticReplans?: number;
}

export function validateTaskSpec(input: unknown): TaskSpec {
  const v = object(input, ["id", "workScope", "version", "objective", "workflow", "required", "optional", "allowPartial", "risk", "policyDigest", "snapshot", "maxSteps", "maxSemanticAttempts", "maxSemanticReplans"]);
  for (const key of ["id", "workScope", "policyDigest", "snapshot"]) identifier(v[key], key);
  for (const key of ["version", "maxSteps", "maxSemanticAttempts"]) finiteInteger(v[key], 1);
  if (v.maxSemanticReplans !== undefined) finiteInteger(v.maxSemanticReplans);
  if (typeof v.objective !== "string" || !v.objective.trim() || v.objective.length > 65536) throw new ContractError("INVALID_OBJECTIVE");
  if (!["inspect", "fix"].includes(v.workflow as string) || typeof v.allowPartial !== "boolean") throw new ContractError("INVALID_WORKFLOW");
  for (const key of ["required", "optional"]) {
    if (!Array.isArray(v[key])) throw new ContractError("INVALID_CHECKS");
    for (const id of v[key] as unknown[]) identifier(id);
  }
  if (v.risk !== undefined && !["low", "medium", "high", "unknown"].includes(v.risk as string)) throw new ContractError("INVALID_RISK");
  const checks = [...v.required as string[], ...v.optional as string[]];
  if (!checks.length || new Set(checks).size !== checks.length) throw new ContractError("INVALID_CHECKS");
  return structuredClone(v) as unknown as TaskSpec;
}

export type CheckStatus = "passed" | "failed" | "not_run" | "unknown" | "not_applicable";
export interface CheckEvidence {
  checkId: string;
  status: CheckStatus;
  snapshot: string;
  specVersion: number;
  policyDigest: string;
  source: "verifier" | "reviewer" | "claim";
  artifactId: string | null;
}
export interface ExecutionContract {
  requested: Record<string, unknown>;
  resolved: Record<string, unknown> | null;
  runtimeObserved: Record<string, unknown> | null;
  violations: string[];
}
export interface FailureFact {
  id: string;
  layer: "provider" | "tool" | "runner" | "storage" | "policy" | "verification";
  code: string;
  message: string;
  attemptId: string;
  required: boolean;
  // This relation must be supplied by an authenticated adapter/verifier, never by a model claim.
  resolvedBy: string | null;
}
export interface ExecutionFacts {
  delivery: "queued" | "accepted" | "started";
  nativeRunId: string | null;
  execution: "running" | "ended" | "failed" | "interrupted" | "unknown";
  nativeStatus: string;
  terminationConfirmed: boolean;
  contract: ExecutionContract;
  observation: { complete: boolean; gaps: string[] };
  unknownMutators: string[];
  failures: FailureFact[];
  checks: CheckEvidence[];
  claims: string[];
}

export interface Receipt {
  jobId: string;
  specVersion: number;
  snapshot: string;
  status: "COMPLETED" | "PARTIAL" | "BLOCKED";
  nativeStatus: string;
  reasons: string[];
  optionalGaps: string[];
  failureHistory: FailureFact[];
  skippedSteps?: Array<{ stepId: string; reason: string | null; at: number | null }>;
  routes?: Array<{ stepId: string; role: string; configuredRoute: string | null; selectedRoute: string | null;
    recovery: { incidentId: string; primaryRoute: string } | null;
    attempts: Array<{ descriptorId: string; routeId: string | null; requested: { provider: string; model: string } | null;
      observed: Array<{ provider: string; model: string; thinking: string; producerId: string; stopReason: string | null;
        identitySource?: "client_configuration"; responseModel?: null; serverWeights?: "unverified" }> | null }> }>;
}

export function outcome(spec: TaskSpec, facts: ExecutionFacts): Receipt {
  const reasons: string[] = [];
  if (facts.delivery !== "started" || !facts.nativeRunId) reasons.push("execution_not_started");
  if (facts.execution !== "ended" || !facts.terminationConfirmed) reasons.push("execution_not_ended");
  reasons.push(...facts.contract.violations.map((v) => `contract:${v}`));
  if (!facts.contract.resolved || !facts.contract.runtimeObserved) reasons.push("contract_unknown");
  else for (const [field, requested] of Object.entries(facts.contract.requested)) {
    const resolved = facts.contract.resolved[field], observed = facts.contract.runtimeObserved[field];
    if (resolved === undefined || observed === undefined) reasons.push(`contract_unknown:${field}`);
    else if (canonical(requested) !== canonical(resolved) || canonical(resolved) !== canonical(observed)) reasons.push(`contract_mismatch:${field}`);
  }
  if (!facts.observation.complete || facts.observation.gaps.length) reasons.push("observation_incomplete");
  if (facts.unknownMutators.length) reasons.push("unknown_mutator");
  const valid = facts.checks.filter((check) => check.status === "passed" && check.source !== "claim" && check.artifactId
    && check.snapshot === spec.snapshot && check.specVersion === spec.version && check.policyDigest === spec.policyDigest);
  const evidenceIds = new Set(valid.map((check) => check.artifactId));
  const conflicting = (id: string) => facts.checks.some((check) => check.checkId === id && check.source !== "claim"
    && check.snapshot === spec.snapshot && check.specVersion === spec.version && check.policyDigest === spec.policyDigest && check.status !== "passed");
  for (const failure of facts.failures) {
    if (failure.required && (!failure.resolvedBy || !evidenceIds.has(failure.resolvedBy))) reasons.push(`unresolved:${failure.id}`);
  }
  for (const id of spec.required) {
    // A conflicting current check cannot be hidden behind an earlier passing result.
    if (!valid.some((check) => check.checkId === id) || conflicting(id)) reasons.push(`required:${id}`);
  }
  const optionalGaps = spec.optional.filter((id) => !valid.some((check) => check.checkId === id) || conflicting(id));
  if (optionalGaps.length && !spec.allowPartial) reasons.push("optional_gap_not_allowed");
  return { jobId: spec.id, specVersion: spec.version, snapshot: spec.snapshot,
    status: reasons.length ? "BLOCKED" : optionalGaps.length ? "PARTIAL" : "COMPLETED",
    nativeStatus: facts.nativeStatus, reasons, optionalGaps, failureHistory: structuredClone(facts.failures) };
}

export function presentReceipt(receipt: Receipt): string {
  return [`Task ${receipt.jobId}: ${receipt.status}; native: ${receipt.nativeStatus}`,
    `Blockers: ${receipt.reasons.join(", ") || "none"}`,
    `Optional gaps: ${receipt.optionalGaps.join(", ") || "none"}`,
    `Skipped steps: ${receipt.skippedSteps?.map(step => `${step.stepId}:${step.reason ?? "reason unknown"}`).join(", ") || "none"}`,
    `Snapshot: ${receipt.snapshot}; spec version: ${receipt.specVersion}`,
    `Failure history: ${receipt.failureHistory.map((f) => `${f.id}:${f.code}${f.resolvedBy ? " (resolved)" : ""}`).join(", ") || "none"}`].join("\n");
}
