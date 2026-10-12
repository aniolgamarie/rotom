// 真实本地入口和业务helper；只有Pi事件/UI/overlay peer是假对象，不启动SDK宿主。
import assert from "node:assert/strict";
import { test } from "node:test";
import footer from "../../packages/colorful-footer/index.ts";
import loopGuard, { installLoopGuard } from "../../packages/loop-guard/index.ts";
import { readLoopGuardConfig } from "../../packages/loop-guard/config.ts";
import { LOOP_GUARD_CHECKPOINT_TYPE } from "../../packages/loop-guard/persistence.ts";
import todo, { PREWARM_DELAY_MS } from "../../packages/todo-vendor/index.ts";
import { __resetState, getTodos } from "../../packages/todo-vendor/todo.ts";
import { getActiveRenderSession } from "../../packages/todo-vendor/state/store.ts";

const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1");
const invalidateKey = Symbol.for("session-yolo:invalidate");
const yoloKey = Symbol.for("session-yolo:state");
const theme = { fg: (_color, value) => value, bold: value => value, strikethrough: value => value };

function runtimeFixture(t, plugins = ["colorful-footer", "loop-guard", "pi-todo"]) {
  for (const key of [runtimeKey, invalidateKey, yoloKey]) {
    const old = Object.getOwnPropertyDescriptor(globalThis, key);
    t.after(() => { if (old) Object.defineProperty(globalThis, key, old); else delete globalThis[key]; });
  }
  globalThis[runtimeKey] = { owner: { role: "manager" }, manifest: { plugins, options: {
    ui: { footer: { adaptive: false, maxLines: 3 } },
    loop_guard: { repeatLimit: 2, advisoryMode: "off", checkpointScanLimit: 16 },
    todo: { locale: "en", collapseKey: "off" },
  } } };
}

function capturePi() {
  const handlers = new Map(), commands = new Map(), tools = new Map(), renderers = new Map(), listeners = new Map();
  const entries = [], stopped = [];
  const pi = {
    on: (name, handler) => { assert.equal(handlers.has(name), false); handlers.set(name, handler); },
    registerCommand: (name, definition) => commands.set(name, definition),
    registerTool: definition => tools.set(definition.name, definition),
    registerShortcut: () => assert.fail("collapseKey=off must not register a shortcut"),
    registerEntryRenderer: (name, renderer) => renderers.set(name, renderer),
    appendEntry: (customType, data) => entries.push({ type: "custom", customType, data: structuredClone(data) }),
    getThinkingLevel: () => "off",
    events: { on: (name, callback) => {
      listeners.set(name, callback);
      return () => { listeners.delete(name); stopped.push(name); };
    } },
  };
  return { pi, handlers, commands, tools, renderers, entries, listeners, stopped };
}

function sessionContext(id, branch = [], hasUI = true) {
  const notices = [], widgets = [], statuses = [];
  const ctx = {
    cwd: "/synthetic/project", mode: "rpc", hasUI,
    sessionManager: { getSessionId: () => id, getLeafId: () => "synthetic-leaf", getBranch: () => branch },
    ui: {
      notify: (text, kind) => notices.push({ text, kind }),
      setStatus: (key, value) => statuses.push({ key, value }),
      setWidget: (key, value) => widgets.push({ key, value }),
    },
  };
  return { ctx, notices, widgets, statuses };
}

function overlayFixture() {
  const calls = { imports: 0, constructed: 0, updates: 0, resets: 0, disposed: 0, hidden: 0 };
  class FakeOverlay {
    ui;
    constructor() { calls.constructed++; }
    setUICtx(ui) { this.ui = ui; }
    update() { calls.updates++; this.ui.setWidget("rpiv-todos", this); }
    resetCompletedDisplayState() { calls.resets++; }
    dispose() { calls.disposed++; this.ui.setWidget("rpiv-todos", undefined); }
    hideCompletedTasksFromPreviousTurn() { calls.hidden++; }
  }
  const importOverlay = async () => { calls.imports++; return { TodoOverlay: FakeOverlay }; };
  return { calls, importOverlay };
}

