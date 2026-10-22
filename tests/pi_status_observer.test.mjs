// 独立公开事件模拟；只运行仓库自己的观察代码，不加载 Pi 或社区插件。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import statusObserver, { formatContextMeter, observe, values } from "../agents/pi/support/status-observer.mjs";

const now = 1700000120000;
const assistant = (id, timestamp, extra = {}) => ({ id, type: "message", message: {
  role: "assistant", provider: "fictional", model: "demo", timestamp,
  usage: { input: 20, output: 10, cacheRead: 60, cacheWrite: 20, cost: { total: 0.01 } }, ...extra,
} });
function fixture() {
  const state = { branch: [assistant("a", now - 60000), assistant("b", now)], window: 2000, tokens: 1000 };
  const ctx = { model: { provider: "fictional", id: "demo" }, thinkingLevel: "medium",
    sessionManager: { getBranch: () => state.branch, getHeader: () => ({ timestamp: new Date(now - 120000).toISOString() }) },
    modelRegistry: { find: () => ({ cost: { input: 1, output: 2, cacheRead: 0.1, cacheWrite: 1 } }) },
    getContextUsage: () => ({ tokens: state.tokens, contextWindow: state.window }),
    isIdle: () => true, hasPendingMessages: () => false, ui: { notify() {} },
  };
  return { ctx, state };
}

test("every enabled template event has a public publisher and clears on shutdown", () => {
  const template = JSON.parse(readFileSync(new URL("../agents/pi/templates/pi-footer.json", import.meta.url), "utf8"));
  const eventRows = template.lines.map((row) => row.filter((widget) => widget.enabled && widget.type === "event")
    .map((widget) => widget.options.widgetId));
  assert.deepEqual(eventRows, [
    ["agentcfg-selection", "agentcfg-provider", "agentcfg-activity"],
    ["agentcfg-context", "agentcfg-meter", "agentcfg-tools"],
    ["agentcfg-statistics", "agentcfg-timing"],
  ]);
  assert.equal(template.lines.flat().filter((widget) => widget.enabled && widget.type === "thinking-level").length, 1);
  const handlers = new Map(), emitted = [];
  statusObserver({ on: (name, fn) => handlers.set(name, fn), registerCommand() {},
    events: { emit: (name, data) => { assert.equal(name, "pi-footer:update-widget"); emitted.push(data); } } });
  const { ctx } = fixture();
  handlers.get("session_start")({}, ctx);
  const expected = eventRows.flat().sort();
  assert.deepEqual(emitted.map((entry) => entry.widgetId).sort(), expected);
  for (const entry of emitted) assert.equal(typeof entry.value, "string");
  assert.equal(emitted.find((entry) => entry.widgetId === "agentcfg-selection").value, ctx.model.id);
  emitted.length = 0;
  handlers.get("session_shutdown")({}, ctx);
  assert.deepEqual(emitted.map((entry) => entry.widgetId).sort(), expected);
  assert.ok(emitted.every((entry) => entry.value === null));
});

test("branch-only usage, duplicate entry, compaction and tool/child text do not double count", () => {
  const { ctx, state } = fixture();
  state.branch.push(state.branch[0], { id: "tool", type: "message", message: { role: "toolResult", usage: { input: 9000 } } },
    { id: "compaction", type: "compaction", usage: { input: 3000 } }, { id: "child", type: "custom", data: { output: 99999 } });
  const result = observe(ctx, "working", now);
  assert.equal(result.input, 40);
  assert.equal(result.output, 20);
  assert.equal(result.cacheRate, 0.6);
  assert.equal(result.estimatedUsd, 0.02);
  assert.equal(result.percent, 50);
  assert.equal(result.elapsedSeconds, 120);
  assert.equal(result.outputPerMinute, 20);
  state.branch = [state.branch[0]];
  assert.equal(observe(ctx, "idle", now).input, 20);
  assert.equal(observe(ctx, "idle", now).outputPerMinute, null);
});

