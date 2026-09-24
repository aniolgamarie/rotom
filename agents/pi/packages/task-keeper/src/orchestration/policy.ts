import { digest, finiteInteger, ContractError, object, identifier } from "../contracts/primitives.ts";

export interface RouteCandidate {
  id: string; preference: number; approved: boolean; accountResolved: boolean; toolsSatisfied: boolean;
  contextSatisfied: boolean; profileVerified: boolean; observationsVerified: boolean; resourcesAvailable: boolean;
  budgetAvailable: boolean; networkVerified: boolean; riskKnown: boolean;
}
/** Pure eligibility and ordering. Capability scores cannot compensate for a failed prerequisite. */
export function chooseRoute(candidates: readonly RouteCandidate[]) {
  const rejected: Array<{ id: string; reasons: string[] }> = [];
  const eligible: RouteCandidate[] = [];
  const prerequisites = ["approved", "accountResolved", "toolsSatisfied", "contextSatisfied", "profileVerified",
    "observationsVerified", "resourcesAvailable", "budgetAvailable", "networkVerified", "riskKnown"] as const;
  const ids = new Set<string>();
  for (const candidate of candidates) {
    object(candidate, ["id", "preference", ...prerequisites]);
    identifier(candidate.id);
    if (ids.has(candidate.id)) throw new ContractError("DUPLICATE_ROUTE_CANDIDATE");
    ids.add(candidate.id);
    finiteInteger(candidate.preference);
    const reasons = prerequisites.filter(key => candidate[key] !== true);
    if (reasons.length) rejected.push({ id: candidate.id, reasons }); else eligible.push(candidate);
  }
  eligible.sort((a, b) => a.preference - b.preference || a.id.localeCompare(b.id));
  return { route: eligible[0]?.id ?? null, rejected, reason: eligible.length ? "hard-eligibility; configured-preference; stable-id" : "no_eligible_route" };
}

export interface RecipeInput {
  enabled: readonly string[]; qualityFailure: boolean; environmentFailure: boolean;
  upgradeEligible: boolean; criticEligible: boolean; upgradesUsed: number; critiquesUsed: number;
  semanticAttempts: number; maxSemanticAttempts: number; stepsUsed: number; maxSteps: number;
  remainingRequests: number; requiredReserve: number;
  finding: null | { actionable: boolean; evidenceVerified: boolean };
}
/** A selector has no timer, runtime adapter or workspace access; only the dispatcher executes its decision. */
export function recipePolicy(input: RecipeInput) {
  if (input.enabled.includes("cascade")) throw new ContractError("CASCADE_REMOVED");
  for (const field of ["upgradesUsed", "critiquesUsed", "semanticAttempts", "maxSemanticAttempts", "stepsUsed", "maxSteps", "remainingRequests", "requiredReserve"] as const) finiteInteger(input[field]);
  const base = { version: 1, inputDigest: digest(input) };
  const decide = (action: "direct" | "upgrade" | "critic" | "revise" | "skip" | "block", reason: string) => ({ ...base, action, reason });
  if (input.environmentFailure) return decide("block", "environment_failure_is_not_quality_failure");
  if (input.stepsUsed >= input.maxSteps) return decide("block", "step_limit");
  if (input.finding?.actionable && input.finding.evidenceVerified) {
    if (input.semanticAttempts >= input.maxSemanticAttempts) return decide("block", "semantic_attempt_limit");
    return decide("revise", "supported_actionable_finding");
  }
  if (input.enabled.includes("critique") && input.criticEligible && input.critiquesUsed < 1) {
    if (input.remainingRequests <= input.requiredReserve) return decide("skip", "required_reserve");
    return decide("critic", "single_optional_critique");
  }
  return decide("direct", input.finding ? "no_supported_actionable_finding" : "default_fixed_workflow");
}

export interface QuotaTelemetry { account: string; bucket: string; source: string; observedAt: number; remaining: number; resetAt: number | null }
export function quotaTelemetry(observation: QuotaTelemetry | null, expected: { account: string; bucket: string; source: string; now: number; freshnessMs: number }) {
  finiteInteger(expected.now); finiteInteger(expected.freshnessMs);
  if (!observation || observation.account !== expected.account || observation.bucket !== expected.bucket || observation.source !== expected.source
    || !Number.isSafeInteger(observation.observedAt) || observation.observedAt > expected.now || expected.now - observation.observedAt > expected.freshnessMs
    || !Number.isSafeInteger(observation.remaining) || observation.remaining < 0) return { status: "unknown" as const, remaining: null };
  if (observation.resetAt !== null && (!Number.isSafeInteger(observation.resetAt) || observation.resetAt < observation.observedAt)) throw new ContractError("INVALID_TELEMETRY_RESET");
  return { status: "observed" as const, remaining: observation.remaining, reservation: false as const };
}