async function executeTodo(tool, ctx, params) {
  return tool.execute("synthetic-call", params, undefined, undefined, ctx);
}
function toolEntry(details, toolName = "todo") {
  return { type: "message", message: { role: "toolResult", toolName, details } };
}
async function settleTimerPromise() { for (let count = 0; count < 6; count++) await Promise.resolve(); }

// 入口负例必须经过真实manager/capability helper，不能用fake helper兜底。
test("local factories reject absent manager and unselected Todo capability", t => {
  runtimeFixture(t);
  delete globalThis[runtimeKey];
  assert.throws(() => loopGuard(capturePi().pi), /AGENTCFG_RUNTIME_REQUIRED/);
  globalThis[runtimeKey] = { owner: { role: "worker" }, manifest: { plugins: ["pi-todo"], options: {} } };
  assert.throws(() => todo(capturePi().pi, async () => assert.fail("overlay must not import")), /CAPABILITY_NOT_SELECTED/);
  globalThis[runtimeKey].owner.role = "manager";
  globalThis[runtimeKey].manifest.plugins = [];
  assert.throws(() => todo(capturePi().pi, async () => assert.fail("overlay must not import")), /CAPABILITY_NOT_SELECTED/);
});

test("provider peer fixtures and Todo js-to-ts rewrites accept only exact parent/target pairs", () => {
  const footerURL = new URL("../../packages/colorful-footer/index.ts", import.meta.url).href;
  const typesURL = new URL("../../packages/todo-vendor/tool/types.ts", import.meta.url).href;
  const todoURL = new URL("../../packages/todo-vendor/index.ts", import.meta.url).href;
  assert.match(import.meta.resolve("@earendil-works/pi-tui", footerURL), /^data:text\/javascript,/);
  assert.match(import.meta.resolve("@earendil-works/pi-ai", typesURL), /^data:text\/javascript,/);
  for (const parent of [import.meta.url, footerURL + "?unknown", "file:///outside/packages/colorful-footer/index.ts"]) {
    assert.throws(() => import.meta.resolve("@earendil-works/pi-tui", parent), { code: "ERR_MODULE_NOT_FOUND" });
  }
  assert.throws(() => import.meta.resolve("@earendil-works/pi-ai", footerURL), { code: "ERR_MODULE_NOT_FOUND" });
  assert.equal(import.meta.resolve("./config.js", todoURL), new URL("../../packages/todo-vendor/config.ts", import.meta.url).href);
  assert.match(import.meta.resolve("./todo-overlay.js", todoURL), /\/todo-overlay\.js$/);
  assert.match(import.meta.resolve("../colorful-footer/index.js", todoURL), /\/colorful-footer\/index\.js$/);
});

