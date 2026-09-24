import type { CompactMetricsEntry } from "../types.ts";
import type { DamageTelemetryEntry } from "../domain/telemetry.ts";
import { type DashboardInsights } from "./dashboard-insights.ts";
export declare function buildLocalDashboardInsights(entries?: CompactMetricsEntry[], damageEntries?: DamageTelemetryEntry[]): DashboardInsights;
export declare function buildMetricsReport(entries?: CompactMetricsEntry[], damageEntries?: DamageTelemetryEntry[], prebuiltInsights?: DashboardInsights): string;
export declare function writeMetricsDashboard(entries?: CompactMetricsEntry[], damageEntries?: DamageTelemetryEntry[]): string | null;
//# sourceMappingURL=metrics-report.d.ts.map