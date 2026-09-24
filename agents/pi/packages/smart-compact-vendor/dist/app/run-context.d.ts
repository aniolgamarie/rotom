/**
 * Per-run pipeline context as a typed state machine.
 *
 * The previous incarnation of `RunContext` was a single fat interface where
 * every later-phase field was marked optional. That kept the type system
 * quiet but had two real costs:
 *
 *   1. **Cast pollution.** `makeContext` initialized half the fields with
 *      `undefined as unknown as RunContext["config"]` because the type
 *      claimed they would be set. Every step then re-read them with `!`,
 *      silently relying on call ordering. A future refactor that moved one
 *      step would compile cleanly and crash at runtime.
 *
 *   2. **No phase guarantees.** `applyCompaction` reading `rc.details!` had
 *      no compile-time proof that `buildState` had actually run.
 *
 * We replace that with a stage chain. Each step accepts the previous stage
 * type and returns the next, so:
 *
 *   - `prepareRun(base)` → `PreparedRc`
 *   - `resolveCompactionWindow(prepared)` → `WindowedRc | null`
 *   - …
 *   - `buildState(verified)` → `StatedRc`
 *   - `applyCompaction(stated)` (cannot be invoked before `buildState`)
 *
 * Implementation note: mutation is preserved. Each step mutates the input
 * object and returns it cast to the next stage. The `_brand` field on each
 * extension is the only thing that distinguishes stages structurally — it is
 * never read at runtime. This lets us avoid copying ~30 fields per step
 * while still getting compile-time stage tracking.
 *
 * The final `RunContext = StatedRc` alias keeps backwards-compatible imports
 * working for the `applyCompaction` / metrics paths that ran post-`buildState`.
 */
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Model, Api, ProviderHeaders } from "@earendil-works/pi-ai";
import type { CompressionProfile, CompactionMode, EffectiveCompactionMode, LlmMessage, StructuredExtraction, ExplorationReport, ChunkSummary, SessionMessageEntry, PipelinePhaseTiming, CompactConfig, ProfileConfig, ProviderCapabilities, SmartCompactDetails, CompactionState, ContinuityScope, OpenLoop, Cell, PreparedConversationBackup } from "../types.ts";
import type { PendingSlot } from "./pending-slot.ts";
import type { PruningResult } from "../utils/pruning.ts";
import type { CompactionTier } from "../utils/helpers.ts";
import type { TokenEstimator } from "../utils/tokens.ts";
import type { SmartCompactServices } from "../infra/services.ts";
import type { SessionRunLock } from "./session-run-lock.ts";
export type Notifier = (msg: string, type?: "info" | "success" | "warning" | "error") => void;
export interface CancellationToken {
    controller: AbortController;
    signal: AbortSignal;
    /** Set when the auto-trigger hard timeout fires. */
    timedOut: boolean;
    /** Active setTimeout handle. Cleared in finally so we never leak timers. */
    timeoutId: ReturnType<typeof setTimeout> | null;
}
/**
 * Backward-compat alias. The pipeline previously juggled a raw
 * `{ value, createdAt }` ref-cell; the encapsulated `PendingSlot` API
 * supersedes it. We keep the name in the run-context so existing wiring
 * stays readable while every mutation goes through the slot's invariants.
 */
