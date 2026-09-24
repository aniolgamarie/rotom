/**
 * Filesystem primitives with atomic-write and lock semantics.
 *
 * Why this module exists:
 *
 *  - Several disk writes (extraction cache, project fingerprint, compaction
 *    state, metrics dashboard) used `fs.writeFileSync` directly. A process
 *    crash mid-write leaves the JSON half-truncated, and the next load throws
 *    on `JSON.parse`. We now write to `<file>.tmp.<pid>.<rand>` then rename,
 *    so readers either see the previous payload or the new one — never both.
 *
 *  - The append-only metrics log was written with `appendFileSync`. Multiple
 *    pi sessions writing concurrently could interleave bytes mid-line and
 *    produce a single corrupted JSON record. We hold a short-lived file lock
 *    while opening and appending, so contiguous lines stay intact.
 *
 *  - Several pieces of code re-checked `existsSync` then `mkdirSync`. The
 *    `ensureDir` helper deduplicates that pattern.
 *
 * Sync vs async:
 *  - The extension runs inside the pi event loop. The hot path through
 *    `runSmartCompact` already does many sync FS calls; turning every helper
 *    into async would balloon the diff. We expose both shapes:
 *    `atomicWriteFileSync` for the existing call sites (kept simple) and
 *    `atomicWriteFile` for new async-friendly callers (background metrics).
 *
 * Lock acquisition is fail-closed: callers never continue an append/trim
 * without ownership. Locks are never stolen on elapsed time because a live,
 * slow owner must not overlap a successor.
 */
/** Ensure a private directory exists and normalize an existing target. */
export declare function ensureDir(dir: string): void;
/**
 * Atomically write a file: write to a sibling temp file, then rename. This
 * prevents partial readers and preserves the previous file on process failure;
 * it does not claim power-loss durability because it deliberately avoids fsync
 * on latency-sensitive cache/backup writes.
 */
export declare function atomicWriteFileSync(target: string, data: string | Uint8Array): void;
export declare function atomicWriteFile(target: string, data: string | Uint8Array): Promise<void>;
/** Immediate lock attempt for synchronous best-effort paths; never parks JS. */
export declare function acquireLockSync(target: string): () => void;
/** Cooperative multi-process lock for durable read-modify-write operations. */
export declare function acquireLock(target: string): Promise<() => void>;
/**
 * Append one complete line while enforcing an optional tail-retention cap.
 *
 * Append and trim share the same advisory lock. This matters because O_APPEND
 * only serializes writes to one inode; it does not protect a concurrent
 * temp-file rename from replacing an append that landed after the trim read.
 * Retention therefore happens synchronously, but only when the cap is crossed.
 */
export declare function appendLineLocked(target: string, line: string, maxBytes?: number): void;
/** Async append/retention variant for event-loop-sensitive telemetry paths. */
export declare function appendLineLockedAsync(target: string, line: string, maxBytes?: number): Promise<void>;
/** Read the newest valid JSONL records without loading an entire bounded log. */
export declare function readJsonlTail<T>(target: string, limit: number, maxBytes?: number): T[];
/** Keep only complete trailing lines that fit within `maxBytes`. */
export declare function trimFileTailLocked(target: string, maxBytes: number): Promise<void>;
export declare function readJsonSync<T>(target: string): T | null;
export declare function writeJsonSync(target: string, value: unknown, pretty?: boolean): void;
//# sourceMappingURL=fs.d.ts.map