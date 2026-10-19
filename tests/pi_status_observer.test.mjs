// 独立公开事件模拟；只运行仓库自己的观察代码，不加载 Pi 或社区插件。
import assert from "node:assert/strict";
import test from "node:test";
import statusObserver, { compact, observe, values } from "../agents/pi/support/status-observer.mjs";

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
  assert.match(values(result).statistics, /estUSD unknown/);
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

test("60/90/130-column configuration intent preserves the highest priority information", () => {
  const { ctx } = fixture();
  ctx.model = { provider: "中文很长的提供方名称", id: "超级长模型名称-for-narrow-screen" };
  const data = values(observe(ctx, "working", now));
  const width = (value) => [...value].reduce((n, c) => n + (/[\u2e80-\ua4cf]/u.test(c) ? 2 : 1), 0);
  const core = [data.selection, data.activity, data.context].join(" | ");
  for (const columns of [60, 90, 130]) assert.ok(width(core) <= columns);
  assert.match(core, /working.*ctx 50%/);
  assert.equal(compact("abc\u001b\n", 10), "abc");
  assert.match(data.details, /permission=unknown/);
});

test("compact managed provider labels remain distinct while full observations retain their identity", () => {
  const { ctx } = fixture();
  const selections = [];
  for (const provider of ["agentcfg-example", "agentcfg-another"]) {
    ctx.model = { provider, id: "demo" };
    const snapshot = observe(ctx, "idle", now);
    const data = values(snapshot);
    assert.equal(snapshot.provider, provider);
    assert.equal(data.selection, `${provider.slice("agentcfg-".length)}/demo medium`);
    assert.ok(data.details.startsWith(`${provider}/demo effort=medium\n`));
    selections.push(data.selection);
  }
  assert.notEqual(selections[0], selections[1]);
  for (const provider of ["fictional", "other-agentcfg-example"]) {
    ctx.model = { provider, id: "demo" };
    assert.equal(values(observe(ctx, "idle", now)).selection, `${compact(provider, 8)}/demo medium`);
  }
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
  assert.equal(activity(), "idle");
  ctx.hasPendingMessages = () => true;
  menu();
  assert.equal(activity(), "queued");
  ctx.isIdle = () => false;
  menu();
  assert.equal(activity(), "unknown");
  // 只有明确的 true 才能证明空闲。
  ctx.isIdle = () => undefined;
  menu();
  assert.equal(activity(), "unknown");
  handlers.get("agent_start")({}, ctx);
  menu();
  assert.equal(activity(), "working");
  handlers.get("ui_prompt_start")({}, ctx);
  handlers.get("ui_prompt_start")({}, ctx);
  handlers.get("ui_prompt_end")({}, ctx);
  assert.equal(activity(), "prompt");
  handlers.get("ui_prompt_end")({}, ctx);
  assert.equal(activity(), "working");
});

test("public lifecycle settles activity; turn_end does not; shutdown clears every event value", async () => {
  const handlers = new Map(), commands = new Map(), emitted = [];
  const pi = { on: (name, fn) => handlers.set(name, fn), registerCommand: (name, def) => commands.set(name, def),
    events: { emit: (_name, data) => emitted.push(data) } };
  statusObserver(pi);
  const { ctx } = fixture();
  handlers.get("session_start")({}, ctx);
  handlers.get("agent_start")({}, ctx);
  handlers.get("turn_end")({}, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "working");
  handlers.get("ui_prompt_start")({}, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "prompt");
  handlers.get("ui_prompt_end")({}, ctx);
  handlers.get("agent_settled")({ aborted: true }, ctx);
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-activity").value, "idle");
  let details;
  ctx.model.provider = "agentcfg-example";
  ctx.ui.notify = (text) => { details = text; };
  await commands.get("agentcfg-status").handler("", ctx);
  assert.ok(details.startsWith("agentcfg-example/demo effort=medium\n"));
  assert.equal(emitted.findLast((e) => e.widgetId === "agentcfg-selection").value, "example/demo medium");
  assert.match(details, /current branch assistant usage/);
  handlers.get("session_shutdown")({}, ctx);
  assert.equal(emitted.slice(-4).filter((e) => e.value === null).length, 4);
  const other = [];
  statusObserver({ ...pi, events: { emit: (_name, data) => other.push(data) } });
  handlers.get("session_start")({}, ctx);
  assert.equal(other.find((e) => e.widgetId === "agentcfg-activity").value, "idle");
});
