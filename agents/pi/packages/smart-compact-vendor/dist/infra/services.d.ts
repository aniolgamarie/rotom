/**
 * Service container — the dependency-injection backbone for one
 * `runSmartCompact` invocation.
 *
 * Background: the original codebase relied on module-level mutable singletons
 * for everything that needed cross-call state — the metrics array in
 * `cache.ts`, `_toolSupportCache` in `explore.ts`, the config cache in
 * `helpers.ts`, the calibration map in `tokens.ts`. Each singleton is
 * convenient on the happy path but breaks down once you run two pi sessions
 * simultaneously or write tests that need isolation:
 *
 *   - `_metrics` is shared across sessions, so one session's summary
 *     reset wipes another's in-flight call record.
 *   - `_toolSupportCache` carries TTL'd state into every test run; a flaky
 *     test that toggles tool support leaks into the next describe block.
 *   - Hot path metrics writes contend on the same array indices.
 *
 * The `SmartCompactServices` bag gives every run its own metrics, budget,
 * scrubber, and prompt namespace. Production runs deliberately share only
 * bounded provider/model capability and token-calibration knowledge; those
 * caches contain no conversation/session data and would otherwise be useless
 * when recreated for each compaction. Tests keep isolated defaults.
 *
 * Services that are stateless or already inject through their own seam
 * (`LlmClient`, `Clock`, file system helpers in `infra/fs.ts`) are exposed via
 * the container for convenience but never mutated through it.
 */
import type { Clock } from "./clock.ts";
import type { LlmClient } from "./llm-client.ts";
import type { CompactConfig, LLMCallMetric } from "../types.ts";
import { TokenCalibrationStore } from "../utils/tokens.ts";
import { SecretScrubber } from "../domain/scrub.ts";
/**
 * Bounded in-memory cache for "does this provider/model support tools?".
 * Production services share it across runs so explicit unsupported-capability
 * responses avoid repeated probes; ordinary createServices() calls stay
 * isolated for tests. Entries expire after one hour.
 */
export declare class ToolSupportCache {
    private readonly ttlMs;
    private readonly maxEntries;
    private readonly entries;
    constructor(ttlMs?: number, maxEntries?: number);
    /** Returns the cached value if fresh, or undefined to force a probe. */
    get(key: string, now: number): boolean | undefined;
    set(key: string, value: boolean, now: number): void;
    clear(): void;
    /** Snapshot for debug logging; safe to call from anywhere. */
    size(): number;
}
/**
 * Per-run metrics sink.
 *
 * Caps at `maxEntries` and trims from the front so a runaway test or a long
 * batch synthesis doesn't grow unbounded. `summary()` is O(n) but n is bounded
 * by `maxEntries`, so it's safe to call from the result screen.
 */
export declare class MetricsSink {
    private readonly buf;
    private readonly maxEntries;
    constructor(maxEntries?: number);
    record(metric: LLMCallMetric): void;
    snapshot(): LLMCallMetric[];
    clear(): void;
    summary(): {
        totalCalls: number;
        totalInput: number;
        totalOutput: number;
        totalCacheHit: number;
        totalCacheWrite: number;
        avgLatency: number;
        cacheHitRate: number;
    };
}
/**
 * Per-run extraction cache stats.
 *
 * Tracks hits vs misses on `loadCachedExtraction`. Surfaced into the metrics
 * dashboard so we can tune the prefix-match tolerance over time.
 */
export declare class BudgetExceededError extends Error {
    readonly reason: "calls" | "latency" | "tokens";
    constructor(reason: "calls" | "latency" | "tokens");
}
/** Atomic per-run reservation guard; safe for concurrent batch wave launches. */
export declare class BudgetGuard {
    private maxCalls;
    private readonly maxLatencyMs;
    private readonly clock;
    private maxInputTokens;
    private maxOutputTokens;
    private calls;
    private inputTokens;
    private outputTokens;
    private reservedOutputTokens;
    private startedAt;
    private lastReason;
    constructor(maxCalls?: number, maxLatencyMs?: number, clock?: Clock, maxInputTokens?: number, maxOutputTokens?: number);
    reserveCall(estimatedInputTokens?: number, expectedOutputTokens?: number): number;
    reconcileInput(estimated: number, actual: number): void;
    reconcileOutput(reserved: number, actual: number): void;
    /** Failed streams may have emitted unreported output; charge the reservation. */
    commitFailedOutput(reserved: number): void;
    /** Compatibility path for callers that do not reserve output. */
    recordOutput(actual: number): void;
    setLimits(maxCalls: number, maxInputTokens: number, maxOutputTokens?: number): void;
    callCount(): number;
    remainingCalls(): number;
    inputTokenCount(): number;
    outputTokenCount(): number;
    remainingOutputTokens(): number;
    reason(): "calls" | "latency" | "tokens" | null;
}
export declare class ExtractionCacheStats {
    private hits;
    private misses;
    recordHit(): void;
    recordMiss(): void;
    snapshot(): {
        hits: number;
        misses: number;
        hitRate: number;
    };
    clear(): void;
}
/** The full per-run service bag. */
export interface SmartCompactServices {
    clock: Clock;
    llm: LlmClient;
    toolSupport: ToolSupportCache;
    metrics: MetricsSink;
    extractionCacheStats: ExtractionCacheStats;
    tokenCalibration: TokenCalibrationStore;
    budget: BudgetGuard;
    scrubber: SecretScrubber;
    /** Config snapshot used to select generic reasoning levels for each phase. */
    thinkingLevels: Pick<CompactConfig, "summaryThinkingLevel" | "segmentationThinkingLevel">;
    /** 0 derives the ChatGPT Codex watchdog from each call's requested output cap. */
    codexWatchdogMs: number;
    /** Per-run prompt-cache namespace for providers that support prompt caching. */
    compactSessionId: string;
}
export declare function makeCompactSessionId(): string;
export declare function createServices(overrides?: Partial<SmartCompactServices>): SmartCompactServices;
/** Production run services: per-run metrics/budgets, shared bounded provider knowledge. */
export declare function createProductionServices(overrides?: Partial<SmartCompactServices>): SmartCompactServices;
export declare function getDefaultServices(): SmartCompactServices;
/** Swap the default container; tests use this to inject a clock/llm. */
export declare function setDefaultServices(services: SmartCompactServices): void;
/** Reset the legacy/test default container. Production runs do not call this. */
export declare function resetDefaultServices(): void;
//# sourceMappingURL=services.d.ts.map