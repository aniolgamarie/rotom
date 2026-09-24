import { webModel, webComplete } from "@agentcfg/pi-runtime/web-model";
import { complete, type Api, type Model, type ProviderHeaders } from "@earendil-works/pi-ai/compat";
import type { SummaryGenerationContext } from "./summary-review.ts";
import { findModelWithProviderRouting, loadEnabledModelPatterns, modelMatchesEnabledPatterns } from "./summary-model-scope.ts";

export async function rewriteSearchQuery(
	query: string,
	ctx: SummaryGenerationContext,
	signal: AbortSignal,
): Promise<string> {
	const model = webModel("rewrite", undefined, ctx.model);
	const completeFn = webComplete;
	const response = await completeFn(
		model,
		{
			messages: [{
				role: "user",
				content: [{ type: "text", text: `Rewrite this web search query to get better, more specific results. Add relevant year qualifiers, precise technical terms, and specificity. Return ONLY the improved query text, nothing else.\n\nQuery: ${query}` }],
				timestamp: Date.now(),
			}],
		},
		{ signal },
	);
	if (response.stopReason === "aborted") throw new Error("Aborted");
	const contentParts = Array.isArray(response.content) ? response.content : [];
	const text = contentParts
		.map((part: unknown) => part && typeof part === "object" && (part as { type?: unknown }).type === "text" && typeof (part as { text?: unknown }).text === "string" ? (part as { text: string }).text : "")
		.join("")
		.trim();
	if (!text) throw new Error("Rewrite returned empty response");
	return text;
}
