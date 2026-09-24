/**
 * Type guards and utility functions for content block inspection.
 * Extracted from types.ts to keep type definitions pure.
 */
/** Narrow an unknown object before reading keyed fields. */
export declare function isRecord(value: unknown): value is Record<string, unknown>;
/** Type guard for text content blocks */
export declare function isTextBlock(c: unknown): c is {
    type: "text";
    text: string;
};
/** Type guard for tool call content blocks */
export declare function isToolCallBlock(c: unknown): c is {
    type: "toolCall";
    id?: string;
    name: string;
    arguments: Record<string, unknown>;
};
/** Get tool call names from unknown content */
export declare function getToolCallNames(content: unknown): string[];
/** Filter tool call blocks from unknown content */
export declare function filterToolCalls(content: unknown): Array<{
    type: "toolCall";
    id?: string;
    name: string;
    arguments: Record<string, unknown>;
}>;
/**
 * Best-effort runtime validator for `SmartCompactDetails` payloads that we
 * read back from compaction entries on the branch.
 *
 * The branch can contain compactions written by:
 *  - an older version of this extension (different shape),
 *  - a completely different compaction extension (arbitrary shape),
 *  - a corrupted session file.
 *
 * Damage detection passes these straight to `new Set([...])`, so a `null` or a
 * non-array `modifiedFiles` would crash the post-success path. We narrow the
 * shape just enough for `detectDamage` and refuse anything that fails.
 */
import type { SmartCompactDetails } from "../types.ts";
export declare function isValidSmartCompactDetails(d: unknown): d is SmartCompactDetails;
/**
 * Normalize an arbitrary details-ish object so it is safe to feed into damage
 * detection regardless of provenance. Anything that fails the validator gets
 * coerced to an empty-but-typed shape; the caller can then skip work without
 * crashing.
 */
export declare function sanitizeSmartCompactDetails(d: unknown): SmartCompactDetails | null;
//# sourceMappingURL=type-guards.d.ts.map