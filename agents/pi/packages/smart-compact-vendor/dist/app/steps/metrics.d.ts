/**
 * Step 10: record metrics for the run.
 *
 * Two paths:
 *
 *   - `recordSuccessMetrics(rc: StatedRc, status)` runs after a full pipeline
 *     completion. Every field on the metric record is statically known.
 *
 *   - `recordFailureMetrics(rc, err, fields)` runs from the catch block in
 *     the orchestrator and may execute before the pipeline ever populated
 *     stage data. The `fields` bag carries whatever the orchestrator managed
 *     to collect before the throw; missing values fall through to undefined.
 *
 * Metrics writes are intentionally append-only and idempotent — they target
 * the JSONL log and never throw past the cache.ts boundary.
 */
import type { RcBase, StatedRc } from "../run-context.ts";
import type { CompactionMode, MetricsSnapshot } from "../../types.ts";
export declare function buildSuccessMetrics(rc: StatedRc, status: "success" | "dry-run" | "cancelled"): MetricsSnapshot;
export declare function recordSuccessMetrics(rc: StatedRc, status: "success" | "dry-run" | "cancelled"): Promise<void>;
/**
 * Partial summary that the orchestrator accumulates as steps complete. The
 * failure path uses whatever is present at the moment of the throw.
 */
export interface FailureSummaryFields {
    sessionId?: string;
    tier?: string;
    contextPercent?: number;
    toolPercent?: number;
    totalTokens?: number;
    methodForMetrics?: string;
    profile: string;
    mode?: CompactionMode;
}
export declare function recordFailureMetrics(rc: RcBase | StatedRc, err: unknown, fields: FailureSummaryFields): Promise<void>;
//# sourceMappingURL=metrics.d.ts.map