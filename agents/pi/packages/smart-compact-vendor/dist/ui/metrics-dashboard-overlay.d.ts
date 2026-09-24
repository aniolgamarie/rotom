import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { CompactMetricsEntry } from "../types.ts";
import { type DashboardInsights } from "./dashboard-insights.ts";
type DashboardAction = "html" | null;
export declare function showMetricsDashboardUI(ctx: ExtensionCommandContext, opts: {
    entries: CompactMetricsEntry[];
    currentSessionId?: string;
    report: string;
    insights?: DashboardInsights;
}): Promise<DashboardAction>;
export {};
//# sourceMappingURL=metrics-dashboard-overlay.d.ts.map