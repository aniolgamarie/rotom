// 观察公开数据并格式化单个meter段；全局布局、终端截断和 Git 查询由 pi-footer 所有。
const finite = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const visualPercent = (value) => finite(value) ? Math.round(value) : null;
const clean = (value) => String(value ?? "unknown").replace(/[\p{Cc}\p{Cf}]/gu, (character) => character === "\u200d" ? character : "");
const WIDGETS = ["selection", "activity", "provider", "context", "statistics", "timing", "tools", "meter"];

export function formatContextMeter(percent) {
  const width = 40;
  const paint = (color, text) => `\x1b[38;5;${color}m${text}`;
  let body;
  if (!finite(percent)) {
    const label = " unknown ";
    const left = Math.floor((width - label.length) / 2);
    body = paint(243, `${"·".repeat(left)}${label}${"·".repeat(width - label.length - left)}`);
  } else {
    const clamped = Math.min(100, percent);
    const steps = Math.round(clamped / 100 * width * 8);
    const full = Math.floor(steps / 8), partial = steps % 8;
    const filled = `${"█".repeat(full)}${partial ? "▏▎▍▌▋▊▉"[partial - 1] : ""}`;
    // 填充保留原始比例的八分格精度，颜色与数字/风险提示使用同一取整比例。
    const rounded = visualPercent(percent);
    const color = rounded >= 85 ? 211 : rounded >= 70 ? 223 : rounded >= 50 ? 116 : 151;
    body = paint(color, filled) + paint(243, "─".repeat(width - full - (partial ? 1 : 0)));
  }
  return `${paint(243, "[")}${body}${paint(243, "]")}\x1b[39m`;
}

export function observe(ctx, activity, now = Date.now(), activeTools = null) {
  const seen = new Set(), messages = [];
  for (const entry of ctx.sessionManager.getBranch()) {
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    if (entry.type === "message" && entry.message?.role === "assistant") messages.push(entry.message);
  }
  const sum = (field) => messages.length && messages.every((m) => finite(m.usage?.[field]))
    ? messages.reduce((total, m) => total + m.usage[field], 0) : null;
  const input = sum("input"), output = sum("output"), read = sum("cacheRead"), write = sum("cacheWrite");
  const denominator = [input, read, write].every(finite) ? input + read + write : null;
  const cacheRate = finite(denominator) && denominator > 0 ? read / denominator : null;
  const priced = (message) => {
    const amount = message.usage?.cost?.total;
    if (!finite(amount)) return false;
    const model = ctx.modelRegistry.find(message.provider, message.model);
    // 宿主的价格表估算不是服务账单；全零未知费率不能显示为免费。
    return model?.cost && Object.values(model.cost).some((value) => finite(value) && value > 0);
  };
  const estimatedUsd = messages.length && messages.every(priced)
    ? messages.reduce((total, message) => total + message.usage.cost.total, 0) : null;
  const context = ctx.getContextUsage();
  const tokens = finite(context?.tokens) ? context.tokens : null;
  const window = finite(context?.contextWindow) && context.contextWindow > 0 ? context.contextWindow : null;
  const percent = finite(tokens) && finite(window) ? tokens / window * 100 : null;
  const timestamp = Date.parse(ctx.sessionManager.getHeader()?.timestamp ?? "");
  const elapsedSeconds = Number.isFinite(timestamp) && timestamp <= now ? Math.floor((now - timestamp) / 1000) : null;
  const times = messages.map((m) => m.timestamp);
  const interval = times.length > 1 && times.every(finite)
    ? times.reduce((max, value) => Math.max(max, value), 0) - times.reduce((min, value) => Math.min(min, value), Infinity) : null;
  const outputPerMinute = finite(output) && finite(interval) && interval > 0 ? output * 60000 / interval : null;
  return { provider: clean(ctx.model?.provider), model: clean(ctx.model?.id), effort: clean(ctx.thinkingLevel),
    activity, activeTools, input, output, cacheRead: read, cacheWrite: write, cacheRate, estimatedUsd,
    tokens, window, percent, elapsedSeconds, outputPerMinute, permission: "unknown",
    scope: "current branch assistant usage; excludes compaction, cache warming and child tasks", updatedAt: now };
}

