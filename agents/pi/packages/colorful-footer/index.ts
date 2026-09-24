/**
 * Colorful Footer — 多彩 statusbar 扩展
 *
 * 纯彩色文字风格，无背景色块，适配暗色/亮色终端。
 * 关键指标加粗突出，分隔符优雅简洁。
 *
 * 配置：agentcfg agent_options.ui.footer
 *   {
 *     "maxLines": 4,
 *     "adaptive": true,
 *     "separator": "│",
 *     "colors": {
 *       "model": "#d787af",
 *       "path": "#00afaf",
 *       "git": "#5faf5f"
 *     },
 *     "icons": {
 *       "folder": "●",
 *       "branch": "⑂"
 *     }
 *   }
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { basename } from "node:path";

// ── 常量 ─────────────────────────────────────────────────────────────

const BAR_FULL = "█";
const BAR_EMPTY = "░";
const BOLD = "\x1b[1m";
const RESET = "\x1b[0m";
const YOLO_STATE_KEY = Symbol.for("session-yolo:state");
const YOLO_INVALIDATE_KEY = Symbol.for("session-yolo:invalidate");

// ── 类型 ─────────────────────────────────────────────────────────────

type UsageSummary = {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
	valid: boolean;
	branchLength: number;
};

type BranchEntry = {
	type?: string;
	message?: AssistantMessage;
};

type RenderData = {
	now: number;
	curTok: number;
	ctxWin: number;
	pct: number;
	bar: string;
	usage: UsageSummary;
	cacheTot: number;
	cacheRate: number;
	dur: string;
	modelId: string;
	provider: string;
	fullModel: string;
	thinking: string;
	branch: string;
	cwd: string;
	turnSpeed: number;
	agentActive: boolean;
};

type FooterData = {
	onBranchChange(callback: () => void): void;
	getGitBranch(): string | undefined;
};

type YoloState = {
	mode?: "cwd" | "global" | "off";
	cwd?: string | null;
  effective?: boolean;
  owner?: string;
};

// ── 图标系统 ─────────────────────────────────────────────────────────

interface IconSet {
	model: string;
	folder: string;
	branch: string;
	git: string;
	tokens: string;
	context: string;
	cost: string;
	time: string;
	cache: string;
	input: string;
	output: string;
}

const NERD_ICONS: IconSet = {
	model: "\uEC19", // nf-md-chip
	folder: "\uF115", // nf-fa-folder_open
	branch: "\uF126", // nf-fa-code_fork
	git: "\uF1D3", // nf-fa-git
	tokens: "\uE26B", // nf-seti-html
	context: "\uE70F", // nf-dev-database
	cost: "\uF155", // nf-fa-dollar
	time: "\uF017", // nf-fa-clock_o
	cache: "\uF1C0", // nf-fa-database
	input: "\uF090", // nf-fa-sign_in
	output: "\uF08B", // nf-fa-sign_out
};

const ASCII_ICONS: IconSet = {
	model: "◆",
	folder: "●",
	branch: "⑂",
	git: "⑂",
	tokens: "",
	context: "◫",
	cost: "$",
	time: "◷",
	cache: "",
	input: "↑",
	output: "↓",
};

function hasNerdFonts(): boolean {
	if (process.env.POWERLINE_NERD_FONTS === "1") return true;
	if (process.env.POWERLINE_NERD_FONTS === "0") return false;
	if (process.env.GHOSTTY_RESOURCES_DIR) return true;
	const term = (process.env.TERM_PROGRAM || "").toLowerCase();
	const nerdTerms = ["iterm", "wezterm", "kitty", "ghostty", "alacritty"];
	return nerdTerms.some((t) => term.includes(t));
}

// ── 颜色配置 ─────────────────────────────────────────────────────────

interface ColorConfig {
	model?: string;
	path?: string;
	git?: string;
	tokens?: string;
	context?: string;
	cost?: string;
	time?: string;
	cache?: string;
	input?: string;
	output?: string;
}

interface Config {
	maxLines: number;
	adaptive: boolean;
	colors?: ColorConfig;
	icons?: Partial<IconSet>;
	separator?: string;
}

const DEFAULT_CONFIG: Config = {
	maxLines: 4,
	adaptive: true,
	separator: "│",
};

const DEFAULT_COLORS: Required<ColorConfig> = {
	model: "accent",
	path: "muted",
	git: "success",
	tokens: "muted",
	context: "success",
	cost: "text",
	time: "dim",
	cache: "success",
	input: "muted",
	output: "muted",
};

// ── 配置加载 ─────────────────────────────────────────────────────────

let configCache: Config | null = null;
let configCacheTime = 0;
const CACHE_TTL = 5000;

function loadConfig(): Config {
	const now = Date.now();
	if (configCache && now - configCacheTime < CACHE_TTL) {
		return configCache;
	}

  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime) throw new Error("AGENTCFG_RUNTIME_REQUIRED");
  const configured: Config = { ...DEFAULT_CONFIG, ...runtime.manifest.options.ui?.footer };
  configCache = configured;
  configCacheTime = now;
  return configured;
}

function getIcons(): IconSet {
	const baseIcons = hasNerdFonts() ? NERD_ICONS : ASCII_ICONS;
	const config = loadConfig();
	return {
		...baseIcons,
		...config.icons,
	};
}

function getColor(name: keyof ColorConfig): string {
	const config = loadConfig();
	return config.colors?.[name] ?? DEFAULT_COLORS[name];
}

function getSep(): string {
	const config = loadConfig();
	return `\x1b[2m ${config.separator ?? "│"} \x1b[0m`;
}

// ── 状态 ─────────────────────────────────────────────────────────────

let cachedUsage: UsageSummary = {
	input: 0,
	output: 0,
	cacheRead: 0,
	cacheWrite: 0,
	cost: 0,
	valid: false,
	branchLength: -1,
};

let sessionStartTime = Date.now();
let turnStartTime = Date.now();
let turnStartTokens = 0;
let agentActive = false;
let turnSpeed = 0;

// ── 节流和缓存 ───────────────────────────────────────────────────────

const FOOTER_THROTTLE_MS = 1000; // 1 次/秒 (降低渲染频率减少闪烁)
const GIT_THROTTLE_MS = 2000; // 0.5 次/秒 (git分支几乎不变)

let lastRenderTime = 0;
let lastGitUpdateTime = 0;
let cachedRenderData: RenderData | null = null;
let cachedRenderLines: string[] = [];
let cachedWidth = 0;
let lastRenderedContent = "";

// ── 权限弹窗冻结 ─────────────────────────────────────────────────────

interface PermissionRequest {
	requestId?: string;
	surface: string;
	value: string;
	agentName?: string;
	timestamp: number;
}

const permissionQueue: PermissionRequest[] = [];
let permissionUiActive = false;
let frozenRenderData: RenderData | null = null;

// ── UI Calm 模式 ─────────────────────────────────────────────────────

let uiCalmMode = true; // 默认开启
let workingIndicatorHidden = false;

// ── 工具函数 ─────────────────────────────────────────────────────────

function fmt(n: number): string {
	if (n < 1000) return String(n);
	if (n < 1000000) return (n / 1000).toFixed(1) + "k";
	return (n / 1000000).toFixed(1) + "M";
}

function emptyUsage(branchLength = -1): UsageSummary {
	return {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
		cost: 0,
		valid: false,
		branchLength,
	};
}

function fgHex(hex: string, text: string): string {
	const h = hex.replace("#", "");
	return `\x1b[38;2;${parseInt(h.slice(0, 2), 16)};${parseInt(h.slice(2, 4), 16)};${parseInt(h.slice(4, 6), 16)}m${text}\x1b[0m`;
}

// 判断是否为 hex 颜色（支持 3/6/8 位）
function isHexColor(color: string): boolean {
	return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(color);
}

// 安全的前景色渲染：hex 颜色直接用 ANSI，theme 颜色走 theme.fg，失败则降级
function safeFg(theme: any, color: string, text: string): string {
	if (isHexColor(color)) {
		return fgHex(color, text);
	}
	try {
		return theme.fg(color, text);
	} catch {
		if (color.startsWith("#")) {
			try {
				return fgHex(color, text);
			} catch {
				/* ignore */
			}
		}
		return text;
	}
}

