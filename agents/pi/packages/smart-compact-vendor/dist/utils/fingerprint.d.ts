/**
 * Lightweight project fingerprint for cross-session context.
 * Stores basic project metadata to improve compaction accuracy.
 */
import type { StructuredExtraction } from "../types.ts";
export interface ProjectFingerprint {
    id: string;
    language: string;
    framework: string | null;
    keyDirectories: string[];
    knownFiles: string[];
    sessionCount: number;
    /** Hashed session identities tracked after distinct-session accounting shipped. */
    knownSessionIds?: string[];
    /** Historical count not attributable to a stored session identity. */
    legacySessionCount?: number;
    updatedAt: number;
}
/**
 * Find the git root for the current working directory.
 * Returns null if not in a git repo.
 *
 * Implementation is delegated to `infra/git.ts` which caches per cwd so that
 * the auto-trigger code path does not pay the execSync cost on every run.
 */
export declare function findGitRoot(cwd: string): string | null;
/**
 * Generate a stable project ID.
 *
 * Priority:
 *  1. cwd / git root — most reliable, survives discussion-only sessions
 *  2. Extraction file paths — absolute → deep ancestor, relative → dir fingerprint
 *  3. sessionId — last resort, never collides but never shares state either
 *
 * Using cwd/git-root as primary prevents cross-project fingerprint contamination
 * when a session has no file operations (review, discussion, debugging).
 */
export declare function deriveProjectIdFromCwd(cwd: string): string | null;
export declare function deriveProjectId(cwd: string, extraction: StructuredExtraction, sessionId?: string): string;
/**
 * Load project fingerprint from cache.
 */
export declare function loadProjectFingerprint(projectId: string): ProjectFingerprint | null;
/**
 * Save/update project fingerprint after compaction.
 *
 * Atomic temp+rename via writeJsonSync prevents a crash from leaving a
 * truncated JSON file behind. The next session would otherwise lose the
 * sessionCount counter or worse, throw on parse.
 */
export declare function saveProjectFingerprint(projectId: string, sessionId: string, extraction: StructuredExtraction): Promise<boolean>;
/**
 * Build a project context string for injection into prompts.
 */
export declare function buildProjectContext(fingerprint: ProjectFingerprint | null): string;
//# sourceMappingURL=fingerprint.d.ts.map