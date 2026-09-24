/**
 * Pre-compaction redundancy pruning — deterministic, zero LLM cost.
 * Reduces compaction input by collapsing redundant message sequences.
 */
import type { LlmMessage } from "../types.ts";
import { type ToolCallIndex } from "./extraction.ts";
export interface PruningResult {
    messages: LlmMessage[];
    /** Original input indexes retained in `messages`; same order as `messages`. */
    keptIndices: number[];
    prunedCount: number;
    prunedTokenSaving: number;
    reasons: Array<{
        count: number;
        reason: string;
    }>;
}
/**
 * Detect and collapse redundant message sequences.
 *
 * @param msgs   Input message list (unpruned).
 * @param tcIdx  Optional pre-computed tool-call index. When the caller has
 *               already built the index (e.g. orchestrator caching it on the
 *               RunContext), passing it here avoids a second O(n) walk over
 *               every assistant message.
 */
export declare function pruneRedundant(msgs: LlmMessage[], precomputedTcIdx?: ToolCallIndex): PruningResult;
//# sourceMappingURL=pruning.d.ts.map