test("Footer callbacks render synthetic usage/turn/permission state and release owned listeners", async t => {
  runtimeFixture(t);
  t.mock.timers.enable({ apis: ["Date"], now: 1_000_000 });
  const host = capturePi(), session = sessionContext("footer");
  let tokens = 500, branchName = "synthetic-main", branchChanged, component;
  let branch = [{ type: "message", message: { role: "assistant", usage: { input: 120, output: 40, cacheRead: 60, cost: { total: 0.25 } } } }];
  session.ctx.sessionManager.getBranch = () => branch;
  Object.assign(session.ctx, { model: { provider: "synthetic", id: "fake-model", contextWindow: 1000 }, getContextUsage: () => ({ tokens }) });
  session.ctx.ui.setFooter = factory => {
    component = factory({}, theme, { getGitBranch: () => branchName, onBranchChange: callback => { branchChanged = callback; } });
  };
  footer(host.pi);
  const invalidate = globalThis[invalidateKey];
  assert.equal(typeof invalidate, "function");
  await host.handlers.get("session_start")({}, session.ctx);
  const initial = component.render(1000).join("\n");
  assert.match(initial, /idle/); assert.match(initial, /synthetic\/fake-model/);
  assert.match(initial, /synthetic-main/); assert.match(initial, /50%/); assert.match(initial, /0\.2500/);
  await host.handlers.get("turn_start")({}, session.ctx);
  tokens = 800; t.mock.timers.tick(1000);
  const running = component.render(1000).join("\n");
  assert.match(running, /run/); assert.match(running, /80%/);
  host.listeners.get("permissions:ui_prompt")({ requestId: "synthetic-prompt" });
  tokens = 900; t.mock.timers.tick(1000);
  assert.equal(component.render(1000).join("\n"), running);
  host.listeners.get("permissions:decision")({ requestId: "synthetic-prompt" });
  assert.match(component.render(1000).join("\n"), /90%/);
  branchName = "synthetic-next"; branchChanged(); component.invalidate();
  assert.match(component.render(1000).join("\n"), /synthetic-next/);
  await host.handlers.get("turn_end")({}, session.ctx); t.mock.timers.tick(1000);
  assert.match(component.render(1000).join("\n"), /idle/);
  globalThis[yoloKey] = { owner: "agentcfg", mode: "cwd", effective: false };
  invalidate(); assert.match(component.render(1000).join("\n"), /permission: constrained/);
  await host.commands.get("ui-calm").handler("off", session.ctx);
  await host.commands.get("ui-calm").handler("status", session.ctx);
  await host.commands.get("colorful-footer").handler("", session.ctx);
  assert.ok(session.notices.some(row => /UI calm mode is disabled/.test(row.text)));
  assert.ok(session.notices.some(row => /Colorful footer config/.test(row.text)));
  await host.handlers.get("session_shutdown")({}, session.ctx);
  assert.deepEqual(host.stopped.sort(), ["permissions:decision", "permissions:ui_prompt"]);
  assert.equal(host.listeners.size, 0); assert.equal(globalThis[invalidateKey], undefined);
  // 清理只能移除自身的全局invalidate，后来owner的替换必须保留。
  const second = capturePi(); footer(second.pi);
  const replacement = () => {}; globalThis[invalidateKey] = replacement;
  await second.handlers.get("session_shutdown")({}, session.ctx);
  assert.equal(globalThis[invalidateKey], replacement);
});

test("Footer never displays unmetered or missing cost as a measured zero", async t => {
  runtimeFixture(t);
  globalThis[runtimeKey].manifest.options.ui.footer.adaptive = true;
  t.mock.timers.enable({ apis: ["Date"], now: 1_000_000 });
  const host = capturePi(), session = sessionContext("footer-cost");
  let component;
  let branch = [{ type: "message", message: { role: "assistant", usage: { input: 10, output: 1, cost: { total: 0 } } } }];
  session.ctx.sessionManager.getBranch = () => branch;
  session.ctx.model = { provider: "synthetic", id: "fake", contextWindow: 1000 };
  session.ctx.getContextUsage = () => ({ tokens: 10 });
  session.ctx.ui.setFooter = factory => { component = factory({}, theme, { getGitBranch: () => "", onBranchChange() {} }); };
  globalThis[runtimeKey].manifest.cost_reporting = "unmetered";
  footer(host.pi); await host.handlers.get("session_start")({}, session.ctx);
  for (const width of [1000, 70]) {
    const rendered = component.render(width).join("\n");
    assert.match(rendered, /费用未计量/); assert.doesNotMatch(rendered, /\$0\.0000/);
  }
  delete globalThis[runtimeKey].manifest.cost_reporting;
  branch = [{ type: "message", message: { role: "assistant", usage: { input: 10, output: 1 } } }];
  await host.handlers.get("session_start")({}, session.ctx); t.mock.timers.tick(1000);
  assert.match(component.render(1000).join("\n"), /费用未计量/);
  await host.handlers.get("session_shutdown")({}, session.ctx);
});

