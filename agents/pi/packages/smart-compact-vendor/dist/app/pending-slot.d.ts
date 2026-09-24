/** Session-scoped pending compaction store with TTL and bounded memory. */
import type { PendingCompaction } from "../types.ts";
import { type SessionIdentityContext } from "../infra/session-identity.ts";
export type ConsumeResult = {
    kind: "ok";
    pending: PendingCompaction;
} | {
    kind: "empty";
} | {
    kind: "expired";
    ageMs: number;
} | {
    kind: "mismatch";
    expected: string;
    actual: string;
};
export interface PendingSlot {
    set(pending: PendingCompaction): void;
    consume(ctx: SessionIdentityContext): ConsumeResult;
    clear(sessionId?: string): void;
    isPresent(sessionId?: string): boolean;
    peek(sessionId?: string): Readonly<PendingCompaction> | null;
    size(): number;
}
export interface PendingSlotOptions {
    ttlMs: number;
    now?: () => number;
    maxEntries?: number;
}
export declare function createPendingSlot(opts: PendingSlotOptions): PendingSlot;
//# sourceMappingURL=pending-slot.d.ts.map