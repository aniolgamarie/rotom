import type { PendingCompaction } from "../types.ts";
export type CommitDiscardReason = "expired" | "evicted" | "aborted" | "shutdown" | "apply-error";
export interface CompactionCommitStore {
    stage(pending: PendingCompaction): void;
    take(runId: string, sessionId: string): PendingCompaction | null;
    discard(runId: string, reason: CommitDiscardReason): PendingCompaction | null;
    clearSession(sessionId: string, reason?: CommitDiscardReason): PendingCompaction[];
    size(): number;
}
/**
 * Holds summaries only between session_before_compact and session_compact.
 * Nothing durable is written until `take()` confirms both run and session.
 */
export declare function createCompactionCommitStore(options?: {
    ttlMs?: number;
    maxEntries?: number;
    onDiscard?: (pending: PendingCompaction, reason: CommitDiscardReason) => void;
}): CompactionCommitStore;
//# sourceMappingURL=compaction-commit-store.d.ts.map