// 加粗 + 前景色
function safeFgBold(theme: any, color: string, text: string): string {
	return `${BOLD}${safeFg(theme, color, text)}${RESET}`;
}

// 段落渲染：纯彩色文字，无背景
function segment(theme: any, color: string, text: string): string {
	return safeFg(theme, color, text);
}

// 加粗段落：关键指标用
function segmentBold(theme: any, color: string, text: string): string {
	return safeFgBold(theme, color, text);
}

function speedColor(speed: number, active: boolean): string {
	if (!active) return "dim";
	if (speed < 100) return "warning";
	if (speed <= 3000) return "success";
	if (speed <= 8000) return "accent";
	return "error";
}

function contextColor(pct: number): string {
	if (pct > 85) return "error";
	if (pct > 60) return "warning";
	return getColor("context");
}

function getYoloIndicator(theme: any): string | null {
	const state = (globalThis as any)[YOLO_STATE_KEY] as YoloState | undefined;
  if (!state || state.owner !== "agentcfg" || state.mode === "off") return null;
  if (!state.effective) return segmentBold(theme, "dim", "permission: constrained");
	if (state.mode === "cwd") return segmentBold(theme, "warning", "prompt: cwd");
	if (state.mode === "global") return segmentBold(theme, "error", "prompt: session");
	return null;
}

