/**
 * Session-identity resolution.
 *
 * Pi's `sessionManager.getSessionId()` is typed as `string` and in normal
 * operation always returns a real id. We still defend against a transient
 * `undefined` (older host versions, mocked test contexts, race conditions
 * during shutdown) — but the previous fallback used a *sentinel literal*
 * (`"unknown"`) which silently re-opened the very cross-session leak that
 * `PendingCompaction.sessionId` was introduced to close:
 *
 *   Session A: getSessionId() → undefined → stored as "unknown"
 *   Session B: getSessionId() → undefined → compared as "unknown"
 *   "unknown" === "unknown"  ⇒  payload from A is applied to B.
 *
 * The fix is to make the fallback *unforgeable*: every unresolved call
 * yields a fresh, namespaced id (`unresolved:<random>`). Two unresolved
 * sessions therefore can never collide. The `unresolved:` prefix is also
 * a useful diagnostic signal — debug logs / metrics can see at a glance
 * that the host did not surface a real session id.
 *
 * Centralizing the helper guarantees the producer (window stage) and the
 * consumer (session_before_compact guard) agree on the exact contract;
 * no caller is allowed to reinvent the fallback locally.
 */
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
/**
 * Minimal structural slice of `ExtensionContext` we need. Using
 * `Pick<ExtensionContext, "sessionManager">` instead of an ad-hoc
 * `interface CtxLike` ties the helper to the real host contract: if the
 * upstream surface changes, this signature changes with it and the
 * compiler flags every caller — we can no longer silently accept any
 * object that happens to expose a `sessionManager` field.
 */
export type SessionIdentityContext = Pick<ExtensionContext, "sessionManager">;
/** Extract the complete ordered ancestry exposed by a session branch. */
export declare function branchEntryIds(branch: Iterable<{
    id?: unknown;
}>): string[];
export declare const MAX_BRANCH_LINEAGE_IDS = 512;
/**
 * Bound persisted/queried lineage while retaining the leaves immediately
 * preceding compaction entries. Those parent IDs are the branch heads used by
 * scoped state snapshots and can otherwise fall far outside a recent tail.
 */
export declare function boundedBranchLineageIds(branch: Iterable<{
    id?: unknown;
    parentId?: unknown;
    type?: unknown;
}>, maxEntries?: number): string[];
/**
 * Resolve the current pi session id, or mint a per-call sentinel that can
 * never compare equal to another caller's sentinel.
 *
 * Callers should treat the returned string as opaque; only equality against
 * another id from the same process is meaningful (which is precisely the
 * cross-session-leak guard's contract).
 *
 * The fallback uses `crypto.randomUUID()` (122 bits of randomness, ~12x
 * more entropy than the previous 48-bit hex) and is the idiomatic Node /
 * Bun way to obtain a process-unique token without external deps.
 */
export declare function resolveSessionId(ctx: SessionIdentityContext): string;
/**
 * True when `id` was produced by `resolveSessionId` as a fallback (no real
 * session id was available). Used by guards that want to refuse to act on
 * an unidentifiable session entirely, rather than relying on equality.
 */
export declare function isUnresolvedSessionId(id: string): boolean;
//# sourceMappingURL=session-identity.d.ts.map