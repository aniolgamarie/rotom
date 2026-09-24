/**
 * Phase 3: Hierarchical Synthesis.
 */
import type { Model, Api, ProviderHeaders } from "@earendil-works/pi-ai";
import type { LlmMessage, LlmChunk, ChunkSummary, StructuredExtraction, ExplorationReport, ProfileConfig, CompactionState } from "../types.ts";
import { type TokenEstimator } from "../utils/tokens.ts";
import type { SmartCompactServices } from "../infra/services.ts";
export declare function chunkLlmMessages(msgs: LlmMessage[], boundaries: import("../types.ts").TopicBoundary[], pc: ProfileConfig, estimator?: TokenEstimator, focus?: string): LlmChunk[];
export declare function singlePassCompact(convText: string, extraction: StructuredExtraction, report: ExplorationReport | null, prevContext: string, model: Model<Api>, auth: {
    apiKey: string;
    headers?: ProviderHeaders;
}, budgetTokens: number, signal?: AbortSignal, services?: SmartCompactServices, focus?: string): Promise<{
    summary: string;
    llmCalls: 1;
}>;
export declare function summarizeBatch(batch: LlmChunk[], extraction: StructuredExtraction, model: Model<Api>, auth: {
    apiKey: string;
    headers?: ProviderHeaders;
}, signal?: AbortSignal, services?: SmartCompactServices, maxOutputTokens?: number, cacheScope?: string): Promise<ChunkSummary[]>;
export declare function assembleLLM(summaries: ChunkSummary[], extraction: StructuredExtraction, report: ExplorationReport | null, model: Model<Api>, auth: {
    apiKey: string;
    headers?: ProviderHeaders;
}, budget: number, prevContext: string, signal?: AbortSignal, services?: SmartCompactServices, focus?: string, continuity?: CompactionState | null): Promise<string>;
export declare function assembleFallback(summaries: ChunkSummary[], extraction: StructuredExtraction, steering?: {
    focus?: string;
    note?: string;
}, budgetTokens?: number, continuity?: CompactionState | null): string;
/**
 * Build a placeholder {@link ChunkSummary} when a batch's LLM call failed, so the
 * assembly step still has something deterministic to merge rather than
 * dropping the segment silently. Co-located with `assembleFallback` so both
 * fallback contracts live in the algorithm layer (no I/O, trivially testable).
 */
export declare function failedChunkSummary(ch: LlmChunk): ChunkSummary;
//# sourceMappingURL=synthesize.d.ts.map