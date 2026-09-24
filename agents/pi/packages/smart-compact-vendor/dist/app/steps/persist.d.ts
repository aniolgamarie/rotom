/**
 * Step 9: apply compaction and persist durable state.
 *
 * Lifecycle invariants:
 *
 *  - `pendingRef` is set immediately so `session_before_compact` can consume
 *    it. We MUST clear it on failure (P1 #4 in the audit) — the previous
 *    implementation left a stale summary alive for up to 5 minutes after a
 *    `ctx.compact()` error.
 *
 *  - Project fingerprint and compaction state are persisted **after** the
 *    host emits the matching `session_compact` entry. `ctx.compact.onComplete`
 *    is UI feedback only and is not a durable-commit authority. If we wrote state
 *    eagerly and the compact failed, the next run would believe a successful
 *    compaction had happened — corrupting damage detection and the
 *    cross-compaction delta. This addresses P1 #5 in the audit.
 *
 *  - For manual / tool runs we run damage detection against the existing
 *    branch's previous compaction as a best-effort signal.
 */
import type { RunContext } from "../run-context.ts";
import type { MetricsSnapshot, PendingCompaction } from "../../types.ts";
import type { StatedRc } from "../run-context.ts";
/**
 * Persist durable state for an applied payload.
 *
 * `session_before_compact` only stages a candidate; Pi may still abort. The
 * extension calls this function exactly once from the correlated
 * `session_compact` event after the compaction entry exists. Best-effort:
 * persistence failures are logged without corrupting the host session.
 */
export declare function persistAppliedState(pending: PendingCompaction): Promise<string[]>;
export declare function commitAppliedCompaction(pending: PendingCompaction): Promise<string[]>;
/** Run post-compaction damage detection. Best-effort — never throws. */
export declare function runDamageDetection(rc: RunContext): void;
/**
 * Stash the prepared compaction in pendingRef and trigger the native compact
 * if appropriate. Returns the pending summary so callers can decide whether
 * the run should keep running side effects (it does until the timeout/cleanup
 * step decides otherwise).
 */
export declare function stagePendingCompaction(rc: RunContext, metricsSnapshot?: MetricsSnapshot): PendingCompaction;
/**
 * Trigger Pi's native compact in non-auto/non-tool runs. Failure clears the
 * pendingRef so the next compact event cannot grab a stale summary (audit
 * P1 #4).
 *
 * `session_compact` owns success metrics and durable commit. onError removes
 * the correlated staged candidate; direct/test callers retain a safe metrics
 * fallback when no lifecycle handler is installed.
 */
export declare function applyCompaction(rc: StatedRc): void;
//# sourceMappingURL=persist.d.ts.map