test("Loop real handlers enforce repeat quota, persist checkpoints, replay and reset", async t => {
  runtimeFixture(t);
  const host = capturePi(), session = sessionContext("loop");
  const config = readLoopGuardConfig(); let now = 1_000_000;
  installLoopGuard(host.pi, { config, now: () => now });
  assert.equal(host.handlers.has("session_shutdown"), false);
  await host.handlers.get("session_start")({ reason: "new" }, session.ctx);
  assert.equal(host.entries[0].customType, LOOP_GUARD_CHECKPOINT_TYPE);
  const input = { path: "synthetic-file.txt" };
  for (let index = 0; index < 2; index++) {
    const toolCallId = "allowed-" + index;
    assert.equal(await host.handlers.get("tool_call")({ toolName: "read", toolCallId, input }, session.ctx), undefined);
    await host.handlers.get("tool_result")({ toolCallId, content: [{ type: "text", text: "changed-result-" + index }], isError: false }, session.ctx);
    now++;
  }
  const quota = await host.handlers.get("tool_call")({ toolName: "read", toolCallId: "quota", input }, session.ctx);
  assert.equal(quota.block, true); assert.equal(quota.terminate, false); assert.match(quota.reason, /exact-quota-exhausted/);
  const checkpoint = host.entries.at(-1);
  assert.equal(checkpoint.data.challenge.executions, 2);
  assert.equal(checkpoint.data.reason, "exact-quota-exhausted");
  const restored = capturePi(); installLoopGuard(restored.pi, { config, now: () => now });
  const restoredCtx = sessionContext("loop", [checkpoint]);
  await restored.handlers.get("session_start")({ reason: "resume" }, restoredCtx.ctx);
  const defiance = await restored.handlers.get("tool_call")({ toolName: "read", toolCallId: "defiance", input }, restoredCtx.ctx);
  assert.equal(defiance.block, true); assert.equal(defiance.terminate, true); assert.match(defiance.reason, /block-defiance/);
  const terminal = restored.entries.at(-1);
  const rendered = restored.renderers.get(LOOP_GUARD_CHECKPOINT_TYPE)(terminal, { expanded: true }).render(120).join("\n");
  assert.match(rendered, /block-defiance/);
  // 新interactive任务边界恢复额度，extension-origin输入不能越过latch。
  await restored.handlers.get("input")({ source: "extension" }, restoredCtx.ctx);
  assert.equal((await restored.handlers.get("tool_call")({ toolName: "read", toolCallId: "latched", input }, restoredCtx.ctx)).terminate, true);
  await restored.handlers.get("input")({ source: "interactive" }, restoredCtx.ctx);
  assert.equal(await restored.handlers.get("tool_call")({ toolName: "read", toolCallId: "fresh", input }, restoredCtx.ctx), undefined);
  await restored.commands.get("loop-guard").handler("reset", restoredCtx.ctx);
  assert.ok(restoredCtx.notices.some(row => row.text === "Loop guard reset"));
});

