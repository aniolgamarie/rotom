import { ContractError, finiteInteger, identifier, object, canonical } from "./primitives.mjs";
export const JOB_STATES = [
    "QUEUED",
    "RUNNING",
    "WAITING_QUOTA",
    "PAUSED",
    "BLOCKED",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "CANCELLED"
];
export const TERMINAL = new Set([
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "CANCELLED"
]);
const NEXT = {
    QUEUED: [
        "RUNNING",
        "PAUSED",
        "BLOCKED",
        "CANCELLED"
    ],
    RUNNING: [
        "WAITING_QUOTA",
        "PAUSED",
        "BLOCKED",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "CANCELLED"
    ],
    WAITING_QUOTA: [
        "RUNNING",
        "PAUSED",
        "BLOCKED",
        "CANCELLED"
    ],
    PAUSED: [
        "QUEUED",
        "RUNNING",
        "WAITING_QUOTA",
        "BLOCKED",
        "CANCELLED"
    ],
    BLOCKED: [
        "QUEUED",
        "RUNNING",
        "WAITING_QUOTA",
        "PAUSED",
        "FAILED",
        "CANCELLED"
    ],
    COMPLETED: [],
    PARTIAL: [],
    FAILED: [],
    CANCELLED: []
};
export function transition(current, next) {
    if (current === next) return current;
    if (!NEXT[current]?.includes(next)) throw new ContractError("ILLEGAL_TRANSITION", `${current} -> ${next}`);
    return next;
}
export function validateTaskSpec(input) {
    const v = object(input, [
        "id",
        "workScope",
        "version",
        "objective",
        "workflow",
        "required",
        "optional",
        "allowPartial",
        "risk",
        "policyDigest",
        "snapshot",
        "maxSteps",
        "maxSemanticAttempts",
        "maxSemanticReplans"
    ]);
    for (const key of [
        "id",
        "workScope",
        "policyDigest",
        "snapshot"
    ])identifier(v[key], key);
    for (const key of [
        "version",
        "maxSteps",
        "maxSemanticAttempts"
    ])finiteInteger(v[key], 1);
    if (v.maxSemanticReplans !== undefined) finiteInteger(v.maxSemanticReplans);
    if (typeof v.objective !== "string" || !v.objective.trim() || v.objective.length > 65536) throw new ContractError("INVALID_OBJECTIVE");
    if (![
        "inspect",
        "fix"
    ].includes(v.workflow) || typeof v.allowPartial !== "boolean") throw new ContractError("INVALID_WORKFLOW");
    for (const key of [
        "required",
        "optional"
    ]){
        if (!Array.isArray(v[key])) throw new ContractError("INVALID_CHECKS");
        for (const id of v[key])identifier(id);
    }
    if (v.risk !== undefined && ![
        "low",
        "medium",
        "high",
        "unknown"
    ].includes(v.risk)) throw new ContractError("INVALID_RISK");
    const checks = [
        ...v.required,
        ...v.optional
    ];
    if (!checks.length || new Set(checks).size !== checks.length) throw new ContractError("INVALID_CHECKS");
    return structuredClone(v);
}
export function outcome(spec, facts) {
    const reasons = [];
    if (facts.delivery !== "started" || !facts.nativeRunId) reasons.push("execution_not_started");
    if (facts.execution !== "ended" || !facts.terminationConfirmed) reasons.push("execution_not_ended");
    reasons.push(...facts.contract.violations.map((v)=>`contract:${v}`));
    if (!facts.contract.resolved || !facts.contract.runtimeObserved) reasons.push("contract_unknown");
    else for (const [field, requested] of Object.entries(facts.contract.requested)){
        const resolved = facts.contract.resolved[field], observed = facts.contract.runtimeObserved[field];
        if (resolved === undefined || observed === undefined) reasons.push(`contract_unknown:${field}`);
        else if (canonical(requested) !== canonical(resolved) || canonical(resolved) !== canonical(observed)) reasons.push(`contract_mismatch:${field}`);
    }
    if (!facts.observation.complete || facts.observation.gaps.length) reasons.push("observation_incomplete");
    if (facts.unknownMutators.length) reasons.push("unknown_mutator");
    const valid = facts.checks.filter((check)=>check.status === "passed" && check.source !== "claim" && check.artifactId && (!facts.evidenceRequired || check.validity === "current" && check.supportsPassed === true && !!check.recordRef) && check.snapshot === spec.snapshot && check.specVersion === spec.version && check.policyDigest === spec.policyDigest);
    const evidenceIds = new Set(valid.map((check)=>check.artifactId));
    const conflicting = (id)=>facts.checks.some((check)=>check.checkId === id && check.source !== "claim" && (!facts.evidenceRequired || check.validity === "current") && check.snapshot === spec.snapshot && check.specVersion === spec.version && check.policyDigest === spec.policyDigest && check.status !== "passed");
    for (const failure of facts.failures){
        if (failure.required && (!failure.resolvedBy || !evidenceIds.has(failure.resolvedBy))) reasons.push(`unresolved:${failure.id}`);
    }
    for (const id of spec.required){
        if (!valid.some((check)=>check.checkId === id) || conflicting(id)) reasons.push(`required:${id}`);
    }
    const optionalGaps = spec.optional.filter((id)=>!valid.some((check)=>check.checkId === id) || conflicting(id));
    if (optionalGaps.length && !spec.allowPartial) reasons.push("optional_gap_not_allowed");
    return {
        jobId: spec.id,
        specVersion: spec.version,
        snapshot: spec.snapshot,
        status: reasons.length ? "BLOCKED" : optionalGaps.length ? "PARTIAL" : "COMPLETED",
        nativeStatus: facts.nativeStatus,
        reasons,
        optionalGaps,
        failureHistory: structuredClone(facts.failures)
    };
}
export function presentReceipt(receipt) {
    return [
        `Task ${receipt.jobId}: ${receipt.status}; native: ${receipt.nativeStatus}`,
        `Blockers: ${receipt.reasons.join(", ") || "none"}`,
        `Optional gaps: ${receipt.optionalGaps.join(", ") || "none"}`,
        `Skipped steps: ${receipt.skippedSteps?.map((step)=>`${step.stepId}:${step.reason ?? "reason unknown"}`).join(", ") || "none"}`,
        `Snapshot: ${receipt.snapshot}; spec version: ${receipt.specVersion}`,
        `Failure history: ${receipt.failureHistory.map((f)=>`${f.id}:${f.code}${f.resolvedBy ? " (resolved)" : ""}`).join(", ") || "none"}`
    ].join("\n");
}