export type PendingRef = PendingSlot;
export interface RunFlags {
    verbose: boolean;
    dryRun: boolean;
    autoTriggered: boolean;
    skipCompact: boolean;
    force: boolean;
    /** Pi is retrying a provider turn that exceeded the active model window. */
    overflowRecovery?: boolean;
}
export interface ResolvedAuth {
    apiKey: string;
    headers?: ProviderHeaders;
}
export interface RcBase {
    /** Unique id for correlating staged and applied compaction lifecycle events. */
    runId: string;
    ctx: ExtensionContext;
    /** Optional caller snapshot; prepareRun loads config only when absent. */
    config?: CompactConfig;
    notify: Notifier;
    vlog: (msg: string) => void;
    services: SmartCompactServices;
    cancellation: CancellationToken;
    pendingRef: PendingRef;
    isRunning: Cell<boolean> | SessionRunLock;
    /** Removes a staged commit candidate when native apply fails. */
    onNativeApplyError?: (runId: string, error: Error) => boolean;
    flags: RunFlags;
    userNote?: string;
    focus?: string;
    maxLlmCalls?: number;
    maxLlmInputTokens?: number;
    timeoutMs: number;
    phaseTimings: PipelinePhaseTiming[];
    pipelineStart: number;
    phaseStart: number;
    summaryModel: Model<Api>;
    segModel: Model<Api>;
    verifyModel: Model<Api>;
    modelLabel: string;
    requestedMode: CompactionMode;
    mode: EffectiveCompactionMode;
    profile: CompressionProfile;
}
export interface PreparedExt {
    /** Discriminator field; never read at runtime. */
    readonly _prepared: true;
    config: CompactConfig;
    profileCfg: ProfileConfig;
    providerCaps: ProviderCapabilities;
    estimator: TokenEstimator;
    adapted: boolean;
    summaryAuth?: ResolvedAuth;
    /** Optional routes resolve credentials only when the stage actually runs. */
    segAuth?: ResolvedAuth;
    verifyAuth?: ResolvedAuth;
}
export type PreparedRc = RcBase & PreparedExt;
export type RelaxedSoftBoundary = "recent-user-turn" | "anchor" | "topical";
export type CompactionPlanReason = "viable" | "no-eligible-prefix" | "unsafe-tool-boundary" | "retention-target-exceeded" | "mode-target-not-met" | "insufficient-projected-saving";
export interface CompactionWindowPlan {
    keepFrom: number;
    compactTokens: number;
    retainedTokens: number;
    projectedAfterTokens: number;
    projectedSavedTokens: number;
    projectedYield: number;
    fixedContextTokens: number;
    retentionTargetTokens: number;
    summaryBudgetTokens: number;
    /** Locally estimated upper bound for synthesis plus deterministic post-processing. */
    finalSummaryAllowanceTokens?: number;
    targetAfterTokens: number;
    hardBoundaryAdjusted: boolean;
    viable: boolean;
    reason: CompactionPlanReason;
    relaxedSoftBoundaries: RelaxedSoftBoundary[];
}
export interface WindowedExt extends PreparedExt {
    readonly _windowed: true;
    sessionId: string;
    branch: unknown[];
    msgs: SessionMessageEntry[];
    totalTokens: number;
    contextPercent: number;
    toolPercent: number;
    keepFrom: number;
    toCompact: SessionMessageEntry[];
    firstKeptId: string;
    /** Estimated tokens replaced by the summary, normalized to Pi's measured context. */
    compactTokens: number;
    /** Estimated retained-tail tokens, normalized to Pi's measured context. */
    accTokens: number;
    /** Content-free plan used to gate execution and, later, preview it in the UI. */
    compactionPlan: CompactionWindowPlan;
}
export type WindowedRc = RcBase & WindowedExt;
export interface RecoveredExt extends WindowedExt {
    readonly _recovered: true;
    llmMessages: LlmMessage[];
    /** Entry id aligned 1:1 with `llmMessages` after convertToLlm filtering. */
    llmEntryIds: string[];
}
export type RecoveredRc = RcBase & RecoveredExt;
export type ActiveTier = Exclude<CompactionTier, "none">;
export interface TieredExt extends RecoveredExt {
    readonly _tiered: true;
    tier: ActiveTier;
}
export type TieredRc = RcBase & TieredExt;
export interface ExtractedExt extends TieredExt {
    readonly _extracted: true;
    pruning: PruningResult;
    currentEntryIds: string[];
    currentKeptEntryIds: string[];
    extraction: StructuredExtraction;
    extractionCacheMissReason?: string;
    prevContext: string;
    projectCtx: string;
    projectId: string;
    continuityScope: ContinuityScope;
    previousState: CompactionState | null;
    /**
     * Serialized pruned conversation text. Computed once in `extractWithCache`
     * and reused by `summarizeConversation` so we don't `serializeConversation`
     * the same 5000-message array twice on the hot path. `convTokens` is the
     * cached `estimateTokens(convText)` value.
     */
    convText: string;
    convTokens: number;
    backupPath: string | null;
    /** Scrubbed exact payload staged in memory and written only after apply confirmation. */
    preparedBackup?: PreparedConversationBackup;
}
export type ExtractedRc = RcBase & ExtractedExt;
export interface SynthesizedExt extends ExtractedExt {
    readonly _synthesized: true;
    finalSummary: string;
    method: "eesv" | "single-pass" | "heuristic";
    methodForMetrics: string;
    generationFallbacks: string[];
    llmCalls: number;
    summaries: ChunkSummary[];
    explorationReport: ExplorationReport | null;
    explorationRounds: number;
    chunkCount: number;
}
export type SynthesizedRc = RcBase & SynthesizedExt;
export interface VerifiedExt extends SynthesizedExt {
    readonly _verified: true;
    verificationScore: number;
    verificationGaps: string[];
    verificationProvenance: import("../types.ts").VerificationProvenance;
    verified: boolean;
}
export type VerifiedRc = RcBase & VerifiedExt;
export interface StatedExt extends VerifiedExt {
    readonly _stated: true;
    openLoops: OpenLoop[];
    compactionState: CompactionState;
    details: SmartCompactDetails;
    tokensSaved: number;
}
export type StatedRc = RcBase & StatedExt;
/**
 * Backwards-compatible alias.
 *
 * Modules that don't care about pipeline ordering (e.g. `applyCompaction` in
 * `persist.ts`, which only runs after `buildState`) can still take a
 * `RunContext`. New code should prefer the explicit stage types.
 */
export type RunContext = StatedRc;
/** Record an already-measured phase and advance the phase boundary. */
export declare function markMeasuredPhase(rc: RcBase, phase: PipelinePhaseTiming["phase"], startMs: number, endMs?: number): void;
/** Mark the boundary between two pipeline phases for the metrics log. */
export declare function markPhase(rc: RcBase, phase: PipelinePhaseTiming["phase"]): void;
/** Runtime-checked, in-place transition between adjacent pipeline stages. */
export declare function advance<TIn extends RcBase, TOut extends TIn>(rc: TIn, stage: keyof TOut): TOut;
//# sourceMappingURL=run-context.d.ts.map