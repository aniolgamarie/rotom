/**
 * Path-segment-suffix needle generator used by `extractOpenLoops` to attach
 * unresolved errors to specific files.
 *
 * The naive approach (basename match) produces massive false positives:
 * common filenames like `index.ts`, `types.ts`, `helpers.ts` appear in
 * almost every error message that mentions ANY file, so a "TypeError in
 * index.ts" snippet would erroneously surface as a bugfix loop for every
 * `index.ts` the session ever touched.
 *
 * The needles we emit are progressively-longer suffix slices:
 *
 *   path = "src/app/steps/persist.ts"
 *   needles = [
 *     "persist.ts",                       // basename, only when specific
 *     "steps/persist.ts",
 *     "app/steps/persist.ts",
 *     "src/app/steps/persist.ts",         // full path
 *   ]
 *
 * The caller matches each needle against the error message (substring,
 * case-insensitive). For generic basenames or very short ones we drop the
 * bare-basename needle so a bare "index.ts" in an error never attaches to
 * an unrelated `index.ts` from somewhere else in the tree.
 */
/**
 * Basenames that appear too often across unrelated files to be a useful
 * standalone match. Anything here is only attached when the error mentions
 * the full `dir/<basename>` segment.
 *
 * Exported so tests can verify the gate and so future contributors can
 * extend the list at one well-known location.
 */
export declare const GENERIC_BASENAMES: ReadonlySet<string>;
/** Bare basenames shorter than this are also dropped (too weak a signal). */
export declare const MIN_BARE_BASENAME_LEN = 5;
/**
 * Build the suffix-needle list for a path. Returns an empty array for the
 * empty path; otherwise the longest needle is always the full normalized
 * path. All needles are lowercased so substring matching can be done with
 * `errorMessage.toLowerCase().includes(needle)` cheaply.
 */
export declare function normalizePath(filePath: string): string;
export declare function buildPathNeedles(filePath: string): string[];
/**
 * Return only suffixes that identify exactly one path in the supplied set.
 * A bare `auth.ts` is useful when unique, but must not let one monorepo package
 * satisfy verification for every sibling package that owns an `auth.ts`.
 */
export declare function buildUniquePathNeedles(filePath: string, allPaths: readonly string[]): string[];
/** Whether an extracted file reference can refer to at least one known path. */
export declare function isKnownPathReference(ref: string, knownPaths: readonly string[]): boolean;
//# sourceMappingURL=file-needles.d.ts.map