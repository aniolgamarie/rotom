import { webModels } from "@agentcfg/pi-runtime/web-model";

const THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);

export type SummaryThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

interface SummaryModelScopeContext {
	cwd: string;
	isProjectTrusted(): boolean;
}

export interface ModelLike {
	provider: string;
	id: string;
}

export interface ModelRegistryLike<T extends ModelLike = ModelLike> {
	find(provider: string, id: string): T | undefined;
	getAvailable(): readonly T[];
}

// 只暴露 agentcfg 选中的模型，不读取全局或项目 settings，不猜测路由别名。
export function findModelWithProviderRouting<T extends ModelLike>(
  _registry: ModelRegistryLike<T>, provider: string, id: string,
): T | undefined {
  return webModels().find(model => model.provider === provider && model.id === id) as T | undefined;
}
export function loadEnabledModelPatterns(_ctx: SummaryModelScopeContext): string[] {
  return webModels().map(model => `${model.provider}/${model.id}`);
}

export function summaryModelValue(model: ModelLike): string {
	return `${model.provider}/${model.id}`;
}

export function splitThinkingSuffix(value: string): { value: string; thinkingLevel?: SummaryThinkingLevel } {
	const index = value.lastIndexOf(":");
	if (index < 0) return { value };
	const suffix = value.slice(index + 1);
	return THINKING_LEVELS.has(suffix)
		? { value: value.slice(0, index), thinkingLevel: suffix as SummaryThinkingLevel }
		: { value };
}

function stripThinkingSuffix(pattern: string): string {
 return splitThinkingSuffix(pattern).value;
}

function globToRegExp(pattern: string): RegExp {
	let source = "^";
	for (const char of pattern) {
		if (char === "*") {
			source += ".*";
		} else if (char === "?") {
			source += ".";
		} else {
			source += char.replace(/[|\\{}()[\]^$+?.]/g, "\\$&");
		}
	}
	return new RegExp(`${source}$`, "i");
}

export function modelMatchesEnabledPatterns(model: ModelLike, patterns: string[] | null): boolean {
	if (patterns === null) return true;
	const value = summaryModelValue(model).toLowerCase();
	const id = model.id.toLowerCase();
	for (const rawPattern of patterns) {
		const pattern = stripThinkingSuffix(rawPattern.trim()).toLowerCase();
		if (!pattern) continue;
		if (pattern.includes("*") || pattern.includes("?")) {
			const regex = globToRegExp(pattern);
			if (regex.test(value) || regex.test(id)) return true;
			continue;
		}
		if (pattern === value || pattern === id) return true;
	}
	return false;
}
