/**
 * Step 7: verify and repair the synthesized summary.
 *
 * Every safe deterministic repair is applied regardless of scalar score. The
 * mode policy controls whether unresolved findings get an additional LLM call;
 * score remains diagnostic and never suppresses known, zero-cost repairs.
 */
import type { SynthesizedRc, VerifiedRc } from "../run-context.ts";
export declare function verifyAndPatch(rc: SynthesizedRc): Promise<VerifiedRc>;
//# sourceMappingURL=verify.d.ts.map