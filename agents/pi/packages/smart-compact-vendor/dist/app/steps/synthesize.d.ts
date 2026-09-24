/**
 * Step 6: synthesize the conversation summary.
 *
 * Two paths converge here:
 *
 *   Single-pass: short conversations fit in one LLM call. The full convText
 *   gets sent with the deterministic extraction context and we get a single
 *   markdown summary back. We always check the result starts with "##" so a
 *   model that refuses or returns junk falls back to the heuristic assembler
 *   without polluting the conversation history.
 *
 *   EESV: long conversations are explored, chunked, summarized in parallel
 *   batches, then assembled. The Explore phase is gated by `shouldExplore` so
 *   trivially small sessions don't pay 3-8 extra LLM calls.
 *
 * Concurrency is provider-derived (`providerCaps.concurrencyLimit`). Wave
 * scheduling matters because some providers (Kimi, Minimax) throttle hard
 * once you exceed 2-3 concurrent calls.
 */
import type { ExtractedRc, SynthesizedRc } from "../run-context.ts";
export declare function summarizeConversation(rc: ExtractedRc): Promise<SynthesizedRc>;
//# sourceMappingURL=synthesize.d.ts.map