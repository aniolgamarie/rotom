import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { CompactConfig, EffectiveCompactionMode, ProfileConfig, ProviderCapabilities, SessionMessageEntry } from "../types.ts";
import { type TokenCalibrationStore, type TokenEstimator } from "../utils/tokens.ts";
import type { CompactionWindowPlan } from "./run-context.ts";
export declare function preflightDamageMedian(cwd: string, config: CompactConfig): number;
export interface PreparedPreflightProfile {
    profileCfg: ProfileConfig;
    estimator: TokenEstimator;
    providerCaps: ProviderCapabilities;
    adapted: boolean;
    damageMedian: number;
}
/** Shared deterministic preparation used by both the preview and the real run. */
export declare function preparePreflightProfile(input: {
    cwd: string;
    summaryModel: Model<Api>;
    mode: EffectiveCompactionMode;
    tokenCalibration: TokenCalibrationStore;
    config: CompactConfig;
    damageMedian?: number;
}): PreparedPreflightProfile;
export interface ManualPreflight {
    mode: EffectiveCompactionMode;
    plan: CompactionWindowPlan | null;
    reason: CompactionWindowPlan["reason"] | "not-enough-messages";
    profileCfg: ProfileConfig;
    totalTokens: number;
    rawEstimatedMessageTokens: number;
    estimatorScale: number;
    adapted: boolean;
    damageMedian: number;
    contextWindowTokens: number;
    contextPercent: number;
    toolPercent: number;
    overflowedContext: boolean;
}
export interface ManualPreflightContext {
    branch: unknown[];
    msgs: SessionMessageEntry[];
    messageTokens: number[];
    totalTokens: number;
    rawEstimatedMessageTokens: number;
    modelContextWindow?: number;
    contextWindowTokens: number;
    contextPercent: number;
    toolPercent: number;
    overflowedContext: boolean;
}
/** Mode-independent session scan shared by all three preview plans. */
export declare function prepareManualPreflightContext(ctx: ExtensionContext, summaryModel: Model<Api>, tokenCalibration: TokenCalibrationStore): ManualPreflightContext;
export declare function planManualPreflight(ctx: ExtensionContext, summaryModel: Model<Api>, mode: EffectiveCompactionMode, tokenCalibration: TokenCalibrationStore, config: CompactConfig, damageMedian?: number, shared?: ManualPreflightContext): ManualPreflight;
//# sourceMappingURL=preflight.d.ts.map