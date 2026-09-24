/**
 * Phase 1: Deterministic extraction — zero LLM calls.
 */
import type { LlmMessage, ProfileConfig, StructuredExtraction, OpenLoop, MediaAttachment } from "../types.ts";
/** pi-toolkit truncation marker: content.slice(0, 20) + `…✂${content.length}` */
export declare const TRUNCATE_RE: RegExp;
/** Reusable tool call index type */
export type ToolCallIndex = Map<string, {
    name: string;
    arguments: Record<string, unknown>;
    msgIndex: number;
}>;
/** Flattened tool-call descriptor (post `multi_tool_use.parallel` expansion). */
export interface FlatToolCall {
    name: string;
    id?: string;
    arguments: Record<string, unknown>;
}
/** Identity contract shared by extraction and pruning for nested parallel calls. */
export declare function nestedToolCallId(wrapperId: string | undefined, messageIndex: number, toolIndex: number, nestedId?: unknown): string;
/**
 * Flatten a single assistant content block into one or more tool-call descriptors.
 * Transparently expands `multi_tool_use.parallel` wrappers into their nested tool_uses.
 * Returns [] for non-tool-call blocks. Used by extraction, topic segmentation, and
 * error-retry detection to avoid re-implementing the parallel-flatten contract.
 */
export declare function flattenToolCallBlock(b: unknown): FlatToolCall[];
/**
 * Flatten an LLM message content payload into a plain string.
 *
 * Accepts `string`, `Array<string | TextBlock | ToolCallBlock | ...>`, or
 * any other shape (which collapses to `""`). Uses `isTextBlock` so the
 * narrowing logic stays in one place — the previous inline
 * `(b as Record<string, unknown>)?.type === "text"` cast trio had to be
 * kept in sync with the real text-block shape by hand.
 */
export declare function extractText(content: unknown): string;
/** Extract attachment metadata without embedding binary/base64 payloads in summaries. */
export declare function extractMediaAttachments(msgs: LlmMessage[]): MediaAttachment[];
export declare function buildToolCallIndex(msgs: readonly LlmMessage[]): ToolCallIndex;
export declare function trackFileOps(msgs: LlmMessage[], _tcIdx?: ToolCallIndex): {
    modified: StructuredExtraction["modifiedFiles"];
    read: string[];
    deleted: string[];
    referenced: string[];
};
/**
 * Preserve the actionable part of a long command failure instead of blindly
 * returning its prefix. The tail is retained as well because shells commonly
 * report their non-zero exit status there.
 */
export declare function commandFailureEvidence(text: string, maxChars: number): string;
export declare function isTransientToolDiagnostic(text: string): boolean;
export declare function catalogErrors(msgs: LlmMessage[], _tcIdx?: ToolCallIndex): StructuredExtraction["errors"];
export declare function extractDecisions(msgs: LlmMessage[], _tcIdx?: ToolCallIndex): StructuredExtraction["decisions"];
export declare function isDiagnosticConstraintText(text: string): boolean;
export declare function mineConstraints(msgs: LlmMessage[]): StructuredExtraction["constraints"];
export declare function segmentTopicsHeuristic(msgs: LlmMessage[], pc: ProfileConfig, maxSegs?: number, _tcIdx?: ToolCallIndex): StructuredExtraction["topics"];
/** Machine status from an earlier compaction is context, not an active user goal. */
export declare function isCompactionStatusText(text: string): boolean;
export declare function extractMainGoal(msgs: LlmMessage[]): string | null;
/** Extract open loops — unresolved tasks from the conversation */
export declare function extractOpenLoops(msgs: LlmMessage[], extraction: StructuredExtraction): OpenLoop[];
/**
 * Run all extractors over a (typically pruned) message list. Accepts an
 * optional pre-built `ToolCallIndex` so callers that have already walked the
 * messages (e.g. the orchestrator caching it on the RunContext) can skip the
 * O(n) rebuild.
 *
 * Important: `tcIdx` must be keyed by the **same** message offsets as `msgs`.
 * Pruning produces an index against the unpruned list; that index is not safe
 * to pass here — build a fresh one over the pruned messages instead.
 */
export declare function extractStructured(msgs: LlmMessage[], pc: ProfileConfig, precomputedTcIdx?: ToolCallIndex): StructuredExtraction;
//# sourceMappingURL=extraction.d.ts.map