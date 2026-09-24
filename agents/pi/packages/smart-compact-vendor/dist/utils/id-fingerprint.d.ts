/**
 * Entry-id list fingerprinting for the extraction cache.
 *
 * The extraction cache used to write the full toCompact entry-id array to
 * disk and then re-read it on the next run to verify that the cached
 * extraction's "prefix" was still valid. That scales linearly with session
 * length — a 5k-message session rewrote a 100KB JSON document on every
 * compact, and disk-usage doubled as soon as you turned on auto-trigger.
 *
 * The fingerprint captures only what the cache logic actually inspects:
 *
 *   1. `count` — gives us an O(1) gate before doing any hashing.
 *   2. `tail` — last K ids, cheap first-line check; if the tail differs we
 *      know the prefix differs without computing a hash.
 *   3. `prefixHash` — SHA-256 over `ids.slice(0, count).join("\n")`. This is
 *      the authoritative prefix proof: if `currentIds.slice(0, cached.count)`
 *      hashes to `cached.prefixHash`, the cache is a valid prefix of the
 *      current run.
 *
 * The hash uses `\n` as a separator because pi-coding-agent entry ids are
 * URL-safe and never contain newlines. Tail size of 16 covers the
 * "single new exchange" case (user message + assistant + ≤14 tool turns) so
 * the slow path (hashing) only runs when something meaningful changed.
 */
import type { EntryIdFingerprint } from "../types.ts";
/** Tail length; chosen to cover one "user → assistant → many tool turns" cycle. */
export declare const FINGERPRINT_TAIL_LEN = 16;
export declare function buildEntryIdFingerprint(ids: ReadonlyArray<string>): EntryIdFingerprint;
/** Stable SHA-256 over the first `count` ids joined by `\n`. */
export declare function hashIds(ids: ReadonlyArray<string>, count: number): string;
/**
 * Does `cached` represent a prefix of `currentIds`?
 *
 * Order of checks is deliberate:
 *
 *   1. `cached.count > currentIds.length` → impossible to be a prefix.
 *   2. Tail mismatch at the boundary → we don't need to hash.
 *   3. Hash check confirms the full prefix.
 *
 * Returns false on missing fingerprint (caller should fall back to the
 * legacy full-array compare).
 */
export declare function isPrefixOf(cached: EntryIdFingerprint | undefined, currentIds: ReadonlyArray<string>): boolean;
/**
 * Backwards-compatible prefix check.
 *
 * Newer caches store a fingerprint; older caches store the full id array. We
 * accept both so the v7.13 upgrade path doesn't invalidate every existing
 * cache file at once — the next save rewrites the cache in the new shape.
 */
export declare function legacyPrefixMatch(legacy: ReadonlyArray<string> | undefined, currentIds: ReadonlyArray<string>): boolean;
//# sourceMappingURL=id-fingerprint.d.ts.map