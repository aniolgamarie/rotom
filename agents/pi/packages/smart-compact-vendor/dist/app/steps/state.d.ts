/**
 * Step 8: build the post-summary state, open loops, and delta against last run.
 *
 * Stage: `VerifiedRc` → `StatedRc`.
 *
 * The structured state is what later sessions reason against — `loadCompactionState`
 * reads it to compute the delta, `damage.ts` reads it to detect post-compaction
 * regression. Persistence itself happens later in the persist step so that we
 * never write stale state when the native compact ultimately fails to apply.
 */
import type { VerifiedRc, StatedRc } from "../run-context.ts";
export declare function buildState(rc: VerifiedRc): StatedRc;
//# sourceMappingURL=state.d.ts.map