test("missing usage, cost and context remain unknown, including zero-price subscription models", () => {
  const { ctx, state } = fixture();
  state.branch.push(assistant("missing", now, { usage: {} }));
  state.window = null;
  state.tokens = null;
  let result = observe(ctx, "unknown", now);
  for (const key of ["input", "output", "cacheRate", "estimatedUsd", "window", "tokens", "percent"]) assert.equal(result[key], null);
  assert.equal(values(result).statistics, "USAGE n/a");
  assert.equal(result.permission, "unknown");
  state.branch = [assistant("zero", now)];
  ctx.modelRegistry.find = () => ({ cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } });
  assert.equal(observe(ctx, "idle", now).estimatedUsd, null);
  ctx.sessionManager.getHeader = () => null;
  assert.equal(observe(ctx, "idle", now).elapsedSeconds, null);
});

test("model changes do not fabricate window, price or earlier branch usage", () => {
  const { ctx, state } = fixture();
  ctx.model = { provider: "other", id: "long-model" };
  state.window = 4000;
  ctx.modelRegistry.find = () => undefined;
  const result = observe(ctx, "working", now);
  assert.equal(result.percent, 25);
  assert.equal(result.estimatedUsd, null);
  assert.equal(result.input, 40);
  assert.match(values(result).details, /other\/long-model/);
});

test("complete Kimi identity and compact English labels are delegated without width truncation", () => {
  const { ctx } = fixture();
  ctx.model = { provider: "agentcfg-example", id: "kimi-k2.5-2026-02-20-thinking" };
  const data = values(observe(ctx, "working", now));
  assert.equal(data.selection, "kimi-k2.5-2026-02-20-thinking");
  assert.equal(data.provider, "example");
  assert.equal(data.activity, "WORKING");
  const width = (text) => [...text].reduce((total, character) => total + (/[\u2e80-\ua4cf]/u.test(character) ? 2 : 1), 0);
  for (const columns of [60, 90, 130]) {
    assert.ok(width(`${data.activity} | ${data.selection}`) <= columns);
    assert.ok(width(data.context) <= columns);
  }
  assert.equal(data.context, "CTX 1k/2k · 50%");
  assert.equal(data.timing, "02:00 avg 20 tok/min");
  assert.match(data.details, /agentcfg-example\/kimi-k2.5-2026-02-20-thinking/);
  // 身份文字不插入ANSI或拆分中文/emoji；实际60/90/130列截断由社区渲染器负责。
  ctx.model.id = "中文模型👩‍💻完整名称\u001b\n";
  assert.equal(values(observe(ctx, "working", now)).selection, "中文模型👩‍💻完整名称");
});

test("compact values retain full identifiers and exact observations in details", () => {
  const { ctx } = fixture();
  ctx.model = { provider: `agentcfg-${"long-provider-".repeat(12)}`, id: "long-model-".repeat(20) };
  ctx.thinkingLevel = "custom-effort";
  const snapshot = { ...observe(ctx, "working", now), input: 12001, output: 1599,
    cacheRead: 48001, cacheRate: 0.80001, cacheWrite: 0, estimatedUsd: 0.123456,
    tokens: 64001, window: 256001, percent: 25.0001, outputPerMinute: 1599.123 };
  const data = values(snapshot);
  assert.equal(data.selection, `${ctx.model.id}`);
  assert.equal(data.provider, ctx.model.provider.slice("agentcfg-".length));
  assert.equal(data.statistics, "IN 12k · OUT 1.6k │ CACHE 80% (48k) │ EST $0.1235");
  assert.doesNotMatch(data.statistics, /write/i);
  assert.equal(data.context, "CTX 64k/256k · 25%");
  assert.equal(data.timing, "02:00 avg 1.6k tok/min");
  assert.ok(data.details.startsWith(`${ctx.model.provider}/${ctx.model.id} effort=custom-effort\n`));
  assert.match(data.details, /context tokens=64001; window=256001; percent=25.0001/);
  assert.match(data.details, /input=12001; output=1599; cacheRead=48001; cacheRate=0.80001; cacheWrite=0; estimatedUsd=0.123456/);
  assert.match(data.details, /branch output\/min=1599.123/);
  assert.match(data.details, /permission=unknown/);
  assert.match(data.details, /权限说明/);
  assert.match(data.details, /scope=current branch assistant usage; excludes compaction, cache warming and child tasks/);
  assert.match(data.details, /cost source=host price estimate, not billing/);
});

