/**
 * Markdown ↔ CanonicalSummary parser.
 *
 * The synthesis phase produces markdown because LLMs and humans both read it
 * well. Verification, patching, and delta-injection used to operate by
 * lowercasing the markdown and substring-scanning for headings, which gave
 * us a long tail of regex fragility: `## Goal` matched but `### Goal` did not,
 * `Files Modified` matched but `Files modified` had to be lowercased first,
 * etc.
 *
 * This module performs one structural parse up front: H1/H2 headings and
 * recognized canonical H3 headings start sections. Unknown H3 headings remain
 * in their parent body so Progress subsections retain their structure. After
 * that, the rest of the code can ask `findSection(summary, "goal")` and let
 * the classifier handle aliases.
 *
 * Duplicate recognized kinds are merged at their first position with exact
 * duplicate body lines removed. Unknown sections remain independent.
 */
import type { CanonicalSummary, Section, SectionKind } from "./summary-schema.ts";
/** Collapse untrusted extracted evidence to one Markdown-safe line. */
export declare function summaryEvidenceLine(value: string, maxLength: number): string;
/**
 * Build stable, collision-resistant path evidence within one aggregate budget.
 * Small sets remain lossless; large sets retain a readable tail plus a digest.
 */
export declare function buildSummaryPathEvidence(paths: readonly string[], budgetTokens?: number): Map<string, string>;
export declare function parseSummary(markdown: string): CanonicalSummary;
/** Find the first section matching the requested kind. */
export declare function findSection(summary: CanonicalSummary | string, kind: SectionKind): Section | undefined;
export declare function hasSection(summary: CanonicalSummary | string, kind: SectionKind): boolean;
/** Stringify the canonical form back to markdown.
 *
 * `opts.canonicalHeadings` rewrites recognized headings to their canonical
 * form. Patch routines turn this on so downstream verification cannot miss a
 * section because the LLM emitted `### Goal` instead of `## Goal`.
 */
export declare function renderSummary(summary: CanonicalSummary, opts?: {
    canonicalHeadings?: boolean;
}): string;
/**
 * Placement hint for `upsertSection` when inserting a *new* section.
 *
 * `before`/`after` name the *kind* of an existing section that the new entry
 * should anchor against. `before` inserts immediately ahead of the anchor;
 * `after` inserts immediately behind it. When both are given, `before` wins
 * (kept for back-compat with positional callers). When neither anchor is found
 * the section falls back to append-at-end.
 *
 * This is how the synthesis pipeline keeps `Open Loops` ahead of `Next Steps`
 * deterministically, and the delta injector places `Changes Since Last
 * Compaction` directly after `Open Loops` when present.
 */
export interface SectionPlacement {
    before?: SectionKind;
    after?: SectionKind;
}
/**
 * Insert or replace a section. If a section with the same `kind` exists, its
 * heading is replaced with the canonical one and the body is overwritten. If
 * not, the section is inserted according to `placement` (or appended).
 */
export declare function upsertSection(summary: CanonicalSummary, kind: SectionKind, body: string, placement?: SectionKind | SectionPlacement): CanonicalSummary;
/**
 * Append text to an existing section body. If the section is missing, it is
 * created with the provided body. This is the structural equivalent of the
 * old `findOrCreateSectionInsert` helper in `verify.ts`.
 */
export declare function appendToSection(summary: CanonicalSummary, kind: SectionKind, text: string, fallbackBody?: string): CanonicalSummary;
//# sourceMappingURL=summary-parse.d.ts.map