function invalidateRenderCache(): void {
	cachedRenderData = null;
	cachedRenderLines = [];
	lastRenderTime = 0;
	lastRenderedContent = "";
}

// ── 数据收集 ─────────────────────────────────────────────────────────

function getUsage(ctx: any): UsageSummary {
	const branch = ctx.sessionManager.getBranch() as BranchEntry[];
	if (cachedUsage.valid && cachedUsage.branchLength === branch.length) {
		return cachedUsage;
	}

	const nextUsage = emptyUsage(branch.length);
	nextUsage.valid = true;

	branch.forEach((e) => {
		if (e.type !== "message" || !e.message || e.message.role !== "assistant")
			return;
		const m = e.message as AssistantMessage;
		if (!m.usage) return;

		nextUsage.input += m.usage.input || 0;
		nextUsage.output += m.usage.output || 0;
		nextUsage.cacheRead += m.usage.cacheRead || 0;
		nextUsage.cacheWrite += m.usage.cacheWrite || 0;

		const costRecord = m.usage.cost as Record<string, unknown> | undefined;
		const apiCost =
			typeof costRecord?.total === "number" ? costRecord.total : 0;
		nextUsage.cost += apiCost;
	});

	cachedUsage = nextUsage;
	return cachedUsage;
}

function buildRenderData(
	ctx: any,
	pi: ExtensionAPI,
	footerData: FooterData,
): RenderData {
	const now = Date.now();

	// 节流检查：如果距离上次渲染不足 FOOTER_THROTTLE_MS，返回缓存数据
	if (cachedRenderData && now - lastRenderTime < FOOTER_THROTTLE_MS) {
		return cachedRenderData;
	}

	const contextUsage = ctx.getContextUsage?.();
	const curTok = contextUsage?.tokens || 0;
	const ctxWin = ctx.model?.contextWindow || 200000;
	const pct = ctxWin > 0 ? Math.min((curTok / ctxWin) * 100, 100) : 0;

	if (agentActive) {
		const turnElapsed = (now - turnStartTime) / 1000;
		if (turnElapsed > 0.5) {
			const delta = Math.max(0, curTok - turnStartTokens);
			turnSpeed = Math.round(delta / turnElapsed);
		}
	}

	const usage = getUsage(ctx);
	const cacheTot = usage.cacheRead + usage.cacheWrite;
	const cacheRate =
		usage.input + cacheTot > 0
			? Math.round((usage.cacheRead / (usage.input + cacheTot)) * 100)
			: 0;
	const sec = Math.floor((now - sessionStartTime) / 1000);
	const dur = Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
	const modelId = ctx.model?.id || "no-model";
	const provider = ctx.model?.provider || "";
	const filled = Math.round(pct / 10);

	// Git 分支节流：只在 GIT_THROTTLE_MS 间隔后更新
	let branch = cachedRenderData?.branch || "-";
	if (now - lastGitUpdateTime >= GIT_THROTTLE_MS) {
		branch = footerData.getGitBranch() || "-";
		lastGitUpdateTime = now;
	}

	const renderData: RenderData = {
		now,
		curTok,
		ctxWin,
		pct,
		bar: BAR_FULL.repeat(filled) + BAR_EMPTY.repeat(10 - filled),
		usage,
		cacheTot,
		cacheRate,
		dur,
		modelId,
		provider,
		fullModel: provider ? provider + "/" + modelId : modelId,
		thinking: pi.getThinkingLevel() || "off",
		branch,
		cwd: basename(process.cwd()),
		turnSpeed,
		agentActive,
	};

	// 缓存渲染数据
	cachedRenderData = renderData;
	lastRenderTime = now;

	return renderData;
}