test("compact numeric thresholds, durations and zero estimates preserve unknown distinctions", () => {
  const { ctx } = fixture();
  const snapshot = observe(ctx, "idle", now);
  for (const [input, expected] of [[0, "0"], [999, "999"], [1000, "1k"], [1250, "1.3k"], [1000000, "1M"], [1250000, "1.3M"]]) {
    assert.ok(values({ ...snapshot, input }).statistics.startsWith(`IN ${expected} · `));
  }
  assert.equal(values({ ...snapshot, tokens: 230400, window: 256000, percent: 90 }).context, "CTX 230.4k/256k · 90% !");
  assert.equal(values({ ...snapshot, elapsedSeconds: 0, outputPerMinute: 0 }).timing, "00:00 avg 0 tok/min");
  assert.equal(values({ ...snapshot, elapsedSeconds: 3661 }).timing, "1:01:01 avg 20 tok/min");
  assert.equal(values({ ...snapshot, elapsedSeconds: null, outputPerMinute: null }).timing, "—");
  assert.match(values({ ...snapshot, estimatedUsd: 0 }).statistics, /EST \$0.0000$/);
  assert.equal(values({ ...snapshot, model: "unknown", effort: "unknown", activity: "invalid" }).selection, "—");
  assert.equal(values({ ...snapshot, activity: "invalid" }).activity, "UNKNOWN");
});

test("missing values differ from reported zero usage and real costs remain unknown", () => {
  const { ctx, state } = fixture();
  state.branch = [];
  state.tokens = null;
  state.window = null;
  const missing = values(observe(ctx, "unknown", now));
  assert.equal(missing.statistics, "USAGE n/a");
  assert.equal(missing.context, "CTX —/— · —");
  assert.equal(missing.activity, "UNKNOWN");
  state.branch = [assistant("zero", now, { usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } })];
  const zero = values(observe(ctx, "idle", now));
  assert.equal(zero.statistics, "IN 0 · OUT 0 │ CACHE -- (0) │ EST $--");
  assert.match(zero.details, /不是真实账单/);
});

test("menu prompt completion uses public idle and pending observations without overriding running or nested prompts", () => {
  const handlers = new Map(), emitted = [];
  statusObserver({ on: (name, fn) => handlers.set(name, fn), registerCommand() {},
    events: { emit: (_name, data) => emitted.push(data) } });
  const { ctx } = fixture();
  const activity = () => emitted.findLast((e) => e.widgetId === "agentcfg-activity").value;
  const menu = () => {
    handlers.get("ui_prompt_start")({}, ctx);
    handlers.get("ui_prompt_end")({}, ctx);
  };
  handlers.get("session_start")({}, ctx);
  menu();
  assert.equal(activity(), "IDLE");
  ctx.hasPendingMessages = () => true;
  menu();
  assert.equal(activity(), "QUEUED");
  ctx.isIdle = () => false;
  menu();
  assert.equal(activity(), "UNKNOWN");
  // 只有明确的 true 才能证明空闲。
  ctx.isIdle = () => undefined;
  menu();
  assert.equal(activity(), "UNKNOWN");
  handlers.get("agent_start")({}, ctx);
  menu();
  assert.equal(activity(), "WORKING");
  handlers.get("ui_prompt_start")({}, ctx);
  handlers.get("ui_prompt_start")({}, ctx);
  handlers.get("ui_prompt_end")({}, ctx);
  assert.equal(activity(), "PROMPT");
  handlers.get("ui_prompt_end")({}, ctx);
  assert.equal(activity(), "WORKING");
});

