import type { CompactMetricsEntry, TelemetryFailureKind } from "../types.ts";
export interface DamageTelemetryEntry {
    ts?: string;
    /** Originating compaction run; required for trustworthy quality/damage joins. */
    runId?: string;
    version?: string;
    releaseChannel?: "stable" | "canary";
    observationSource?: "online-window" | "next-compaction";
    damageScore?: number;
}
export interface TelemetryWindowStats {
    runs: number;
    appliedRuns: number;
    successRate: number;
    avgQuality: number | null;
    qualityCoverage: number;
    p95LatencyMs: number;
    avgTokens: number;
    fallbackRate: number;
    damageRate: number;
    damageCoverage: number;
}
export interface CanaryTrigger {
    metric: "failure-rate" | "quality" | "latency" | "tokens" | "fallback" | "damage";
    baseline: number;
    canary: number;
    threshold: string;
}
export interface CanaryAssessment {
    version: string;
    decision: "promote" | "hold" | "rollback";
    dataConfidence: number;
    baseline: TelemetryWindowStats;
    canary: TelemetryWindowStats;
    triggers: CanaryTrigger[];
    reasons: string[];
}
export interface PrivacySafeTelemetryAggregate {
    version: string;
    channel: "stable" | "canary";
    provider: string;
    model: string;
    runs: number;
    successes: number;
    avgQuality: number | null;
    avgLatencyMs: number;
    inputTokens: number;
    outputTokens: number;
}
export interface PrivacySafeTelemetry {
    generatedAt: string;
    totalRuns: number;
    aggregates: PrivacySafeTelemetryAggregate[];
    failures: Partial<Record<TelemetryFailureKind, number>>;
    canary: CanaryAssessment;
    privacy: "aggregate-only; no session ids, project ids, prompts, summaries, paths, or error text";
}
/** Stable, content-free failure taxonomy for aggregate telemetry. */
export declare function classifyTelemetryFailure(error: unknown, timedOut?: boolean): TelemetryFailureKind;
export declare function assessCanary(entries: readonly CompactMetricsEntry[], damageEntries: readonly DamageTelemetryEntry[], options: {
    version: string;
    minCanaryRuns?: number;
    baselineRuns?: number;
}): CanaryAssessment;
export declare const TELEMETRY_FAILURE_KINDS: ReadonlySet<TelemetryFailureKind>;
export declare function isTelemetryFailureKind(value: unknown): value is TelemetryFailureKind;
export declare function buildPrivacySafeTelemetry(entries: readonly CompactMetricsEntry[], damageEntries: readonly DamageTelemetryEntry[], options: {
    version: string;
    minCanaryRuns?: number;
}): PrivacySafeTelemetry;
export declare function formatPrivacySafeTelemetry(report: PrivacySafeTelemetry): string;
//# sourceMappingURL=telemetry.d.ts.map