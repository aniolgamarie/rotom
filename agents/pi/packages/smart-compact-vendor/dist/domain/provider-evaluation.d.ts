import type { CompactMetricsEntry, LLMCallMetric, ProviderRouteMetric, ProviderRouteStage } from "../types.ts";
export type ProviderScenario = "compact/conversational" | "compact/mixed" | "compact/tool-heavy" | "pressure/conversational" | "pressure/mixed" | "pressure/tool-heavy" | "critical/conversational" | "critical/mixed" | "critical/tool-heavy";
export interface ProviderEvaluationCell {
    stage: ProviderRouteStage;
    scenario: ProviderScenario;
    provider: string;
    model: string;
    runs: number;
    calls: number;
    successRate: number;
    avgLatencyMs: number;
    avgTokensPerCall: number;
    avgQuality: number | null;
    qualityCoverage: number;
    score: number;
    confidence: number;
    eligible: boolean;
}
export interface ProviderRouteRecommendation {
    stage: ProviderRouteStage;
    scenario: ProviderScenario;
    model: string | null;
    score: number;
    confidence: number;
    reason: string;
}
export interface ProviderEvaluationReport {
    generatedAt: string;
    entries: number;
    minSamples: number;
    advisoryOnly: true;
    cells: ProviderEvaluationCell[];
    recommendations: ProviderRouteRecommendation[];
}
export declare function providerStage(phase: LLMCallMetric["phase"]): ProviderRouteStage;
/** Collapse per-call telemetry into one route row per stage/provider/model. */
export declare function aggregateProviderRoutes(metrics: readonly LLMCallMetric[]): ProviderRouteMetric[];
export declare function providerScenario(entry: Pick<CompactMetricsEntry, "contextPercent" | "toolPercent">): ProviderScenario;
/**
 * Build an advisory scenario matrix from persisted real-run telemetry.
 * Legacy rows contribute reliability/latency. Quality is accepted only from
 * an explicitly stage-attributed route sample, never copied from the run's
 * final verifier score into every provider stage.
 */
export declare function evaluateProviderMetrics(entries: readonly CompactMetricsEntry[], options?: {
    minSamples?: number;
}): ProviderEvaluationReport;
export declare function formatProviderEvaluation(report: ProviderEvaluationReport): string;
//# sourceMappingURL=provider-evaluation.d.ts.map