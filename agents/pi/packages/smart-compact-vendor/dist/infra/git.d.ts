/**
 * Git root resolver with a bounded, expiring cwd cache.
 *
 * Positive entries avoid repeated synchronous `git rev-parse` calls during
 * compaction. Negative entries use a short TTL because a directory may become
 * a repository while the extension process is still running.
 */
export declare function findGitRoot(cwd: string, now?: number): string | null;
/** Test helper — clears the cache between runs. */
export declare function _resetGitRootCacheForTests(): void;
//# sourceMappingURL=git.d.ts.map