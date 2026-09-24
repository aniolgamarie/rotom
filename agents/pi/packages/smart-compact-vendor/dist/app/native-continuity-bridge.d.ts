export interface NativeContinuityScope {
    projectId: string;
    sessionId: string;
    branchHeadId: string;
}
export interface NativeContinuityBridge {
    stage(scope: NativeContinuityScope, text: string): void;
    take(scope: NativeContinuityScope): string | null;
    clear(scope?: NativeContinuityScope): void;
    size(): number;
}
export declare function createNativeContinuityBridge(opts?: {
    ttlMs?: number;
    maxEntries?: number;
    now?: () => number;
    dir?: string;
}): NativeContinuityBridge;
//# sourceMappingURL=native-continuity-bridge.d.ts.map