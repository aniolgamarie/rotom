/**
 * LLM client seam.
 *
 * Why we have a seam at all:
 *
 *  - pi-ai's completers are the only runtime entry points into a model.
 *    Importing them directly from utility modules tied even the metrics test
 *    path to the peer dependency, which made `bun test` fail when the peer
 *    was not installed.
 *
 *  - Test fakes need to assert which `phase` was used, control failures, and
 *    return synthetic usage tokens for calibration tests.
 *
 *  - Future provider fallback work (per `implement-llm-provider-fallback`)
 *    becomes a single-file change instead of a cross-module refactor.
 *
 * The interface is intentionally narrow: a single `complete()` method matching
 * the pi-ai shape, plus the same options object existing callers already pass.
 *
 * The default implementation keeps `complete()` for existing calls and uses
 * `completeSimple()` when generic reasoning is explicitly configured.
 * `setLlmClient` is exposed for tests and wrapping/fallback clients. Both
 * completers are resolved below through the host's compat alias.
 */
import type { Model, Api, AssistantMessage, Context, SimpleStreamOptions } from "@earendil-works/pi-ai";
export type LlmCompleteOptions = SimpleStreamOptions & {
    codexWatchdogMs?: number;
};
export interface LlmClient {
    complete(model: Model<Api>, body: Context, opts: LlmCompleteOptions): Promise<AssistantMessage>;
}
export declare function isChatGptCodex(model: Model<Api>): boolean;
/** ChatGPT rejects wire token caps; OpenAI-compatible custom Codex endpoints may accept them. */
export declare function withCodexWireLimit(model: Model<Api>, opts: LlmCompleteOptions): LlmCompleteOptions;
export declare function resolveCodexWatchdogMs(maxTokens: number | undefined, configuredMs?: number): number;
export declare function resolveProviderWatchdogMs(provider: string | undefined, maxTokens: number | undefined, configuredMs?: number): number;
/** @internal Test seam for the transport deadline used by every provider. */
export declare function withProviderDeadline(opts: LlmCompleteOptions, invoke: (bounded: LlmCompleteOptions) => Promise<AssistantMessage>, provider?: string): Promise<AssistantMessage>;
/** Raw client — map generic reasoning only when explicitly configured. */
export declare const rawLlmClient: LlmClient;
/** Production default: never replay an expensive compaction request automatically. */
export declare const defaultLlmClient: LlmClient;
export declare function getLlmClient(): LlmClient;
export declare function setLlmClient(client: LlmClient): void;
/** Restore the production client. Tests should always pair `setLlmClient` with this. */
export declare function resetLlmClient(): void;
//# sourceMappingURL=llm-client.d.ts.map