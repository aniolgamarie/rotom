import type { ModelReview, ReviewReason } from "./reviewer";
import { REVIEW_REASONS } from "./reviewer";
import type { NativeConstraint } from "./reviewer";
import type { ShellEffect } from "./shell-analysis";
import type { PermissionMode } from "./types";

export type RestrictionState = "clear" | "conflicting" | "unknown";

export interface StructuredRestriction {
  verified: boolean;
  result: "satisfied" | "conflicting" | "unknown";
}

export interface RestrictionFacts {
  generation: number;
  currentGeneration: number;
  contextComplete: boolean;
  uninterpretedUserText: boolean;
  structuredRestrictions: readonly StructuredRestriction[];
}

export interface MechanicalPolicyEvidence {
  coverageVerified: boolean;
  healthVerified: boolean;
  contextComplete: boolean;
  redactionComplete: boolean;
  targetProofVerified: boolean;
  generationVerified: boolean;
}

export interface PolicyInput {
  mode: PermissionMode;
  effects: readonly ShellEffect[];
  analysisComplete: boolean;
  nativeConstraints: readonly NativeConstraint[];
  restrictionFacts: RestrictionFacts;
  hardProhibited: boolean;
  mechanical: MechanicalPolicyEvidence;
}

export type PolicyOutcome = "allow" | "ask" | "deny" | "review";
export type PolicySource =
  | "hard-rule"
  | "low-risk-rule"
  | "reviewer"
  | "remote-fallback"
  | "fallback"
  | "manual-boundary"
  | "native-protection"
  | "system-failure";
export type PolicyReasonCode = ReviewReason | "DETERMINISTIC_LOW_RISK";

export interface PolicyAssessment {
  outcome: PolicyOutcome;
  source: PolicySource;
  reason_code: PolicyReasonCode;
  restrictionState: RestrictionState;
  modelCallsAllowed: boolean;
}

const REVIEW_REASON_SET = new Set<string>(REVIEW_REASONS);
const FIXED_HUMAN_EFFECTS = new Set([
  "write",
  "delete",
  "network-send",
  "secret-access",
  "device-access",
]);
const UNKNOWN_NON_READ_EFFECTS = new Set(["unknown", "dynamic", "execute", "state-change"]);

export function deriveRestrictionState(input: RestrictionFacts): RestrictionState {
  if (
    !Number.isSafeInteger(input.generation) ||
    !Number.isSafeInteger(input.currentGeneration) ||
    input.generation !== input.currentGeneration
  )
    return "unknown";
  if (
    input.structuredRestrictions.some(
      (restriction) => restriction.verified && restriction.result === "conflicting",
    )
  )
    return "conflicting";
  if (
    !input.contextComplete ||
    input.uninterpretedUserText ||
    input.structuredRestrictions.some(
      (restriction) => !restriction.verified || restriction.result !== "satisfied",
    )
  )
    return "unknown";
  return "clear";
}

function assessment(
  outcome: PolicyOutcome,
  source: PolicySource,
  reason_code: PolicyReasonCode,
  restrictionState: RestrictionState,
): PolicyAssessment {
  return {
    outcome,
    source,
    reason_code,
    restrictionState,
    modelCallsAllowed: outcome === "review",
  };
}

function hasHardNativeDeny(input: PolicyInput): boolean {
  return input.nativeConstraints.some(
    (constraint) => constraint.source === "explicit-deny" || constraint.policy === "deny",
  );
}

function hasNativeHumanBoundary(input: PolicyInput): boolean {
  return input.nativeConstraints.some(
    (constraint) =>
      (constraint.policy === "prompt" && !["tool-default", "tier-default", "compound-structural"].includes(constraint.source)) ||
      constraint.source === "command-prompt" ||
      constraint.source === "critical-safety" ||
      constraint.source === "unknown",
  );
}

function mechanicalGatePassed(input: PolicyInput): boolean {
  const evidence = input.mechanical;
  return (
    evidence.coverageVerified &&
    evidence.healthVerified &&
    evidence.contextComplete &&
    evidence.redactionComplete &&
    evidence.targetProofVerified &&
    evidence.generationVerified &&
    input.restrictionFacts.generation === input.restrictionFacts.currentGeneration
  );
}

function allDeterministicReads(effects: readonly ShellEffect[]): boolean {
  return (
    effects.length > 0 && effects.every((effect) => effect.kind === "read" && effect.risk === "low")
  );
}