test("public lifecycle settles activity; turn_end does not; shutdown clears every event value", async () => {
  const handlers = new Map(), commands = new Map(), emitted = [];
  const pi = { on: (name, fn) => handlers.set(name, fn), registerCommand: (name, def) => commands.set(name, def),
    events: { emit: (_name, data) => emitted.push(data) } };
  statusObserver(pi);
  const { ctx } = fixture();
  handlers.get("session_start")({}, ctx);
  assert.deepEqual(emitted.slice(-8).map((e) => e.widgetId), ["agentcfg-selection", "agentcfg-activity",
    "agentcfg-provider", "agentcfg-context", "agentcfg-statistics", "agentcfg-timing", "agentcfg-tools", "agentcfg-meter"]);
  const timing = emitted.findLast((e) => e.widgetId === "agentcfg-timing");
  handlers.get("message_end")({}, ctx);
  assert.notEqual(emitted.findLast((e) => e.widgetId === "agentcfg-timing"), timing);
  handlers.get("agent_start")({}, ctx);
  handlers.get("turn_end")({}, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "WORKING");
  handlers.get("ui_prompt_start")({}, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "PROMPT");
  handlers.get("ui_prompt_end")({}, ctx);
  handlers.get("agent_settled")({ aborted: true }, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "IDLE");
  let details;
  ctx.model.provider = "agentcfg-example";
  ctx.ui.notify = (text) => { details = text; };
  await commands.get("agentcfg-status").handler("", ctx);
  assert.ok(details.startsWith("agentcfg-example/demo effort=medium\n"));
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-selection").value, "demo");
  assert.match(details, /current branch assistant usage/);
  handlers.get("session_shutdown")({}, ctx);
  assert.equal(emitted.slice(-8).filter((e) => e.value === null).length, 8);
  const other = [];
  statusObserver({ ...pi, events: { emit: (_name, data) => other.push(data) } });
  handlers.get("session_start")({}, ctx);
  assert.equal(other.find((e) => e.widgetId === "agentcfg-activity").value, "IDLE");
});


test("public tool invocation IDs track concurrency, duplicates and settled cleanup", async () => {
  const handlers = new Map(), emitted = [], commands = new Map();
  statusObserver({ on: (name, fn) => handlers.set(name, fn),
    registerCommand: (name, command) => commands.set(name, command),
    events: { emit: (_name, data) => emitted.push(data) } });
  const { ctx } = fixture();
  const tools = () => emitted.findLast((entry) => entry.widgetId === "agentcfg-tools").value;
  const event = (name, toolCallId) => handlers.get(name)({ toolCallId }, ctx);
  event("session_start");
  assert.equal(tools(), "TOOLS 0");
  event("agent_start");
  event("tool_execution_start", "first");
  event("tool_execution_start", "first");
  assert.equal(tools(), "TOOLS 1");
  event("tool_execution_start", "second");
  assert.equal(tools(), "TOOLS 2");
  event("turn_end");
  assert.equal(tools(), "TOOLS 2");
  assert.equal(handlers.has("agent_end"), false);
  event("tool_execution_end", "first");
  assert.equal(tools(), "TOOLS 1");
  event("tool_execution_end", "first");
  assert.equal(tools(), "TOOLS 1");
  event("tool_execution_end", "second");
  assert.equal(tools(), "TOOLS 0");
  event("tool_execution_start", "third");
  event("agent_settled");
  assert.equal(tools(), "TOOLS 0");
  event("tool_execution_start", "fourth");
  let details;
  ctx.ui.notify = (text) => { details = text; };
  await commands.get("agentcfg-status").handler("", ctx);
  assert.match(details, /active tools=1; scope=current host tool invocations; excludes subagent\/background totals/);
  event("agent_start");
  assert.equal(tools(), "TOOLS 0");
  event("session_shutdown");
  assert.equal(emitted.slice(-8).filter((entry) => entry.value === null).length, 8);
  event("tool_execution_start", "after-shutdown");
  assert.equal(tools(), "TOOLS --");
});

