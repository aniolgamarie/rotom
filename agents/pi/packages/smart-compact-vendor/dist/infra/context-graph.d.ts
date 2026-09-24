import type { CompactionState } from "../types.ts";
export type ContextMemoryKind = "goal" | "decision" | "constraint" | "error" | "loop" | "next-action" | "critical" | "topic" | "file" | "preference" | "warning" | "procedure" | "context";
export interface ContextGraphScope {
    projectId: string;
    sessionId: string;
    branchHeadId?: string;
    branchEntryIds?: readonly string[];
}
export interface ContextRecallOptions {
    limit?: number;
    sessionOnly?: boolean;
    kinds?: readonly ContextMemoryKind[];
}
export interface ContextRecallResult {
    id: string;
    kind: ContextMemoryKind;
    title: string;
    content: string;
    relatedPaths: string[];
    score: number;
    source: "compaction" | "manual";
    sameSession: boolean;
    sameBranch: boolean;
    updatedAt: number;
}
export interface SavedContextMemory {
    id: string;
    kind: Extract<ContextMemoryKind, "decision" | "constraint" | "preference" | "warning" | "procedure" | "context">;
    title: string;
    content: string;
    relatedPaths?: string[];
}
export interface ContextGraphStats {
    totalNodes: number;
    activeNodes: number;
    sessions: number;
    lastUpdatedAt: number | null;
}
/** Persist a scoped compaction state into the project context graph. Best-effort. */
export declare function indexCompactionState(projectId: string, state: CompactionState): boolean;
/**
 * Queue an apply-confirmed state and resolve only after the SQLite transaction
 * succeeds or fails. Duplicate updates coalesce per branch head; every caller
 * observes the result of the latest queued state.
 */
export declare function scheduleCompactionStateIndex(projectId: string, state: CompactionState): Promise<boolean>;
/** Test seam; production drains in a microtask. */
export declare function flushCompactionStateIndexes(): void;
/** Resolve or supersede an explicit memory by stable fact identity within one project. */
export declare function closeContextMemory(projectId: string, kind: SavedContextMemory["kind"], content: string, status: "resolved" | "superseded"): number;
/** Save one explicit, user-confirmed project memory. */
export declare function saveContextMemory(scope: ContextGraphScope, memory: Omit<SavedContextMemory, "id">): SavedContextMemory;
/** Weighted project recall: lexical seeds + one-hop file relationships + scope/recency boosts. */
export declare function recallContext(scope: ContextGraphScope, query: string, options?: ContextRecallOptions): ContextRecallResult[];
export declare function formatRecallResults(results: ContextRecallResult[], maxChars?: number): string;
export declare function getContextGraphStats(projectId: string): ContextGraphStats;
//# sourceMappingURL=context-graph.d.ts.map