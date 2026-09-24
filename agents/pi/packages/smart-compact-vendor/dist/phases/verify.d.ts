/**
 * Phase 4: deterministic verification and repair.
 *
 * Verification findings are structured data. Formatting belongs at the UI/LLM
 * boundary; repair logic switches on `kind` and never reparses its own prose.
 */
import type { Model, Api, ProviderHeaders } from "@earendil-works/pi-ai";
import type { CompactionState, StructuredExtraction, VerificationGap, VerificationGateStage, VerificationResult, LlmMessage } from "../types.ts";
import type { SmartCompactServices } from "../infra/services.ts";
export interface VerificationEvidence {
    sourceMessages?: readonly LlmMessage[];
    steering?: {
        focus?: string;
        note?: string;
    };
    summaryBudgetTokens?: number;
}
export declare function formatVerificationGap(gap: VerificationGap): string;
export declare function verificationFailureMessage(result: VerificationResult): string | null;
/** Content-free diagnostics survive the throw without leaking evidence to telemetry. */
export declare class VerificationGateError extends Error {
    readonly score: number;
    readonly initialScore: number;
    readonly gapKinds: VerificationGap["kind"][];
    readonly stage: VerificationGateStage;
    readonly gapCount: number;
    constructor(result: VerificationResult, initialScore: number, stage: VerificationGateStage);
}
export declare function isDeterministicallyPatchable(gap: VerificationGap): boolean;
/** Apply safe repairs to a fixed point; newly introduced patchable gaps get another bounded pass. */
export declare function repairSummaryDeterministically(summary: string, result: VerificationResult, extraction: StructuredExtraction, continuity?: CompactionState | null, evidence?: VerificationEvidence, maxRounds?: number): {
    summary: string;
    result: VerificationResult;
    patched: VerificationGap[];
};
export declare function verifySummary(summary: string, extraction: StructuredExtraction, continuity?: CompactionState | null, evidence?: VerificationEvidence): VerificationResult;
/** Apply every safe, deterministic repair. Hallucination/inconsistency gaps stay visible for LLM/user review. */
export declare function patchDeterministic(summary: string, gaps: VerificationGap[], extraction: StructuredExtraction, continuity?: CompactionState | null, evidence?: VerificationEvidence): string;
export declare function patchSummary(summary: string, gaps: VerificationGap[], model: Model<Api>, auth: {
    apiKey: string;
    headers?: ProviderHeaders;
}, signal?: AbortSignal, services?: SmartCompactServices): Promise<string>;
//# sourceMappingURL=verify.d.ts.map