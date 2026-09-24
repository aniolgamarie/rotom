/**
 * General helpers: config, backup, batching, preprocessing.
 */
import type { ChunkSummary, ExplorationReport, LlmChunk, SessionMessageEntry, SessionType, StructuredExtraction } from "../types.ts";
export { loadConfig, resetConfigCache, validateSmartCompactConfig, } from "./config.ts";
export declare function getPreviousCompactionContext(branch: unknown[]): string;
export type SmartBoundaryKind = "anchor" | "topical";
/** Return soft boundary candidates in application order. */
export declare function smartKeepBoundaryCandidates(msgs: SessionMessageEntry[], keepFromIndex: number, branchEntries?: unknown[]): Array<{
    kind: SmartBoundaryKind;
    keepFrom: number;
}>;
export declare function smartKeepBoundary(msgs: SessionMessageEntry[], keepFromIndex: number, branchEntries?: unknown[]): number;
/**
 * Tool-call boundary guard: never split a toolCall / toolResult pair across the compaction boundary.
 *
 * If a kept message is a toolResult whose corresponding toolCall would be compacted,
 * pull keepFrom back to include the assistant message containing that toolCall.
 * This prevents "tool_call_id is not found" API errors after compaction.
 *
 * Also handles multi_tool_use.parallel wrappers where the actual tool call IDs are nested
 * inside arguments.tool_uses rather than on the wrapper block itself.
 */
export type ToolCallBoundaryIndex = ReadonlyMap<string, number>;
export declare function buildToolCallBoundaryIndex(msgs: SessionMessageEntry[]): ToolCallBoundaryIndex;
export declare function guardToolCallBoundary(msgs: SessionMessageEntry[], keepFrom: number, tcMap?: ToolCallBoundaryIndex): number;
/**
 * Prefer summarizing a complete tool exchange when pulling its call backward
 * would exceed the retention target. Returns msgs.length when no later kept
 * message exists; callers can then retain the pair or reject the plan.
 */
export declare function advancePastToolCallBoundary(msgs: SessionMessageEntry[], keepFrom: number, tcMap?: ToolCallBoundaryIndex): number;
export declare function createBatches(chunks: LlmChunk[], maxTokens: number): LlmChunk[][];
export declare function preProcessSummaries(summaries: ChunkSummary[], budgetTokens?: number, focus?: string): {
    decisions: string[];
    modified: string[];
    read: string[];
    deleted: string[];
    text: string;
};
export declare function normalizeFactKey(text: string): string;
export declare function buildExtractionContext(extraction: StructuredExtraction, forRange?: {
    start: number;
    end: number;
}): string;
/**
 * Compute tool-output character percentage from branch entries.
 * Mirrors pi-toolkit's context hook logic for consistent tier decisions.
 */
export declare function computeToolCharPercentage(branchEntries: readonly unknown[]): number;
export type CompactionTier = "none" | "light" | "full";
export declare function selectCompactionTier(contextPercent: number, totalTokens: number, minThreshold: number, minContextPercent?: number): CompactionTier;
export declare function inferSessionType(extraction: StructuredExtraction, report: ExplorationReport | null): SessionType;
export declare function buildExplorationContext(report: ExplorationReport): string;
//# sourceMappingURL=helpers.d.ts.map