test("Loop branch recovery rejects scan-expired, malformed and uncorrelated checkpoints", async t => {
  runtimeFixture(t);
  const config = readLoopGuardConfig(), source = capturePi(), session = sessionContext("loop-negative");
  installLoopGuard(source.pi, { config, now: () => 1_000_000 });
  await source.handlers.get("session_start")({ reason: "new" }, session.ctx);
  const checkpoint = source.entries[0];
  const branches = [
    [checkpoint, ...Array.from({ length: config.checkpointScanLimit }, () => ({ type: "synthetic-unrelated" }))],
    [{ ...checkpoint, data: { ...checkpoint.data, version: 99 } }],
    [checkpoint, { type: "message", message: { role: "assistant", content: [{ type: "toolCall", id: "missing-result", name: "read", arguments: { path: "fixed" } }] } }],
  ];
  for (const branch of branches) {
    const target = capturePi(); installLoopGuard(target.pi, { config, now: () => 1_000_001 });
    const ctx = sessionContext("loop-negative", branch).ctx;
    await target.handlers.get("session_tree")({}, ctx);
    const blocked = await target.handlers.get("tool_call")({ toolName: "read", toolCallId: "new", input: { path: "fixed" } }, ctx);
    assert.equal(blocked.terminate, true); assert.match(blocked.reason, /checkpoint-incompatible/);
  }
  const mismatch = capturePi(); installLoopGuard(mismatch.pi, { config, now: () => 1_000_001 });
  await mismatch.handlers.get("session_start")({ reason: "resume" }, sessionContext("unrelated", [{ ...checkpoint, customType: "other-provider" }]).ctx);
  assert.equal(mismatch.entries.at(-1).data.reason, "allowed");
  assert.equal(mismatch.entries.at(-1).data.transition, "task-boundary");
});

