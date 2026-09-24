/**
 * Step 1: prepare a run — load config, provider caps, budgets, and
 * cancellation. Provider credentials are intentionally resolved later by
 * `resolveStageAuth()` immediately before each stage's first network call.
 *
 * Stage transition: `RcBase` → `PreparedRc`.
 */
import type { RcBase, PreparedRc } from "../run-context.ts";
export declare function prepareRun(rc: RcBase): Promise<PreparedRc>;
//# sourceMappingURL=prepare.d.ts.map