// ── 渲染 ─────────────────────────────────────────────────────────────

function renderPrimaryLine(data: RenderData, theme: any): string {
	const icons = getIcons();
	const sep = getSep();
	const statColor = data.agentActive ? "accent" : "success";
	const statStr = segmentBold(
		theme,
		statColor,
		data.agentActive ? "▸ run" : "◦ idle",
	);
	const tokInStr = segment(
		theme,
		getColor("input"),
		icons.input + " " + fmt(data.usage.input),
	);
	const tokOutStr = segment(
		theme,
		getColor("output"),
		icons.output + " " + fmt(data.usage.output),
	);
	const costStr = segment(
		theme,
		getColor("cost"),
		icons.cost + data.usage.cost.toFixed(4),
	);
	const cacheStr =
		data.cacheTot > 0
			? segment(
					theme,
					getColor("cache"),
					icons.cache +
						" " +
						fmt(data.usage.cacheRead) +
						" " +
						data.cacheRate +
						"%",
				)
			: "";
	return [statStr, tokInStr, tokOutStr, costStr, cacheStr]
		.filter(Boolean)
		.join(sep);
}

function renderSessionLine(data: RenderData, theme: any): string {
	const icons = getIcons();
	const sep = getSep();
	const tiColors: Record<string, string> = {
		off: "dim",
		minimal: "thinkingMinimal",
		low: "thinkingLow",
		medium: "thinkingMedium",
		high: "thinkingHigh",
		xhigh: "thinkingXhigh",
	};
	const spStr = segment(
		theme,
		speedColor(data.turnSpeed, data.agentActive),
		icons.model + " " + fmt(data.turnSpeed) + "/s",
	);
	const durStr = segment(theme, getColor("time"), icons.time + " " + data.dur);
	const branchStr = segment(
		theme,
		getColor("git"),
		icons.branch + " " + data.branch,
	);
	const cwdStr = segment(
		theme,
		getColor("path"),
		icons.folder + " " + data.cwd,
	);
	const modelStr = segment(
		theme,
		getColor("model"),
		icons.model + " " + data.fullModel,
	);
	const tiStr = segment(
		theme,
		tiColors[data.thinking] || "dim",
		"think:" + data.thinking,
	);
	const yoloIndicator = getYoloIndicator(theme);

	return [spStr, durStr, branchStr, cwdStr, modelStr, tiStr, yoloIndicator]
		.filter(Boolean)
		.join(sep);
}

function renderContextLine(data: RenderData, theme: any): string {
	const icons = getIcons();
	const sep = getSep();
	const pctNum = Math.round(data.pct);
	const pctCol = contextColor(data.pct);

	// 渐变色进度条：绿 → 黄 → 红
	const filled = Math.round(data.pct / 10);
	const barChars: string[] = [];
	for (let i = 0; i < 10; i++) {
		if (i < filled) {
			const segPct = (i + 1) * 10;
			const segCol = contextColor(segPct);
			barChars.push(safeFg(theme, segCol, BAR_FULL));
		} else {
			barChars.push(safeFg(theme, "dim", BAR_EMPTY));
		}
	}
	const barStr = barChars.join("");

	return [
		segment(theme, "dim", icons.context + " Ctx"),
		segmentBold(theme, pctCol, pctNum + "%"),
		barStr,
		segment(theme, "dim", fmt(data.curTok) + "/" + fmt(data.ctxWin)),
	].join(sep);
}

