/**
 * Canonical summary schema.
 *
 * The summary that smart-compact produces is consumed by humans (in the result
 * screen and `Pending Compaction` banner) but also re-parsed downstream by the
 * verification phase and by the delta extractor. Originally everything spoke
 * Markdown, and verification ran on string `lower.includes("## goal")`-style
 * checks. That meant:
 *
 *  - A model that emitted `### Goal` or `## Goals` slipped past the check and
 *    triggered a false `Missing section` gap.
 *  - Reordering / renaming sections by an aggressive provider caused phantom
 *    gaps that triggered an LLM patch call — burning tokens just to restore
 *    text the summary already contained.
 *  - Adding new sections required touching three modules (synthesize prompts,
 *    verify regexes, delta injectors).
 *
 * The fix is a tiny canonical representation: a discriminated `Section` array
 * with a `kind` tag. Markdown stays the human/LLM interface, but everything we
 * actually *check* runs on the parsed `CanonicalSummary`. Verification asks
 * "does a section with kind=goal exist?", not "does the lowercased string
 * contain '## goal'".
 *
 * We do not try to parse the body of every section into structured fields
 * here. Body text remains free-form so the LLM can express nuance. Specific
 * sections (`progress`, `files-modified`, etc.) have their bodies inspected
 * by helpers in `summary-parse.ts` when the verification logic needs to look
 * deeper.
 */
export type SectionKind = "goal" | "constraints" | "progress" | "decisions" | "files-modified" | "files-read" | "files-deleted" | "next-steps" | "critical-context" | "topics" | "open-loops" | "changes" | "verification-note" | "unknown";
export interface Section {
    kind: SectionKind;
    /** Parsed heading with normalized H2 depth; the user-facing label is preserved. */
    heading: string;
    /** Body of the section, leading/trailing whitespace trimmed. */
    body: string;
}
export interface CanonicalSummary {
    sections: Section[];
}
/**
 * Map a free-form heading text to a known `SectionKind`. We match generously
 * because LLMs reshape capitalization and punctuation: `## Goal`, `# Goal`,
 * `Goals:`, `## GOAL` should all resolve to `goal`.
 */
export declare function classifyHeading(raw: string): SectionKind;
/** Canonical heading text used when synthesizing a missing section. */
export declare function canonicalHeading(kind: SectionKind): string;
//# sourceMappingURL=summary-schema.d.ts.map