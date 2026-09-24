import type { ChunkSummary, ExplorationReport } from "../types.ts";
import type { ExtractedRc } from "../app/run-context.ts";
export interface CachedSynthesis {
    finalSummary: string;
    method: "eesv" | "single-pass" | "heuristic";
    summaries: ChunkSummary[];
    explorationReport: ExplorationReport | null;
    explorationRounds: number;
    chunkCount: number;
}
export declare function synthesisCacheKey(rc: ExtractedRc): string;
export declare function getCachedSynthesis(key: string, now?: number): CachedSynthesis | null;
export declare function setCachedSynthesis(key: string, value: CachedSynthesis, now?: number): void;
export declare function batchCacheKey(value: unknown): string;
export declare function getCachedBatch(key: string, now?: number): ChunkSummary[] | null;
export declare function setCachedBatch(key: string, value: ChunkSummary[], now?: number): void;
export declare function clearSynthesisCache(): void;
export declare function synthesisCacheSize(): number;
//# sourceMappingURL=synthesis-cache.d.ts.map