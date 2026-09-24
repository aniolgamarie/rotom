/**
 * Step 4: select compaction tier.
 *
 * Stage: `RecoveredRc` → `TieredRc | null`.
 *
 * Returns `null` for tier="none" so the orchestrator can short-circuit. Only
 * "light" and "full" tiers reach later stages, which is enforced statically
 * by the `ActiveTier` type on `TieredRc.tier`.
 */
import type { RecoveredRc, TieredRc } from "../run-context.ts";
export declare function selectTier(rc: RecoveredRc): TieredRc | null;
//# sourceMappingURL=tier.d.ts.map