/** Step 2: select and validate the active-context prefix to summarize. */
import type { CompactionPlanReason, CompactionWindowPlan, PreparedRc, WindowedRc } from "../run-context.ts";
import type { EffectiveCompactionMode, ProfileConfig, ProviderCapabilities, SessionMessageEntry } from "../../types.ts";
import { type TokenEstimator } from "../../utils/tokens.ts";
export type { CompactionWindowPlan } from "../run-context.ts";
export interface CompactionWindowPlanInput {
    msgs: SessionMessageEntry[];
    branch: unknown[];
    messageTokens: number[];
    totalTokens: number;
    modelContextWindow?: number;
    mode: EffectiveCompactionMode;
    profileCfg: ProfileConfig;
    force: boolean;
    /** Estimated final summary size in the same local units as messageTokens. */
    finalSummaryAllowanceTokens?: number;
}
/** Canonical user-facing wording for every planner outcome. */
export declare function compactionPlanReasonText(reason: CompactionPlanReason): string;
/** Pure, content-free result suitable for both execution and a later UI preview. */
export declare function estimateFinalSummaryAllowance(profileCfg: ProfileConfig, estimator: TokenEstimator, providerCaps: ProviderCapabilities | undefined): number;
export declare function planCompactionWindow(input: CompactionWindowPlanInput): CompactionWindowPlan;
export declare function resolveCompactionWindow(rc: PreparedRc): WindowedRc | null;
//# sourceMappingURL=window.d.ts.map