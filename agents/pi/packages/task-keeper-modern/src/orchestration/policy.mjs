import { digest, finiteInteger, ContractError, object, identifier } from "../contracts/primitives.mjs";
export function chooseRoute(candidates) {
    const rejected = [];
    const eligible = [];
    const prerequisites = [
        "approved",
        "accountResolved",
        "toolsSatisfied",
        "contextSatisfied",
        "profileVerified",
        "observationsVerified",
        "resourcesAvailable",
        "budgetAvailable",
        "networkVerified",
        "riskKnown"
    ];
    const ids = new Set();
    for (const candidate of candidates){
        object(candidate, [
            "id",
            "preference",
            ...prerequisites
        ]);
        identifier(candidate.id);
        if (ids.has(candidate.id)) throw new ContractError("DUPLICATE_ROUTE_CANDIDATE");
        ids.add(candidate.id);
        finiteInteger(candidate.preference);
        const reasons = prerequisites.filter((key)=>candidate[key] !== true);
        if (reasons.length) rejected.push({
            id: candidate.id,
            reasons
        });
        else eligible.push(candidate);
    }
    eligible.sort((a, b)=>a.preference - b.preference || a.id.localeCompare(b.id));
    return {
        route: eligible[0]?.id ?? null,
        rejected,
        reason: eligible.length ? "hard-eligibility; configured-preference; stable-id" : "no_eligible_route"
    };
}
export function recipePolicy(input) {
    if (input.enabled.includes("cascade")) throw new ContractError("CASCADE_REMOVED");
    for (const field of [
        "upgradesUsed",
        "critiquesUsed",
        "semanticAttempts",
        "maxSemanticAttempts",
        "stepsUsed",
        "maxSteps",
        "remainingRequests",
        "requiredReserve"
    ])finiteInteger(input[field]);
    const base = {
        version: 1,
        inputDigest: digest(input)
    };
    const decide = (action, reason)=>({
            ...base,
            action,
            reason
        });
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
export function quotaTelemetry(observation, expected) {
    finiteInteger(expected.now);
    finiteInteger(expected.freshnessMs);
    if (!observation || observation.account !== expected.account || observation.bucket !== expected.bucket || observation.source !== expected.source || !Number.isSafeInteger(observation.observedAt) || observation.observedAt > expected.now || expected.now - observation.observedAt > expected.freshnessMs || !Number.isSafeInteger(observation.remaining) || observation.remaining < 0) return {
        status: "unknown",
        remaining: null
    };
    if (observation.resetAt !== null && (!Number.isSafeInteger(observation.resetAt) || observation.resetAt < observation.observedAt)) throw new ContractError("INVALID_TELEMETRY_RESET");
    return {
        status: "observed",
        remaining: observation.remaining,
        reservation: false
    };
}