test("Todo actual tool mutations, details replay, session isolation and eviction", async t => {
  runtimeFixture(t); __resetState(); t.after(__resetState);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const host = capturePi(), overlay = overlayFixture(); todo(host.pi, overlay.importOverlay);
  const foreground = sessionContext("foreground"), child = sessionContext("child", [], false);
  await host.handlers.get("session_start")({}, foreground.ctx);
  await host.handlers.get("session_start")({}, child.ctx);
  const tool = host.tools.get("todo");
  const created = await executeTodo(tool, foreground.ctx, { action: "create", subject: "Synthetic task" });
  assert.match(created.content[0].text, /Created #1/); assert.equal(created.details.nextId, 2);
  assert.equal(created.details.tasks[0].status, "pending");
  const invalid = await executeTodo(tool, foreground.ctx, { action: "update", id: 99, status: "completed" });
  assert.ok(invalid.details.error); assert.equal(getTodos("foreground")[0].status, "pending");
  const selfBlock = await executeTodo(tool, foreground.ctx, { action: "update", id: 1, addBlockedBy: [1] });
  assert.match(selfBlock.details.error, /cannot block #1 on itself/); assert.equal(getTodos("foreground")[0].status, "pending");
  const updated = await executeTodo(tool, foreground.ctx, { action: "update", id: 1, status: "in_progress", activeForm: "Testing synthetic task" });
  assert.match(updated.content[0].text, /pending → in_progress/);
  const completed = await executeTodo(tool, foreground.ctx, { action: "update", id: 1, status: "completed" });
  assert.equal(completed.details.tasks[0].status, "completed");
  const reopen = await executeTodo(tool, foreground.ctx, { action: "update", id: 1, status: "in_progress" });
  assert.match(reopen.details.error, /illegal transition/); assert.equal(getTodos("foreground")[0].status, "completed");
  const childCreated = await executeTodo(tool, child.ctx, { action: "create", subject: "Independent child task" });
  assert.equal(childCreated.details.tasks[0].id, 1); assert.equal(childCreated.details.tasks[0].status, "pending");
  assert.equal(getTodos("foreground")[0].subject, "Synthetic task");
  assert.equal(getTodos("child")[0].subject, "Independent child task");
  assert.match(tool.renderCall({ action: "get", id: 1 }, theme, {}).render(1000).join("\n"), /Synthetic task/);
  assert.match(tool.renderResult(completed, {}, theme, {}).render(1000).join("\n"), /completed/i);
  await host.handlers.get("tool_execution_end")({ toolName: "other", isError: false }, foreground.ctx);
  await host.handlers.get("tool_execution_end")({ toolName: "todo", isError: true }, foreground.ctx);
  assert.equal(overlay.calls.imports, 0);
  await host.handlers.get("tool_execution_end")({ toolName: "todo", isError: false }, foreground.ctx);
  assert.equal(overlay.calls.imports, 1); assert.equal(overlay.calls.constructed, 1);
  await host.handlers.get("agent_start")({}, foreground.ctx); assert.equal(overlay.calls.hidden, 1);
  await host.commands.get("todos").handler("", foreground.ctx);
  assert.ok(foreground.notices.some(row => /Synthetic task/.test(row.text)));
  // 重放来自真正tool.details；无效/其他工具结果不能覆盖最后一个匹配快照。
  const branch = [toolEntry(created.details), toolEntry(updated.details), toolEntry({ tasks: "bad", nextId: 9 }), toolEntry(childCreated.details, "other")];
  const restored = sessionContext("restored", branch, false);
  await host.handlers.get("session_start")({}, restored.ctx);
  assert.equal(getTodos("restored")[0].status, "in_progress");
  branch.push(toolEntry(completed.details));
  await host.handlers.get("session_tree")({}, restored.ctx);
  assert.equal(getTodos("restored")[0].status, "completed");
  assert.equal(getTodos("child")[0].status, "pending");
  await host.handlers.get("session_shutdown")({}, child.ctx);
  assert.deepEqual(getTodos("child"), []); assert.equal(overlay.calls.disposed, 0);
  assert.equal(getActiveRenderSession(), "foreground");
  await host.handlers.get("session_shutdown")({}, foreground.ctx);
  assert.deepEqual(getTodos("foreground"), []); assert.equal(overlay.calls.disposed, 1);
  assert.equal(getActiveRenderSession(), ""); assert.equal(foreground.widgets.at(-1).value, undefined);
  await host.handlers.get("session_shutdown")({}, restored.ctx);
});

test("Todo prewarm before and after shutdown imports only, without cancelling its timer", async t => {
  runtimeFixture(t); __resetState(); t.after(__resetState);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  assert.equal(PREWARM_DELAY_MS, 2000);
  for (const shutdownFirst of [false, true]) {
    const host = capturePi(), overlay = overlayFixture(), session = sessionContext("timer-" + shutdownFirst);
    todo(host.pi, overlay.importOverlay);
    await host.handlers.get("session_start")({}, session.ctx);
    if (shutdownFirst) await host.handlers.get("session_shutdown")({}, session.ctx);
    t.mock.timers.tick(1999); await settleTimerPromise(); assert.equal(overlay.calls.imports, 0);
    t.mock.timers.tick(1); await settleTimerPromise();
    assert.equal(overlay.calls.imports, 1); assert.equal(overlay.calls.constructed, 0);
    assert.equal(overlay.calls.updates, 0); assert.deepEqual(session.widgets, []);
    if (!shutdownFirst) await host.handlers.get("session_shutdown")({}, session.ctx);
    assert.equal(getActiveRenderSession(), "");
  }
});

test("Todo pending overlay import cannot resurrect widgets after foreground shutdown", async t => {
  runtimeFixture(t); __resetState(); t.after(__resetState);
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const host = capturePi(), overlay = overlayFixture(), session = sessionContext("late-overlay");
  let resolveImport, imports = 0;
  const pendingModule = new Promise(resolve => { resolveImport = resolve; });
  todo(host.pi, () => { imports++; return pendingModule; });
  await host.handlers.get("session_start")({}, session.ctx);
  await executeTodo(host.tools.get("todo"), session.ctx, { action: "create", subject: "Before shutdown" });
  const refresh = host.handlers.get("tool_execution_end")({ toolName: "todo", isError: false }, session.ctx);
  assert.equal(imports, 1);
  await host.handlers.get("session_shutdown")({}, session.ctx);
  resolveImport(await overlay.importOverlay()); await refresh;
  assert.equal(overlay.calls.constructed, 0); assert.equal(overlay.calls.updates, 0);
  assert.deepEqual(session.widgets, []); assert.deepEqual(getTodos("late-overlay"), []);
});