function renderCompactLines(data: RenderData, theme: any): string[] {
	const icons = getIcons();
	const sep = getSep();
	const status = segmentBold(
		theme,
		data.agentActive ? "accent" : "success",
		data.agentActive ? "▸ run" : "◦ idle",
	);
	const pctCol = contextColor(data.pct);
	const ctxStr = segment(
		theme,
		pctCol,
		icons.context + " " + Math.round(data.pct) + "%",
	);
	const speedStr = segment(
		theme,
		speedColor(data.turnSpeed, data.agentActive),
		icons.model + " " + fmt(data.turnSpeed) + "/s",
	);
	const branchStr = segment(
		theme,
		getColor("git"),
		icons.branch + " " + data.branch,
	);
	return [[status, ctxStr, speedStr, branchStr].join(sep)];
}

function renderNormalLines(data: RenderData, theme: any): string[] {
	const icons = getIcons();
	const sep = getSep();
	const pctCol = contextColor(data.pct);
	const status = segmentBold(
		theme,
		data.agentActive ? "accent" : "success",
		data.agentActive ? "▸ run" : "◦ idle",
	);
	const ctxStr = segment(
		theme,
		pctCol,
		icons.context + " " + Math.round(data.pct) + "%",
	);
	const speedStr = segment(
		theme,
		speedColor(data.turnSpeed, data.agentActive),
		icons.model + " " + fmt(data.turnSpeed) + "/s",
	);
	const tokenStr = segment(
		theme,
		"dim",
		icons.input +
			" " +
			fmt(data.usage.input) +
			" " +
			icons.output +
			" " +
			fmt(data.usage.output),
	);
	const costStr = segment(
		theme,
		getColor("cost"),
		icons.cost + data.usage.cost.toFixed(4),
	);
	const sessionBits = [
		segment(theme, getColor("time"), icons.time + " " + data.dur),
		segment(theme, getColor("git"), icons.branch + " " + data.branch),
		segment(theme, getColor("path"), icons.folder + " " + data.cwd),
		segment(theme, getColor("model"), icons.model + " " + data.fullModel),
		segment(theme, "dim", "think:" + data.thinking),
		getYoloIndicator(theme),
	].filter(Boolean);

	return [
		[status, ctxStr, speedStr, tokenStr, costStr].join(sep),
		sessionBits.join(sep),
	];
}

function renderDetailedLines(data: RenderData, theme: any): string[] {
	return [
		renderPrimaryLine(data, theme),
		renderSessionLine(data, theme),
		renderContextLine(data, theme),
	];
}

function getDisplayMode(
	width: number,
	adaptive: boolean,
): "compact" | "normal" | "detailed" {
	if (!adaptive) return "detailed";
	if (width < 70) return "compact";
	if (width < 120) return "normal";
	return "detailed";
}

function renderLines(
	data: RenderData,
	theme: any,
	width: number,
	config: Config,
): string[] {
	const mode = getDisplayMode(width, config.adaptive);
	const lines =
		mode === "compact"
			? renderCompactLines(data, theme)
			: mode === "normal"
				? renderNormalLines(data, theme)
				: renderDetailedLines(data, theme);

	return lines
		.slice(0, config.maxLines)
		.map((line) => truncateToWidth(line, width));
}

