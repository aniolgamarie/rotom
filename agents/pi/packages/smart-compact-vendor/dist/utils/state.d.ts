/**
 * Build structured machine-readable compaction state.
 * Produced alongside the human-readable Markdown summary.
 * Supports cross-compaction tracking and delta computation.
 */
import type { StructuredExtraction, OpenLoop, CompactionState, ExplorationReport, LoopOverride, ContinuityOverride, ContinuityScope } from "../types.ts";
export declare function sanitizeCompactionStateEvidence(state: CompactionState): CompactionState;
/**
 * Persist compaction state for cross-compaction tracking.
 *
 * Atomic temp+rename writes via writeJsonSync ensure that a crash mid-save
 * leaves the previous valid state file untouched instead of a truncated JSON
 * blob that would crash the next loadCompactionState parse.
 */
export declare function saveCompactionState(projectId: string, state: CompactionState): boolean;
/**
 * Load previous compaction state for delta computation.
 */
export declare function loadCompactionState(projectId: string): CompactionState | null;
export declare function loadScopedCompactionState(scope: Pick<ContinuityScope, "projectId" | "sessionId"> & Partial<Pick<ContinuityScope, "branchHeadId">>, branchEntryIds?: readonly string[]): CompactionState | null;
export declare function applyLoopOverrides(loops: OpenLoop[], overrides: LoopOverride[]): OpenLoop[];
export declare function upsertLoopOverride(overrides: LoopOverride[], loop: OpenLoop, patch: Partial<Omit<LoopOverride, "id" | "summaryKey">>): LoopOverride[];
export declare function upsertContinuityOverride(overrides: ContinuityOverride[], kind: ContinuityOverride["kind"], text: string, patch: Pick<ContinuityOverride, "status"> & Partial<Pick<ContinuityOverride, "replacement">>): ContinuityOverride[];
export declare function buildCompactionState(extraction: StructuredExtraction, openLoops: OpenLoop[], report: ExplorationReport | null, nextActions: string[], criticalContext: string[], loopOverrides?: LoopOverride[]): CompactionState;
/**
 * Conservative cross-compaction merge: neither absence nor free-form goal text
 * is evidence that a decision, constraint, error, or loop was resolved.
 * Current facts win, old unresolved facts remain, and every collection is
 * bounded so continuity cannot grow without limit. Goal shifts are recorded as
 * context; only positive resolution evidence or an explicit override retires a fact.
 */
export declare function mergeCompactionStates(previous: CompactionState | null, current: CompactionState): CompactionState;
/** Build the bounded, deterministic context that must survive every generation. */
export declare function renderContinuityCapsule(state: CompactionState, maxChars?: number, existing?: string): string;
/**
 * Inject Open Loops section into the Markdown summary.
 *
 * Implementation goes through the canonical summary parser so that string
 * variants of "## Next Steps" (different capitalization, an extra blank line,
 * H3 instead of H2) still result in `Open Loops` being placed *before* the
 * next-steps section. Falls back to append-at-end when the section is absent.
 */
export declare function injectOpenLoopsSection(summary: string, openLoops: OpenLoop[]): string;
/**
 * Compute delta between previous and current compaction state.
 */
export interface CompactionDelta {
    /** Decisions added since last compaction */
    newDecisions: string[];
    /** Decisions that appear to have been superseded or removed */
    removedDecisions: string[];
    /** Open loops that were resolved */
    resolvedLoops: string[];
    /** Open loops still open from last time */
    persistentLoops: string[];
    /** New open loops */
    newLoops: string[];
    /** Files modified since last compaction */
    newModifiedFiles: string[];
    /** Errors that were resolved since last compaction */
    resolvedErrors: string[];
    /** New unresolved errors */
    newErrors: string[];
    /** Goal changed? */
    goalChanged: boolean;
    /** Previous goal if changed */
    previousGoal: string | null;
}
export declare function computeDelta(prev: CompactionState, current: CompactionState): CompactionDelta;
export declare function hasDeltaChanges(delta: CompactionDelta): boolean;
/**
 * Format delta as Markdown section for injection into summary.
 */
export declare function formatDeltaSection(delta: CompactionDelta): string;
/**
 * Inject delta section into summary.
 *
 * Placement priority:
 *  1. Immediately after `## Open Loops` if present.
 *  2. Immediately before `## Next Steps` otherwise.
 *  3. Append at the end.
 *
 * Works on the canonical parsed form, so heading-format drift cannot misorder
 * the delta section.
 */
export declare function injectDeltaSection(summary: string, delta: CompactionDelta): string;
/**
 * Ensure user-pinned paths ("never compact") appear in the summary. Any pinned
 * path not already mentioned is appended to the Files Read section so it
 * survives compaction regardless of what the LLM chose to include. This is a
 * deterministic, LLM-free guarantee — the pin wins over synthesis output.
 */
export declare function ensurePinnedPaths(summary: string, pinned: readonly string[]): string;
/**
 * Extract next actions from the summary's "Next Steps" section.
 */
export declare function extractNextActions(summary: string): string[];
/**
 * Extract critical context lines from the summary.
 */
export declare function extractCriticalContext(summary: string): string[];
//# sourceMappingURL=state.d.ts.map