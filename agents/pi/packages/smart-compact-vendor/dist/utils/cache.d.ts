/**
 * Extraction cache, metrics, and cache-aware LLM options.
 *
 * Filesystem writes go through `src/infra/fs.ts` (atomic temp+rename for
 * snapshots, advisory lock for the metrics append log) so that two pi
 * sessions racing to compact the same project cannot corrupt each other's
 * state. All LLM I/O routes through the services bag's `llm` client so tests
 * can swap a fake provider in without resolving the real peer dependency.
 */
import type { LLMCallMetric, StructuredExtraction, CachedExtraction, CacheAwareOptions, CompactMetricsEntry, LlmMessage } from "../types.ts";
import { type ToolCallIndex } from "./extraction.ts";
import type { Model, Api, AssistantMessage, Context } from "@earendil-works/pi-ai";
import { type SmartCompactServices } from "../infra/services.ts";
export declare function recordMetric(m: LLMCallMetric, services: SmartCompactServices): void;
export declare function effectivePromptInputTokens(inputTokens: number, cacheHitTokens: number, cacheWriteTokens?: number): number;
export declare function getMetricsSummary(services: SmartCompactServices): {
    totalCalls: number;
    totalInput: number;
    totalOutput: number;
    totalCacheHit: number;
    totalCacheWrite: number;
    avgLatency: number;
    cacheHitRate: number;
};
export declare function trackedComplete(phase: LLMCallMetric["phase"], model: Model<Api>, reqBody: Context, opts: CacheAwareOptions, services?: SmartCompactServices): Promise<AssistantMessage>;
export declare function getExtractionCacheStats(services: SmartCompactServices): {
    hits: number;
    misses: number;
    hitRate: number;
};
export declare function recordExtractionCacheHit(services: SmartCompactServices): void;
export declare function recordExtractionCacheMiss(services: SmartCompactServices): void;
/**
 * Save extraction cache with entry-id fingerprints for branch-aware
 * invalidation.
 *
 * We store **compact fingerprints** rather than the raw id arrays so the cache
 * file stays a few hundred bytes regardless of session size. The fingerprint
 * carries enough information (count + tail + prefix hash) for the next run to
 * prove that the cached extraction's domain is a strict prefix of the current
 * pruned/unpruned conversation.
 *
 * @param msgCount — Length of the **pruned** llmMessages array. This is the
 *   domain for all index-bearing fields inside `extraction` (topics, errors,
 *   decisions, etc.). It must NOT be the unpruned toCompact length.
 * @param entryIds — FULL ordered list of original toCompact entry IDs. Used
 *   for branch/pivot detection on subsequent incremental runs.
 * @param keptEntryIds — Ordered entry IDs that survived pruning. This is the
 *   index domain used for safe incremental extraction prefix matching.
 */
export declare function saveCachedExtraction(sessionId: string, extraction: StructuredExtraction, msgCount: number, firstEntryId?: string, lastEntryId?: string, entryIds?: string[], keptEntryIds?: string[]): void;
export declare function loadCachedExtraction(sessionId: string): CachedExtraction | null;
export declare function mergeExtractions(base: StructuredExtraction, delta: StructuredExtraction, baseMsgCount: number, deltaMessages?: LlmMessage[], deltaToolCalls?: ToolCallIndex): StructuredExtraction;
/** Append a fully materialized payload after an external lifecycle commits. */
export declare function appendMetricsSnapshot(sessionId: string, snapshot: Omit<CompactMetricsEntry, "ts" | "sessionId">): Promise<boolean>;
export declare function appendMetricsLog(sessionId: string, extra: Partial<Omit<CompactMetricsEntry, "ts" | "sessionId" | "totalCalls" | "totalInput" | "totalOutput" | "totalCacheHit" | "totalCacheWrite" | "avgLatency" | "cacheHitRate">> | undefined, services: SmartCompactServices): Promise<boolean>;
/**
 * Read the last `limit` valid entries from the metrics log without loading
 * the whole file. We start from the tail, walking backwards in 64 KB chunks
 * until we have enough lines (`limit * 4` raw lines is a generous safety
 * factor against corrupt entries that get filtered out). The old
 * implementation read the entire log into memory before slicing, which on
 * a long-lived install with a multi-megabyte log was a noticeable IO + GC
 * hit on every dashboard render.
 *
 * Behavior guarantees:
 *   - At most `limit` entries returned (always sliced from the tail).
 *   - Corrupt JSON lines are dropped with a warning, NOT counted toward limit.
 *   - Returned in chronological order (oldest -> newest within the window).
 */
export declare function readMetricsLog(limit?: number): CompactMetricsEntry[];
//# sourceMappingURL=cache.d.ts.map