test("busy reload and branch reset retain unknown tool baseline until settled", () => {
  const handlers = new Map(), emitted = [];
  statusObserver({ on: (name, fn) => handlers.set(name, fn), registerCommand() {},
    events: { emit: (_name, data) => emitted.push(data) } });
  const { ctx } = fixture();
  const tools = () => emitted.findLast((entry) => entry.widgetId === "agentcfg-tools").value;
  assert.equal(observe(ctx, "working", now).activeTools, null);
  assert.equal(values(observe(ctx, "working", now)).tools, "TOOLS --");
  assert.equal(observe(ctx, "working", now, 12).activeTools, 12);
  assert.equal(values(observe(ctx, "working", now, 12)).tools, "TOOLS 12");
  for (const reset of ["session_start", "session_tree"]) {
    ctx.isIdle = () => false;
    handlers.get(reset)({}, ctx);
    assert.equal(tools(), "TOOLS --");
    handlers.get("tool_execution_start")({ toolCallId: "observed" }, ctx);
    assert.equal(tools(), "TOOLS --");
    handlers.get("tool_execution_end")({ toolCallId: "observed" }, ctx);
    assert.equal(tools(), "TOOLS --");
    handlers.get("turn_end")({}, ctx);
    assert.equal(tools(), "TOOLS --");
    handlers.get("agent_settled")({}, ctx);
    assert.equal(tools(), "TOOLS 0");
  }
  ctx.isIdle = () => undefined;
  handlers.get("session_start")({}, ctx);
  assert.equal(tools(), "TOOLS --");
  ctx.isIdle = () => true;
  handlers.get("session_tree")({}, ctx);
  assert.equal(tools(), "TOOLS 0");
});


