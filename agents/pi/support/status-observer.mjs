// 仅观察公开数据并发布事件；布局、终端渲染和 Git 查询由 pi-footer 所有。
const finite = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const clean = (value) => String(value ?? "unknown").replace(/[\p{Cc}\p{Cf}]/gu, "");
export function compact(value, budget) {
  const clusters = [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(clean(value))];
  let result = "", used = 0;
  for (const [index, { segment }] of clusters.entries()) {
    const width = /[\p{Extended_Pictographic}\u1100-\u115f\u2329\u232a\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe10-\ufe6f\uff01-\uff60\uffe0-\uffe6]/u.test(segment) ? 2 : 1;
    if (used + width > budget - (index < clusters.length - 1 ? 1 : 0)) return result + "…";
    result += segment;
    used += width;
  }
  return result;
}

export function observe(ctx, activity, now = Date.now()) {
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
    activity, input, output, cacheRead: read, cacheWrite: write, cacheRate, estimatedUsd,
    tokens, window, percent, elapsedSeconds, outputPerMinute, permission: "unknown",
    scope: "current branch assistant usage; excludes compaction, cache warming and child tasks", updatedAt: now };
}

export function values(snapshot) {
  const number = (value) => finite(value) ? String(Math.round(value)) : "unknown";
  const context = finite(snapshot.percent)
    ? `ctx ${Math.round(snapshot.percent)}%${snapshot.percent >= 85 ? "!" : ""}` : "ctx unknown";
  const usage = `branch in ${number(snapshot.input)} out ${number(snapshot.output)} cache ${finite(snapshot.cacheRate) ? `${Math.round(snapshot.cacheRate * 100)}%` : "unknown"} estUSD ${finite(snapshot.estimatedUsd) ? snapshot.estimatedUsd.toFixed(4) : "unknown"}`;
  // 紧凑标签省略受管路由前缀；观察记录与完整详情仍保留原身份。
  const providerLabel = snapshot.provider.replace(/^agentcfg-/, "");
  return {
    selection: `${compact(providerLabel, 8)}/${compact(snapshot.model, 12)} ${compact(snapshot.effort, 6)}`,
    activity: snapshot.activity,
    context,
    statistics: usage,
    details: [
      `${snapshot.provider}/${snapshot.model} effort=${snapshot.effort}`,
      `activity=${snapshot.activity}; permission=${snapshot.permission}`,
      "权限说明：宿主未提供可查询的权限状态；此项不代表权限保护。",
      `context=${number(snapshot.tokens)}/${number(snapshot.window)} (${finite(snapshot.percent) ? snapshot.percent.toFixed(1) + "%" : "unknown"})`,
      usage,
      `session seconds=${number(snapshot.elapsedSeconds)} (session header); branch output/min=${number(snapshot.outputPerMinute)} (assistant timestamp interval)`,
      `scope=${snapshot.scope}; cost source=host price estimate, not billing; updated=${new Date(snapshot.updatedAt).toISOString()}`,
    ].join("\n"),
  };
}

export default function statusObserver(pi) {
  let activity = "unknown", running = false, prompts = 0;
  const publish = (ctx) => {
    const data = values(observe(ctx, activity));
    for (const key of ["selection", "activity", "context", "statistics"]) {
      pi.events.emit("pi-footer:update-widget", { widgetId: `agentcfg-${key}`, value: data[key] });
    }
    return data;
  };
  const reset = (_event, ctx) => {
    prompts = 0;
    running = !ctx.isIdle();
    activity = running ? "working" : ctx.hasPendingMessages() ? "queued" : "idle";
    publish(ctx);
  };
  for (const event of ["session_start", "session_tree"]) pi.on(event, reset);
  pi.on("agent_start", (_event, ctx) => { running = true; activity = "working"; publish(ctx); });
  pi.on("agent_settled", (_event, ctx) => {
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
    for (const key of ["selection", "activity", "context", "statistics"]) {
      pi.events.emit("pi-footer:update-widget", { widgetId: `agentcfg-${key}`, value: null });
    }
    activity = "unknown";
    running = false;
    prompts = 0;
  });
}
