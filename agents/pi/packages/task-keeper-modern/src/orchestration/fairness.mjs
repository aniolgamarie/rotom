import { finiteInteger, identifier } from "../contracts/primitives.mjs";
export const MAX_BASE_PRIORITY = 100;
export const DEFAULT_SCHEDULING = {
    agingMs: 60000,
    priorities: {
        inspect: 0,
        fix: 0
    }
};
export function selectReadyCandidate(candidates, now, agingMs) {
    finiteInteger(now);
    finiteInteger(agingMs, 1, 2147483647);
    const ranked = candidates.map((candidate)=>{
        identifier(candidate.jobId);
        identifier(candidate.stepId);
        finiteInteger(candidate.readyAt);
        finiteInteger(candidate.priority, 0, MAX_BASE_PRIORITY);
        return {
            jobId: candidate.jobId,
            stepId: candidate.stepId,
            readyAt: candidate.readyAt,
            effectivePriority: candidate.priority + Math.floor(Math.max(0, now - candidate.readyAt) / agingMs)
        };
    });
    ranked.sort((a, b)=>b.effectivePriority - a.effectivePriority || a.readyAt - b.readyAt || a.jobId.localeCompare(b.jobId) || a.stepId.localeCompare(b.stepId));
    return ranked[0] ? {
        ...ranked[0],
        reason: "priority+ready-aging; ready-time; stable-id"
    } : null;
}
