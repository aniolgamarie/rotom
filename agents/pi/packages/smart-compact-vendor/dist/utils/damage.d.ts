/**
 * Post-compaction regression signal detection.
 * Monitors agent behavior after compaction to detect quality issues.
 */
import type { LlmMessage, SmartCompactDetails } from "../types.ts";
export interface RegressionSignal {
    type: "re-read" | "re-question" | "contradiction" | "user-complaint";
    severity: "low" | "medium" | "high";
    detail: string;
}
export interface DamageReport {
    signals: RegressionSignal[];
    damageScore: number;
    summary: string;
    /** Distinct file paths the agent re-read after compaction — fed forward as
     *  remediation hints so the next compaction preserves them. */
    reReadFiles: string[];
}
/**
 * Detect regression signals in messages AFTER compaction.
 * Called with the post-compaction messages (typically 5-20 messages).
 *
 * @param postMessages Messages after compaction was applied
 * @param details The compaction details (contains the files/decisions that were compacted)
 */
export declare function detectDamage(postMessages: LlmMessage[], details: SmartCompactDetails): DamageReport;
/**
 * Save a damage report to the metrics log for future analysis.
 *
 * The append is fire-and-forget async: this runs from the message_end
 * handler, and the locked append path must never block the main thread on a
 * contended lock. Failures are logged, not thrown.
 */
export declare function logDamageReport(sessionId: string, report: DamageReport, details: SmartCompactDetails, projectId?: string, observationSource?: "online-window" | "next-compaction"): void;
export interface OnlineDamageObservation {
    projectId: string;
    details: SmartCompactDetails;
    report: DamageReport;
    complete: boolean;
}
/** Session-keyed monitor activated only after Pi confirms `session_compact`. */
export declare class OnlineDamageMonitor {
    private readonly maxMessages;
    private readonly active;
    constructor(maxMessages?: number);
    activate(sessionId: string, projectId: string, details: SmartCompactDetails): void;
    observe(sessionId: string, message: LlmMessage): OnlineDamageObservation | null;
    clear(sessionId: string): void;
    size(): number;
}
export declare function readRecentDamageScores(projectId: string, limit?: number): number[];
/**
 * Persist the files the agent re-read after a compaction so the NEXT
 * compaction treats them as must-preserve (remediation). Overwrites with the
 * latest set; a TTL bounds how long stale hints linger.
 */
export declare function writeRemediationHints(projectId: string, files: string[]): void;
/**
 * Read remediation hints for a project. Returns [] when absent, malformed,
 * or older than the TTL.
 */
export declare function readRemediationHints(projectId: string): string[];
//# sourceMappingURL=damage.d.ts.map