export function assessBeforeReview(input: PolicyInput): PolicyAssessment {
  const restrictionState = deriveRestrictionState(input.restrictionFacts);
  if (input.hardProhibited || hasHardNativeDeny(input))
    return assessment("deny", "hard-rule", "PROHIBITED_EFFECT", restrictionState);
  if (hasNativeHumanBoundary(input))
    return assessment("ask", "native-protection", "USER_CONFIRMATION_REQUIRED", restrictionState);
  if (restrictionState === "conflicting")
    return assessment("ask", "native-protection", "USER_CONFIRMATION_REQUIRED", restrictionState);
  if (input.effects.some((effect) => FIXED_HUMAN_EFFECTS.has(effect.kind)))
    return assessment("ask", "native-protection", "USER_CONFIRMATION_REQUIRED", restrictionState);
  if (
    input.effects.some(
      (effect) =>
        UNKNOWN_NON_READ_EFFECTS.has(effect.kind) ||
        (effect.risk === "unknown" && effect.kind !== "read"),
    )
  )
    return assessment("ask", "native-protection", "UNKNOWN_EFFECT", restrictionState);
  if (!input.analysisComplete || input.effects.length === 0)
    return assessment("ask", "native-protection", "UNKNOWN_EFFECT", restrictionState);
  if (!mechanicalGatePassed(input))
    return assessment("ask", "native-protection", "USER_CONFIRMATION_REQUIRED", restrictionState);
  if (restrictionState === "clear" && allDeterministicReads(input.effects))
    return assessment("allow", "low-risk-rule", "DETERMINISTIC_LOW_RISK", restrictionState);
  if (input.mode === "manual")
    return assessment("ask", "manual-boundary", "USER_CONFIRMATION_REQUIRED", restrictionState);
  return assessment("review", "reviewer", "USER_CONFIRMATION_REQUIRED", restrictionState);
}

function sameEffectCoverage(input: PolicyInput, review: ModelReview): boolean {
  const expected = new Set(input.effects.map((effect) => effect.effectId));
  const actual = new Set(review.effects);
  return (
    actual.size === review.effects.length &&
    actual.size === expected.size &&
    [...expected].every((effectId) => actual.has(effectId))
  );
}

function validCommonReview(input: PolicyInput, review: ModelReview): boolean {
  return (
    (review.decision === "allow" || review.decision === "ask" || review.decision === "deny") &&
    REVIEW_REASON_SET.has(review.reasonCode) &&
    Array.isArray(review.effects) &&
    Array.isArray(review.unknowns) &&
    Array.isArray(review.evidence?.userMessageIds) &&
    Array.isArray(review.evidence?.bindings) &&
    sameEffectCoverage(input, review)
  );
}

function validAllowReview(input: PolicyInput, review: ModelReview): boolean {
  if (
    review.decision !== "allow" ||
    review.risk !== "low" ||
    review.authorization !== "sufficient" ||
    review.reasonCode !== "LOW_RISK_AUTHORIZED" ||
    review.unknowns.length !== 0 ||
    !allDeterministicReads(input.effects) ||
    review.evidence.userMessageIds.length === 0 ||
    review.evidence.bindings.length !== input.effects.length
  )
    return false;
  const expected = new Set(input.effects.map((effect) => effect.effectId));
  const bound = new Set<string>();
  for (const binding of review.evidence.bindings) {
    if (!expected.has(binding.effectId) || bound.has(binding.effectId)) return false;
    bound.add(binding.effectId);
  }
  return bound.size === expected.size;
}

export function synthesizeReview(
  input: PolicyInput,
  review: ModelReview | undefined,
  mechanicalEvidenceVerified: boolean,
  reviewSource: "reviewer" | "remote-fallback" = "reviewer",
): PolicyAssessment {
  const beforeReview = assessBeforeReview(input);
  if (beforeReview.outcome !== "review") return beforeReview;
  if (!review || !validCommonReview(input, review))
    return assessment("ask", reviewSource, "POLICY_MISMATCH", beforeReview.restrictionState);
  if (review.decision === "deny")
    return assessment("deny", reviewSource, review.reasonCode, beforeReview.restrictionState);
  if (review.decision === "ask")
    return assessment("ask", reviewSource, review.reasonCode, beforeReview.restrictionState);
  if (!mechanicalEvidenceVerified || !validAllowReview(input, review))
    return assessment("ask", reviewSource, "POLICY_MISMATCH", beforeReview.restrictionState);
  return assessment("allow", reviewSource, "LOW_RISK_AUTHORIZED", beforeReview.restrictionState);
}
