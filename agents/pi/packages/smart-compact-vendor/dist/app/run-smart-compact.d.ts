/**
 * Orchestrator: thread the typed run context through every stage in order.
 *
 * Each step is now a typed transition (see `app/run-context.ts`): the input
 * is the previous stage type, the output is the next. Skipping a step or
 * reordering them is a TypeScript error rather than a runtime crash.
 *
 * Responsibilities owned by this file:
 *
 *  - The try/finally that maintains `isRunning`.
 *  - The timeout `setTimeout` handle (set in prepare, cleared in finally).
 *  - The decision to bail out without side effects when the auto-trigger
 *    hard-timeout fires.
 *  - The post-success result screen + apply-compaction trigger.
 *
 * The function intentionally has no clever control flow: every cross-step
 * dependency is data on the stage type, every conditional is a boolean flag.
 */
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Cell, PendingCompaction, SmartCompactDetails } from "../types.ts";
import type { SessionRunLock } from "./session-run-lock.ts";
import type { Model, Api } from "@earendil-works/pi-ai";
import type { CompactionMode, CompressionProfile } from "../types.ts";
import type { PendingRef } from "./run-context.ts";
/**
 * Co-operative cancellation surface that the extension entry point can hand
 * back to itself to drive an *external* hard timeout.
 *
 * Setting `timedOut = true` and calling `abort()` from outside the pipeline
 * is the single source of truth for "give up on smart compaction and let Pi
 * run its native compact". The orchestrator notices the flag and:
 *
 *   - skips all remaining side effects (state persist, ctx.compact apply),
 *   - clears `pendingRef` in finally,
 *   - records a timeout metric instead of a success metric.
 */
export interface ExternalCancellation {
    timedOut: boolean;
    abort: () => void;
}
/** Options for runSmartCompact — avoids 10-parameter positional calls. */
export interface SmartCompactOptions {
    /**
     * The pipeline only touches members shared by `ExtensionContext` and
     * `ExtensionCommandContext` (ui, cwd, sessionManager, modelRegistry,
     * model, getContextUsage, compact). Using the narrower base type lets
     * the `session_before_compact` event handler pass its context in without
     * any cast, and makes the contract "what does the pipeline actually
     * need?" explicit at the type level.
     */
    ctx: ExtensionContext;
    /** Reuse a caller-loaded snapshot when preview and execution must agree. */
    config?: import("../types.ts").CompactConfig;
    summaryModel: Model<Api>;
    segModel: Model<Api>;
    /** Optional explicit verification/repair route; defaults to the summary model. */
    verifyModel?: Model<Api>;
    /** New execution preset. Omit to preserve the legacy profile mapping. */
    mode?: CompactionMode;
    profile?: CompressionProfile;
    verbose?: boolean;
    dryRun?: boolean;
    pendingRef: PendingRef;
    isRunning: Cell<boolean> | SessionRunLock;
    autoTriggered?: boolean;
    userNote?: string;
    focus?: string;
    maxLlmCalls?: number;
    maxLlmInputTokens?: number;
    skipCompact?: boolean;
    /** Explicit user command may bypass adaptive context-pressure tier gate. */
    force?: boolean;
    /** Native hook reason is overflow; EESV must not resend the rejected window to native summarization. */
    overflowRecovery?: boolean;
    /** Optional hard budget for native auto-trigger only. Manual/tool runs do not time out by default. */
    timeoutMs?: number;
    /** Host cancellation for tool/manual callers. Linked to the pipeline controller. */
    abortSignal?: AbortSignal;
    /**
     * If provided, populated with the run's cancellation handle before any
     * async work begins. The session_before_compact hook uses this to enforce
     * its own hard timeout in addition to the in-pipeline one (some providers
     * ignore AbortSignal entirely).
     */
    cancellationOut?: Cell<ExternalCancellation | null>;
    /** Lifecycle callback supplied by the extension's commit store. */
    onNativeApplyError?: (runId: string, error: Error) => boolean;
}
export type CompactOutcome = {
    kind: "staged";
    pending: PendingCompaction;
} | {
    kind: "apply-requested";
    pending: PendingCompaction;
} | {
    kind: "dry-run";
    details: SmartCompactDetails;
} | {
    kind: "skipped";
    reason: "model-unavailable" | "session-unavailable" | "already-running" | "window-not-viable" | "tier-selection-failed";
} | {
    kind: "cancelled";
    source: "user" | "timeout" | "host";
};
export declare function runSmartCompact(opts: SmartCompactOptions): Promise<CompactOutcome>;
//# sourceMappingURL=run-smart-compact.d.ts.map