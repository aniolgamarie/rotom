import { type CanaryAssessment, type DamageTelemetryEntry } from "../domain/telemetry.ts";
import type { CompactMetricsEntry, ProviderRouteStage, TelemetryFailureKind } from "../types.ts";
export interface DashboardDataConfidence {
    score: number;
    label: "high" | "medium" | "low";
    targetMet: boolean;
    sampleScore: number;
    schemaScore: number;
    qualityScore: number;
    completenessScore: number;
    freshnessScore: number;
    guidance: string[];
}
export interface DashboardQualityInsight {
    /** Actual outcome health; separate from telemetry completeness confidence. */
    healthScore: number;
    healthLabel: "healthy" | "degraded" | "critical";
    targetMet: boolean;
    measuredRuns: number;
    missingRuns: number;
    average: number | null;
    median: number | null;
    minimum: number | null;
    excellent: number;
    passing: number;
    low: number;
    averageInitial: number | null;
    averageRepairGain: number | null;
    deterministicPatchedRuns: number;
    llmPatchedRuns: number;
    qualityFloorRuns: number;
    remainingGaps: number;
}
export interface DashboardProviderInsight {
    stage: ProviderRouteStage;
    provider: string;
    model: string;
    runs: number;
    calls: number;
    reliability: number;
    avgQuality: number | null;
    qualityCoverage: number;
    avgLatencyMs: number;
    avgTokensPerCall: number;
}
export interface DashboardInsights {
    confidence: DashboardDataConfidence;
    quality: DashboardQualityInsight;
    providers: DashboardProviderInsight[];
    canary: CanaryAssessment;
    failures: Partial<Record<TelemetryFailureKind, number>>;
}
export declare function calculateDashboardDataConfidence(entries: readonly CompactMetricsEntry[], now?: number): DashboardDataConfidence;
export declare function formatDashboardQuality(insights: DashboardInsights): string[];
export declare function formatDashboardProviders(insights: DashboardInsights): string[];
export declare function formatDashboardCanary(insights: DashboardInsights): string[];
export declare function buildDashboardInsights(entries: readonly CompactMetricsEntry[], damageEntries?: readonly DamageTelemetryEntry[], options?: {
    version?: string;
    minCanaryRuns?: number;
    now?: number;
}): DashboardInsights;
//# sourceMappingURL=dashboard-insights.d.ts.map