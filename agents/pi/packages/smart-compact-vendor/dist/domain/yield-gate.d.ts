import type { CompactionWindowPlan } from "../app/run-context.ts";
export interface CompactionYieldEstimate {
    plannedAfterTokens: number;
    plannedSavedTokens: number;
    plannedYield: number;
    estimatedAfterTokens: number;
    estimatedSavedTokens: number;
    estimatedYield: number;
    retainedTailTokens: number;
    summaryTokens: number;
    summaryBudgetTokens: number;
    targetAfterTokens: number;
    relaxedSoftBoundaries: CompactionWindowPlan["relaxedSoftBoundaries"];
    hardBoundaryAdjusted: boolean;
}
/** Content-free failure raised before any compaction side effect. */
export declare class YieldGateError extends Error implements CompactionYieldEstimate {
    readonly reason: "target-miss" | "insufficient-saving";
    readonly name = "YieldGateError";
    constructor(reason: "target-miss" | "insufficient-saving", estimate: CompactionYieldEstimate);
    plannedAfterTokens: number;
    plannedSavedTokens: number;
    plannedYield: number;
    estimatedAfterTokens: number;
    estimatedSavedTokens: number;
    estimatedYield: number;
    retainedTailTokens: number;
    summaryTokens: number;
    summaryBudgetTokens: number;
    targetAfterTokens: number;
    relaxedSoftBoundaries: CompactionWindowPlan["relaxedSoftBoundaries"];
    hardBoundaryAdjusted: boolean;
}
export declare function verifyCompactionYield(totalTokens: number, summaryTokens: number, plan: CompactionWindowPlan): CompactionYieldEstimate;
//# sourceMappingURL=yield-gate.d.ts.map