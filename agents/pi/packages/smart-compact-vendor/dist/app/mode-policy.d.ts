import type { CompactionMode, CompactionState, CompressionProfile, EffectiveCompactionMode, StructuredExtraction } from "../types.ts";
export interface ModePolicy {
    profile: CompressionProfile;
    maxLlmCalls: number;
    maxInputTokens: number;
    maxOutputTokens: number;
    explore: boolean;
    allowLlmPatch: boolean;
    singlePassMultiplier: number;
    batchOutput: {
        min: number;
        perChunk: number;
        max: number;
    };
    targetContextPercent: number;
}
export declare const MODE_POLICIES: Readonly<Record<EffectiveCompactionMode, ModePolicy>>;
export declare function modeFromLegacyProfile(profile: CompressionProfile): EffectiveCompactionMode;
/** Cheap preflight choice used before deterministic extraction is available. */
export declare function resolveMode(requested: CompactionMode, contextPercent: number, extraction?: StructuredExtraction, additionalRisk?: number): EffectiveCompactionMode;
export declare function deterministicExtractionConfidence(extraction: StructuredExtraction, context?: {
    conversationTokens?: number;
    toolPercent?: number;
}): number;
export declare function continuityRisk(state: CompactionState | null): number;
export declare function batchOutputLimit(mode: EffectiveCompactionMode, chunks: number, providerMax: number): number;
export declare function effectiveBudget(configured: number, modeDefault: number): number;
//# sourceMappingURL=mode-policy.d.ts.map