const meterText = (value) => value.replace(/\x1b\[[0-9;]*m/g, "");

test("context meter keeps forty slots with eighth-cell fill and visual saturation", () => {
  assert.equal(meterText(formatContextMeter(0)), `[${"─".repeat(40)}]`);
  assert.equal(meterText(formatContextMeter(1)), `[▍${"─".repeat(39)}]`);
  assert.equal(meterText(formatContextMeter(12.65625)), `[${"█".repeat(5)}▏${"─".repeat(34)}]`);
  assert.equal(meterText(formatContextMeter(100)), `[${"█".repeat(40)}]`);
  assert.equal(formatContextMeter(125), formatContextMeter(100));
  for (const [index, glyph] of [..."▏▎▍▌▋▊▉"].entries()) {
    assert.equal(meterText(formatContextMeter((index + 1) * 0.3125)), `[${glyph}${"─".repeat(39)}]`);
  }
  for (const percent of [0, 1, 12.65625, 49.999, 50, 69.999, 70, 84.999, 85, 100, 125, Number.MAX_VALUE]) {
    assert.equal([...meterText(formatContextMeter(percent))].length, 42);
  }
});

test("context meter thresholds color fill separately from empty slots and frame using only foreground SGR", () => {
  for (const [percent, color] of [[0, 151], [49.49, 151], [49.5, 116], [50, 116], [69.49, 116], [69.5, 223], [70, 223], [84.49, 223], [84.5, 211], [85, 211], [100, 211]]) {
    const meter = formatContextMeter(percent);
    assert.ok(meter.includes(`\x1b[38;5;${color}m`));
    assert.ok(meter.startsWith("\x1b[38;5;243m["));
    assert.ok(meter.endsWith("\x1b[38;5;243m]\x1b[39m"));
    assert.match(meter, /\x1b\[38;5;243m─*/);
    const text = meter.replace(/\x1b\[(?:38;5;(?:151|116|223|211|243)|39)m/g, "");
    assert.equal(text, meterText(meter));
    assert.doesNotMatch(text, /[\p{Cc}\p{Cf}]/u);
  }
});

test("unknown context meter has a centered label and never resembles reported zero or full usage", () => {
  const unknown = formatContextMeter(null);
  assert.equal(meterText(unknown), `[${"·".repeat(15)} unknown ${"·".repeat(16)}]`);
  assert.equal([...meterText(unknown)].length, 42);
  assert.ok(unknown.includes("\x1b[38;5;243m"));
  assert.doesNotMatch(meterText(unknown), /[█▏▎▍▌▋▊▉─]/u);
  for (const invalid of [undefined, null, NaN, Infinity, -Infinity, -1, "1", "\x1b[0m", {}]) {
    assert.equal(formatContextMeter(invalid), unknown);
  }
  assert.equal(unknown.replace(/\x1b\[(?:38;5;243|39)m/g, ""), meterText(unknown));
});

test("meter formatting preserves exact context details and never adds ANSI to user identifiers", () => {
  const { ctx, state } = fixture();
  state.tokens = 2500;
  const snapshot = observe(ctx, "working", now);
  const data = values(snapshot);
  assert.equal(snapshot.percent, 125);
  assert.equal(data.context, "CTX 2.5k/2k · 125% !");
  assert.equal(data.meter, formatContextMeter(100));
  assert.match(data.details, /context tokens=2500; window=2000; percent=125/);
  assert.doesNotMatch(data.details, /\x1b/);
  state.tokens = null;
  const missing = values(observe(ctx, "working", now));
  assert.equal(missing.meter, formatContextMeter(null));
  assert.match(missing.details, /context tokens=—; window=2000; percent=—/);
  ctx.model = { provider: "agentcfg-demo\x1b[31m", id: "model\x1b[0m" };
  ctx.thinkingLevel = "medium\x1b[0m";
  const identifiers = values(observe(ctx, "working", now));
  for (const field of ["selection", "provider", "details"]) assert.doesNotMatch(identifiers[field], /\x1b/);
});


test("Usage groups distinguish partially known cache, all unknown and reported zero", () => {
  const { ctx } = fixture();
  const snapshot = observe(ctx, "idle", now);
  assert.equal(values({ ...snapshot, cacheRead: null }).statistics, "IN 40 · OUT 20 │ CACHE 60% (--) │ EST $0.0200");
  assert.equal(values({ ...snapshot, cacheRead: 1600, cacheRate: null }).statistics, "IN 40 · OUT 20 │ CACHE -- (1.6k) │ EST $0.0200");
  assert.equal(values({ ...snapshot, cacheRead: null, cacheRate: null }).statistics, "IN 40 · OUT 20 │ CACHE -- │ EST $0.0200");
  const unknown = { ...snapshot, input: null, output: null, cacheRead: null, cacheRate: null, estimatedUsd: null, cacheWrite: 0 };
  assert.equal(values(unknown).statistics, "USAGE n/a");
  assert.equal(values({ ...unknown, input: 0 }).statistics, "IN 0 · OUT -- │ CACHE -- │ EST $--");
  assert.equal(values({ ...unknown, input: 0, output: 0, cacheRead: 0, cacheRate: 0, estimatedUsd: 0 }).statistics,
    "IN 0 · OUT 0 │ CACHE 0% (0) │ EST $0.0000");
  assert.match(values(unknown).details, /主栏 -- 表示数据未上报或无法确认/);
  assert.equal(values({ ...snapshot, outputPerMinute: null }).timing, "02:00");
  assert.equal(values({ ...snapshot, outputPerMinute: 0 }).timing, "02:00 avg 0 tok/min");
  assert.match(values({ ...snapshot, outputPerMinute: null }).details, /branch output\/min=—/);
  for (const key of ["statistics", "tools", "selection"]) assert.doesNotMatch(values(snapshot)[key], /[↑↓\ue000-\uf8ff]/u);
});


test("selection stays a model value while off and unavailable effort remain explicit in details", () => {
  const { ctx } = fixture();
  for (const effort of ["off", undefined]) {
    ctx.thinkingLevel = effort;
    const snapshot = observe(ctx, "idle", now);
    const data = values(snapshot);
    assert.equal(data.selection, "demo");
    assert.match(data.details, effort === "off" ? /effort=off\n/ : /effort=unknown\n/);
    assert.equal(snapshot.activity, "idle");
    assert.equal(data.activity, "IDLE");
    assert.match(data.details, /activity=idle; permission=unknown/);
  }
});


test("rounded context labels, colors and risk marker agree while details keep the raw percentage", () => {
  const { ctx } = fixture();
  const snapshot = observe(ctx, "working", now);
  for (const [percent, label, color, warning] of [[0, 0, 151, false], [49.6, 50, 116, false],
    [69.6, 70, 223, false], [84.6, 85, 211, true], [100, 100, 211, true]]) {
    const data = values({ ...snapshot, percent });
    assert.equal(data.context, `CTX 1k/2k · ${label}%${warning ? " !" : ""}`);
    assert.ok(data.meter.includes(`\x1b[38;5;${color}m`));
    assert.ok(data.details.includes(`percent=${percent}\n`));
    assert.equal([...meterText(data.meter)].length, 42);
  }
  const unknown = values({ ...snapshot, percent: null });
  assert.equal(unknown.context, "CTX 1k/2k · —");
  assert.ok(meterText(unknown.meter).includes("unknown"));
});
