import type { Cell } from "../types.ts";
export interface SessionRunLock extends Cell<boolean> {
    acquire(sessionId: string): boolean;
    release(sessionId: string): void;
    isSessionActive(sessionId: string): boolean;
    isRunning(sessionId: string): boolean;
    activeCount(): number;
    size(): number;
}
/**
 * Same-session serialization plus a filesystem-backed process-global
 * semaphore. A crashed process leaves a lease that is reclaimed only when its
 * PID is no longer alive (or an unreadable lease exceeds the stale ceiling).
 */
export declare function createSessionRunLock(maxConcurrent?: number, options?: {
    leaseDir?: string | null;
    staleMs?: number;
}): SessionRunLock;
export declare function acquireRunLock(lock: Cell<boolean> | SessionRunLock, sessionId: string): boolean;
export declare function releaseRunLock(lock: Cell<boolean> | SessionRunLock, sessionId: string): void;
//# sourceMappingURL=session-run-lock.d.ts.map