/**
 * Session log reader — bypasses pi-toolkit truncation by reading the
 * original untruncated conversation from pi-coding-agent's .jsonl session log.
 *
 * pi-toolkit's context hook mutates branch entries in-place (tool results
 * truncated to `…✂N`), but the disk log retains the original content until
 * pi-coding-agent itself overwrites it on session save. This module reads
 * from the log and falls back to the branch when the log is unavailable.
 *
 * Recovery strategy (ID-based):
 *  - Branch entries each carry a unique `id`.
 *  - The session .jsonl log also records `id` per entry.
 *  - We build a Map<entryId, LlmMessage> from the log and then walk the
 *    branch's toCompact entries in order, substituting the original
 *    (untruncated) message when the id matches. This avoids tail-slice
 *    misalignment completely.
 */
import type { LlmMessage, SessionMessageEntry } from "../types.ts";
/**
 * Maximum entries kept per cache. Both caches were previously unbounded:
 * `logPathCache` had a TTL but no size cap, and `messageMapCache` had no
 * eviction at all (only mtime-driven overwrite). In long-running pi
 * processes that hop between many sessions — sub-agent workflows are a
 * common offender — the message-map cache can hold dozens of giant
 * Map<entryId, LlmMessage> instances indefinitely, each potentially many
 * megabytes. We cap both with a tiny LRU: cheap to maintain, never holds
 * more than `getMaxEntries()` sessions, and re-fetching an evicted entry
 * is a single mtime+stream-parse — already fast and rarely triggered.
 *
 * The default (8) is tuned for a typical interactive workflow. Heavy
 * sub-agent orchestration may want a larger window; set
 * `SMART_COMPACT_LOG_CACHE_MAX` in the environment to override. Invalid
 * values (non-numeric, <=0) silently fall back to the default so a typo
 * in `.env` never disables the cache entirely.
 *
 * We read the env on every call (rather than memoizing at module load) so
 * tests can mutate `process.env.SMART_COMPACT_LOG_CACHE_MAX` between cases
 * without reloading the module. The cost is one env lookup + one parseInt
 * per cache write, which is negligible compared with the surrounding fs
 * stat + JSONL parse.
 */
/**
 * @internal Exposed for unit tests; production callers should NOT depend on
 * this directly. Reads `SMART_COMPACT_LOG_CACHE_MAX` from the environment
 * on every call so tests can mutate process.env between cases.
 */
export declare function _getMaxEntriesForTests(): number;
/** @internal Test-only: drop both module caches between cases. */
export declare function __resetSessionLogCachesForTests(): void;
/**
 * Check if any message in the array has been truncated by pi-toolkit.
 */
export declare function hasTruncatedMessages(msgs: LlmMessage[]): boolean;
export interface ResolvedCompactionMessage {
    entryId: string;
    message: LlmMessage;
}
/**
 * Recover untruncated messages while preserving the exact entry-id/message
 * association after `convertToLlm` filters context-excluded branch entries.
 *
 * Each returned tuple is in the same domain as the LLM messages. Raw branch
 * cardinality is deliberately not preserved: entries excluded from provider
 * context must not shift cache fingerprints for every later message.
 */
export declare function resolveCompactionMessages(sessionId: string, toCompactEntries: SessionMessageEntry[], cwd?: string): Promise<ResolvedCompactionMessage[] | null>;
//# sourceMappingURL=session-log.d.ts.map