export function values(snapshot) {
  const number = (value) => finite(value) ? String(value) : "—";
  const compact = (value) => {
    if (!finite(value)) return "—";
    const unit = value >= 1000000 ? 1000000 : value >= 1000 ? 1000 : 1;
    return `${unit === 1 ? Math.round(value) : Number((value / unit).toFixed(1))}${unit === 1000000 ? "M" : unit === 1000 ? "k" : ""}`;
  };
  const label = (value) => !value || value === "unknown" ? "—" : clean(value);
  const activity = ["working", "prompt", "queued", "idle", "unknown"].includes(snapshot.activity)
    ? snapshot.activity : "unknown";
  const percent = visualPercent(snapshot.percent);
  const context = `CTX ${compact(snapshot.tokens)}/${compact(snapshot.window)} · ${finite(percent)
    ? `${percent}%${percent >= 85 ? " !" : ""}` : "—"}`;
  const uiNumber = (value) => finite(value) ? compact(value) : "--";
  const cache = !finite(snapshot.cacheRead) && !finite(snapshot.cacheRate) ? "CACHE --"
    : `CACHE ${finite(snapshot.cacheRate) ? `${Math.round(snapshot.cacheRate * 100)}%` : "--"} (${uiNumber(snapshot.cacheRead)})`;
  const usage = [snapshot.input, snapshot.output, snapshot.cacheRead, snapshot.cacheRate, snapshot.estimatedUsd].every((value) => !finite(value))
    ? "USAGE n/a" : `IN ${uiNumber(snapshot.input)} · OUT ${uiNumber(snapshot.output)} │ ${cache} │ EST $${finite(snapshot.estimatedUsd) ? snapshot.estimatedUsd.toFixed(4) : "--"}`;
  const duration = finite(snapshot.elapsedSeconds)
    ? `${snapshot.elapsedSeconds >= 3600 ? `${Math.floor(snapshot.elapsedSeconds / 3600)}:` : ""}${String(Math.floor(snapshot.elapsedSeconds / 60) % 60).padStart(2, "0")}:${String(snapshot.elapsedSeconds % 60).padStart(2, "0")}` : "—";
  return {
    selection: label(snapshot.model),
    provider: label(snapshot.provider.replace(/^agentcfg-/, "")),
    activity: activity.toUpperCase(),
    context,
    statistics: usage,
    timing: `${duration}${finite(snapshot.outputPerMinute) ? ` avg ${compact(snapshot.outputPerMinute)} tok/min` : ""}`,
    tools: `TOOLS ${finite(snapshot.activeTools) ? number(snapshot.activeTools) : "--"}`,
    meter: formatContextMeter(snapshot.percent),
    details: [
      `${snapshot.provider}/${snapshot.model} effort=${snapshot.effort}`,
      `activity=${snapshot.activity}; permission=${snapshot.permission}`,
      `active tools=${number(snapshot.activeTools)}; scope=current host tool invocations; excludes subagent/background totals`,
      "任务说明：公开事件仅支持当前宿主工具调用数，未提供子代理或后台任务总数。",
      "权限说明：宿主未提供可查询的权限状态；此项不代表权限保护。",
      `context tokens=${number(snapshot.tokens)}; window=${number(snapshot.window)}; percent=${number(snapshot.percent)}`,
      `branch input=${number(snapshot.input)}; output=${number(snapshot.output)}; cacheRead=${number(snapshot.cacheRead)}; cacheRate=${number(snapshot.cacheRate)}; cacheWrite=${number(snapshot.cacheWrite)}; estimatedUsd=${number(snapshot.estimatedUsd)}`,
      "— 和主栏 -- 表示数据未上报或无法确认；USAGE n/a 表示主栏用量全部未知；已上报的零值显示为 0。EST $为宿主价格表估算USD，不是真实账单；未知费率不代表免费。",
      `session seconds=${number(snapshot.elapsedSeconds)} (session header); branch output/min=${number(snapshot.outputPerMinute)} (assistant timestamp interval)`,
      `scope=${snapshot.scope}; cost source=host price estimate, not billing; updated=${new Date(snapshot.updatedAt).toISOString()}`,
    ].join("\n"),
  };
}

export default function statusObserver(pi) {
  let activity = "unknown", running = false, prompts = 0, toolsKnown = false;
  const activeTools = new Set();
  const publish = (ctx) => {
    const data = values(observe(ctx, activity, Date.now(), toolsKnown ? activeTools.size : null));
    for (const key of WIDGETS) {
      pi.events.emit("pi-footer:update-widget", { widgetId: `agentcfg-${key}`, value: data[key] });
    }
    return data;
  };
  const reset = (_event, ctx) => {
    prompts = 0;
    activeTools.clear();
    // 忙时重载或切换分支可能漏过开始事件，已见事件不能补全未知基线。
    toolsKnown = ctx.isIdle() === true;
    running = !ctx.isIdle();
    activity = running ? "working" : ctx.hasPendingMessages() ? "queued" : "idle";
    publish(ctx);
  };
  for (const event of ["session_start", "session_tree"]) pi.on(event, reset);
  pi.on("agent_start", (_event, ctx) => {
    activeTools.clear();
    toolsKnown = true;
    running = true;
    activity = "working";
    publish(ctx);
  });
  pi.on("tool_execution_start", (event, ctx) => {
    activeTools.add(event.toolCallId);
    publish(ctx);
  });
  pi.on("tool_execution_end", (event, ctx) => {
    activeTools.delete(event.toolCallId);
    publish(ctx);
  });
  pi.on("agent_settled", (_event, ctx) => {
    activeTools.clear();
    toolsKnown = true;
    running = false;
    activity = prompts ? "prompt" : ctx.hasPendingMessages() ? "queued" : "idle";
    publish(ctx);
  });
  pi.on("ui_prompt_start", (_event, ctx) => { prompts++; activity = "prompt"; publish(ctx); });
  pi.on("ui_prompt_end", (_event, ctx) => {
    prompts = Math.max(0, prompts - 1);
    activity = prompts ? "prompt" : running ? "working"
      : ctx.isIdle() === true ? ctx.hasPendingMessages() ? "queued" : "idle" : "unknown";
    publish(ctx);
  });
  // turn_end 只刷新统计，不用它推断整个 agent 已空闲。
  for (const event of ["turn_end", "message_end", "model_select", "thinking_level_select", "session_compact"]) {
    pi.on(event, (_event, ctx) => publish(ctx));
  }
  pi.registerCommand("agentcfg-status", {
    description: "Show complete public status observations and their scope",
    handler: async (_args, ctx) => ctx.ui.notify(publish(ctx).details, "info"),
  });
  pi.on("session_shutdown", () => {
    for (const key of WIDGETS) {
      pi.events.emit("pi-footer:update-widget", { widgetId: `agentcfg-${key}`, value: null });
    }
    activeTools.clear();
    toolsKnown = false;
    activity = "unknown";
    running = false;
    prompts = 0;
  });
}