// ── 扩展入口 ─────────────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	const config = loadConfig();
	const invalidateYoloFooter = () => invalidateRenderCache();
	(globalThis as any)[YOLO_INVALIDATE_KEY] = invalidateYoloFooter;

	pi.on("session_start", (_event: unknown, ctx: any) => {
		sessionStartTime = Date.now();
		turnStartTime = Date.now();
		turnStartTokens = 0;
		agentActive = false;
		turnSpeed = 0;
		cachedUsage = emptyUsage();

		// 检查是否有 UI 可用
		if (!ctx.hasUI) {
			return;
		}

		try {
			ctx.ui.setFooter((tui: any, theme: any, footerData: FooterData) => {
				footerData.onBranchChange(() => {
					// 分支变化时重置 Git 缓存，但不立即触发渲染
					lastGitUpdateTime = 0;
				});

					return {
						dispose: () => {},
						invalidate: invalidateRenderCache,
					render: (w: number): string[] => {
						try {
							// 权限弹窗期间：返回冻结的数据或空行
							if (permissionUiActive) {
								return cachedRenderLines.length > 0 ? cachedRenderLines : [""];
							}

							// UI Calm 模式：使用静态 working indicator
							if (uiCalmMode && agentActive && !workingIndicatorHidden) {
								// 保持当前显示，不更新 working 状态
							}

							// 宽度变化时强制重新渲染
							if (w !== cachedWidth) {
								cachedWidth = w;
								cachedRenderLines = [];
								lastRenderedContent = "";
							}

							const data = buildRenderData(ctx, pi, footerData);
							const newLines = renderLines(data, theme, w, config);

							// 检查内容是否实际变化
							const newContent = newLines.join("\n");
							if (newContent === lastRenderedContent) {
								// 内容未变化，返回缓存
								return cachedRenderLines;
							}

							// 内容变化，更新缓存
							cachedRenderLines = newLines;
							lastRenderedContent = newContent;

							return newLines;
						} catch (renderError) {
							// 渲染错误时返回空行，避免崩溃
							console.error("FOOTER_RENDER_FAILED");
							return ["[colorful-footer error]"];
						}
					},
				};
			});
		} catch (setError) {
			console.error("FOOTER_SETUP_FAILED");
		}
	});

	pi.on("turn_start", (_event: unknown, ctx: any) => {
		agentActive = true;
		turnStartTime = Date.now();
		const usage = ctx.getContextUsage?.();
		turnStartTokens = usage?.tokens || 0;
		turnSpeed = 0;
	});

	pi.on("turn_end", (_event: unknown, _ctx: any) => {
		agentActive = false;
		cachedUsage.valid = false;
	});

	pi.on("session_shutdown", () => {
		for (const stop of permissionListeners) stop();
		if ((globalThis as any)[YOLO_INVALIDATE_KEY] === invalidateYoloFooter) {
			delete (globalThis as any)[YOLO_INVALIDATE_KEY];
		}
	});

	// ── 权限弹窗事件监听 ─────────────────────────────────────────────

	const permissionListeners = [pi.events.on("permissions:ui_prompt", (event: any) => {
		// 权限 UI 开始显示，冻结 Footer
		permissionUiActive = true;

		// 保存当前渲染数据
		if (cachedRenderData) {
			frozenRenderData = { ...cachedRenderData };
		}

		// 将请求加入队列
		const request: PermissionRequest = {
			requestId: event.requestId,
			surface: event.surface || "unknown",
			value: event.value || "",
			agentName: event.agentName,
			timestamp: Date.now(),
		};
		permissionQueue.push(request);

		// 隐藏 working loader
		if (uiCalmMode && agentActive) {
			workingIndicatorHidden = true;
		}
	}), pi.events.on("permissions:decision", (event: any) => {
		// 权限决策完成，从队列中移除
		const requestId = event.requestId;
		const index = permissionQueue.findIndex((r) => r.requestId === requestId);
		if (index !== -1) {
			permissionQueue.splice(index, 1);
		}

		// 如果队列为空，恢复 Footer
		if (permissionQueue.length === 0) {
			permissionUiActive = false;
			frozenRenderData = null;

			// 恢复 working indicator
			if (workingIndicatorHidden) {
				workingIndicatorHidden = false;
			}

			// 强制刷新一次 Footer
			lastRenderTime = 0;
			lastRenderedContent = "";
		}
	})];

	// ── UI Calm 命令 ─────────────────────────────────────────────────

	pi.registerCommand("ui-calm", {
		description:
			"Toggle UI calm mode (reduces footer updates during streaming)",
		handler: (args: unknown, ctx: any) => {
			const action = (args as string)?.trim()?.toLowerCase();

			if (action === "on") {
				uiCalmMode = true;
				ctx.ui.notify("UI calm mode enabled", "info");
			} else if (action === "off") {
				uiCalmMode = false;
				ctx.ui.notify("UI calm mode disabled", "info");
			} else if (action === "status") {
				const status = uiCalmMode ? "enabled" : "disabled";
				ctx.ui.notify(`UI calm mode is ${status}`, "info");
			} else {
				ctx.ui.notify(
					"Usage: /ui-calm on|off|status\n\nUI calm mode reduces footer updates during streaming to prevent flickering. Default: on",
					"info",
				);
			}

			return Promise.resolve();
		},
	});

	pi.registerCommand("colorful-footer", {
		description: "Show colorful footer config",
		handler: (_args: unknown, ctx: any) => {
			ctx.ui.notify(
				"Colorful footer config: " + JSON.stringify(loadConfig(), null, 2),
				"info",
			);
			return Promise.resolve();
		},
	});
}
