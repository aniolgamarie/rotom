/**
 * Step 5: deterministic extraction with incremental cache.
 *
 * Stage: `TieredRc` → `ExtractedRc`.
 *
 * Pruning + extraction are paired here because:
 *
 *  1. The extraction indexes (topic ranges, error message offsets, decisions)
 *     live in the pruned message domain. Caching the extraction is only safe
 *     when the pruned *prefix* of the next run matches the previous one.
 *  2. Without the prefix guard, an incremental delta could be merged on top
 *     of a base whose pruning result drifted (e.g. a new duplicate read
 *     evicted an old cached read), producing index offsets that point at the
 *     wrong messages.
 *
 * `extractionCacheMissReason` captures *why* the cache could not be used so
 * the metrics dashboard can show the hit-rate alongside the failure mode.
 */
import type { TieredRc, ExtractedRc } from "../run-context.ts";
export declare function extractWithCache(rc: TieredRc): ExtractedRc;
//# sourceMappingURL=extract.d.ts.map