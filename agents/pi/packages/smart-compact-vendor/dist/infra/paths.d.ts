/**
 * Centralized filesystem path resolution.
 *
 * Every disk-bound subsystem in the extension (extraction cache, metrics log,
 * project fingerprints, compaction state, damage reports, backups, session
 * logs) used to compute its own `path.join(process.env.HOME …)` on every call.
 * That made it impossible to:
 *
 *  - test path layout deterministically (HOME changes per test, but module
 *    state captured an old HOME),
 *  - swap roots in worktree / CI scenarios,
 *  - reason about file ownership when adding atomic writes and locking.
 *
 * This module is intentionally **stateless**: every function reads
 * `process.env.HOME` at call time. That way tests can override HOME in
 * `beforeEach` and the next call sees the new root.
 */
/**
 * `HOME` wins so tests can override the root. Windows' `USERPROFILE` is the
 * next choice; GUI launches that strip both variables fall back to
 * `os.homedir()`, matching how the pi host resolves `~/.pi/agent`.
 */
export declare function home(): string;
/** Root pi agent directory (`~/.pi/agent`). */
export declare function piAgentDir(): string;
/** Pi-coding-agent session log directory. */
export declare function sessionsDir(): string;
/** Pi-coding-agent settings file. */
export declare function settingsFile(): string;
/** Default backup directory. */
export declare function defaultBackupDir(): string;
/** Metrics JSONL log. */
export declare function metricsLogFile(): string;
/** Cross-process Smart Compact semaphore/session lease directory. */
export declare function runLocksDir(): string;
/** One-shot, branch-scoped native-compaction continuity handoffs. */
export declare function nativeContinuityDir(): string;
/** Project-scoped persistent context graph (SQLite + FTS5). */
export declare function contextGraphFile(): string;
/** Damage reports JSONL log. */
export declare function damageReportsFile(): string;
/** Extraction cache file for a given session. */
export declare function extractionCacheFile(sessionId: string): string;
/** Project fingerprint file for a given project id. */
export declare function projectFingerprintFile(projectId: string): string;
/** Legacy project-wide compaction state file (v1). */
export declare function compactionStateFile(projectId: string): string;
/** Pre-v8.1 session-only path, retained solely for one-time branch migration. */
export declare function legacyScopedCompactionStateFile(projectId: string, sessionId: string): string;
/** Immutable branch snapshot; descendants find it through their ancestry IDs. */
export declare function scopedCompactionStateFile(projectId: string, sessionId: string, branchHeadId: string): string;
/** Remediation hints file — files to re-preserve after a damage event. */
export declare function remediationHintsFile(projectId: string): string;
/** HTML metrics dashboard file. */
export declare function metricsDashboardFile(): string;
//# sourceMappingURL=paths.d.ts.map