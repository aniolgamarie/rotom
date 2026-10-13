// 显式真实 Core/Perry 组件验收：模型和人工回答器为确定性 fixture。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
const runtime = process.argv[2], root = process.env.AGENTCFG_SMOKE_ROOT, output = process.env.AGENTCFG_SMOKE_RESULT;
assert(path.isAbsolute(runtime) && root && ["HOME", "DSH_HOME", "XDG_CONFIG_HOME"].every(key => process.env[key]?.startsWith(root + "/")));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)));
let report = process.argv[3] === "--read-audit" ? JSON.parse(fs.readFileSync(output, "utf8"))
  : { nonce: process.env.AGENTCFG_SMOKE_NONCE, checks: {}, cases: {}, requests: [], model_calls: 0, stage: "boot", real_human: "NOT RUN", sandbox: "NOT RUN", audit_restart: "NOT RUN", concurrent: "NOT RUN", off_late: "NOT RUN", unload: "NOT RUN" };
const save = () => fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
const stage = name => { report.stage = name; save(); };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const deadline = async (work, ms = 5000) => {
  let timer;
  try { return await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("STAGE_TIMEOUT")), ms); })]); }
  finally { clearTimeout(timer); }
};
const wait = async predicate => { for (let i = 0; i < 300 && !predicate(); i++) await sleep(10); assert(predicate(), "FIXTURE_STATE_TIMEOUT"); };
const audit = events => events.filter(e => ["approval/asked", "approval/decided", "autoReview/verdict"].includes(e.type))
  .map(e => ({ type: e.type, id: e.data.id ?? e.data.approvalId, ...(e.data.callId ? { callId: e.data.callId } : {}),
    ...(e.data.outcome ? { outcome: e.data.outcome } : {}) }));
let boot;
try {
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  boot = await deadline(runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_SMOKE_PATCH], args: [],
    packageManager: { command: "/bin/false", args: [], env: {} } }), 20000);
  const ctx = boot.ctx;
  assert(ctx.get("agents") && ctx.get("approval") && ctx.get("subagents") && ctx.get("tools"));
  if (process.argv[3] === "--read-audit") {
    stage("audit.restart");
    let native = 0, perry = 0;
    for (const id of report.sessions) {
      const handle = await ctx.get("sessionPersistence").open(id, "read");
      try {
        const events = audit((await handle.read()).events);
        const expected = report.audit[id];
        assert.deepEqual(events.filter(e => e.type !== "autoReview/verdict"), expected.filter(e => e.type !== "autoReview/verdict"));
        native += events.filter(e => e.type === "approval/asked").length;
        perry += events.filter(e => e.type === "autoReview/verdict").length;
      } finally { await handle.close(); }
    }
    report.audit_restart = { native_asked: native, perry_verdict: perry, original_pairing: native > 0 ? "PASS" : "FAIL",
      persistent_perry_audit: perry > 0 ? "PASS" : "FAIL", note: "Memory observer output is not durable verdict evidence." };
    report.release_gate = report.functional === "PASS" && perry > 0 && native > 0 ? "PASS" : "FAIL";
    report.stage = "complete"; save(); await boot.shutdown.shutdown(0);
  } else {
    stage("fixture.mount");
    const { LlmAdapter } = await moduleAt("@deepseek-ai/dsh-llm");
    const perry = await moduleAt("dsh-auto-review");
    const steps = new Map(), calls = new Map(), ready = new Set(), counts = new Map(), humans = new Map(), catalogs = [];
    report.created_agents = [];
    report.plugin_messages = [];
    await ctx.logger.exporter({ export(message) {
      const text = message.args.filter(arg => typeof arg === "string").join(" ");
      if (text.startsWith("auto-review") && report.plugin_messages.length < 20) report.plugin_messages.push(text);
    } });
    ctx.on("agent/created", ({ agent }) => { report.created_agents.push({ id: agent.id,
      provider: agent.options.provider, model: agent.options.model, parent: agent.session.header.parentSessionId ?? null }); });
    const canary = "SYNTHETIC_OUTSIDE_HOME_SENTINEL";
    fs.writeFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, canary);
    class Fake extends LlmAdapter {
      providerRetryPolicy() { return { mode: "normal", maxRetries: 0 }; }
      async resolveModel(provider, model) { return { provider, id: model, name: model, inputModalities: ["text"], context: { contextWindow: 262144 }, defaultMaxTokens: 4096 }; }
      async *stream(options) {
        report.model_calls++; assert(report.model_calls <= 80, "MODEL_BUDGET");
        const mode = options.model, n = steps.get(options.sessionId) ?? 0;
        steps.set(options.sessionId, n + 1); calls.set(mode, (calls.get(mode) ?? 0) + 1);
        const structured = options.tools?.find(tool => tool.parameters?.properties?.decision && tool.parameters?.properties?.reason);
        catalogs.push({ model: mode, names: options.tools?.map(tool => tool.name) ?? [] });
        assert(structured && options.tools.every(tool => ["rotom_review_fact", structured.name].includes(tool.name)), "REVIEWER_TOOL_SCOPE");
        assert(!JSON.stringify(options.messages).includes(canary), "SENTINEL_LEAK");
        if (["sdk401", "sdk429", "no-carrier"].includes(mode)) {
          yield { type: "finish", reason: { kind: "error", failure: { code: mode === "sdk401" ? "AUTHENTICATION_FAILED" : "RATE_LIMIT", message: mode, retryable: false } } }; return;
        }
        if (n === 1 && ["timeout", "cancel-late", "off-late", "unload-late"].includes(mode)) { ready.add(mode); await sleep(mode === "timeout" ? 1500 : 400); }
        let name, args;
        if (n === 0 && mode.startsWith("attack-")) {
          name = mode === "attack-read" ? "read" : "bash";
          args = name === "read" ? { file_path: process.env.AGENTCFG_SMOKE_OUTSIDE } : { command: "cat " + process.env.AGENTCFG_SMOKE_OUTSIDE };
        } else if (n === 0) { name = "rotom_review_fact"; args = {}; }
        else if (mode.startsWith("attack-") || (mode === "malformed" && n > 1)) { yield { type: "finish", reason: { kind: "stop" } }; return; }
        else { name = structured.name; args = { decision: mode.startsWith("deny") ? "deny" : mode === "malformed" ? "invalid" : "allow",
          reason: "deterministic fixture verdict", riskLevel: mode === "high" ? "high" : "low" }; }
        const block = { type: "tool-call", id: "fixture-" + randomUUID(), name, arguments: JSON.stringify(args) };
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "tool-call-delta", index: 0, id: block.id, name, argumentsDelta: block.arguments };
        yield { type: "block-end", index: 0, block };
        yield { type: "finish", reason: { kind: "tool-calls" } }; save();
      }
    }
    ctx.get("llm").registerAdapter(["rotom-review-fixture"], new Fake());
    const tools = ctx.get("tools");
    tools.register({ name: "rotom_review_fact", description: "Readonly constant, no filesystem/network/process access",
      parameters: { type: "object", properties: {}, additionalProperties: false },
      output: { schema: { type: "string" }, render: (_args, value) => [{ type: "text", text: value }] }, execute: async () => "CONSTANT_FACT" });
    tools.register({ name: "rotom_review_probe", description: "Memory-only execution counter, no side effects",
      parameters: { type: "object", properties: { action: { type: "string" } }, required: ["action"] },
      output: { schema: { type: "integer" }, render: (_args, value) => [{ type: "text", text: String(value) }] },
      execute: async args => { counts.set(args.action, (counts.get(args.action) ?? 0) + 1); return counts.get(args.action); } });
    ctx.on("tools/pre-execute", (exec, next) => {
      if (exec.name !== "rotom_review_probe") return next();
      return exec.arguments.action === "hard-deny"
        ? { kind: "deny", reason: "fixture deterministic deny" }
        : { kind: "ask", reason: exec.arguments.action };
    }, { prepend: true });
    ctx.on("approval/request", (request, next) => {
      const events = request.agent.session.snapshotEvents();
      report.requests.push({ actor: request.agent.id, callId: request.callId, tool: request.toolName,
        correlated: perry.correlateApprovalId(events, request.toolName, request.callId) ?? null,
        events: events.map(e => e.type), runtime_present: !!request.agent.ctx.get("autoReviewRuntime") }); return next();
    }, { prepend: true });
    const refusals = [];
    ctx.on("tools/result", (exec, result) => { if (["read", "bash"].includes(exec.name)) refusals.push({ tool: exec.name, isError: !!result.isError }); });
    const config = { enableByDefault: true, toolsPolicy: { default: "human", overrides: { rotom_review_probe: "ai" } },
      riskRules: [{ pattern: "^human$", field: "reason", policy: "human" }], reviewerProvider: "spawn", reviewerTools: ["rotom_review_fact"],
      reviewerTimeoutMs: 1000, maxReviewsPerTurn: 3, maxFailuresPerTurn: 2, verdictCacheTtlMs: 0,
      contextBudget: { turns: 0, maxChars: 2000 }, fallbackPolicy: "delegate", riskPolicy: { maxAutoAllow: "low", onHighRisk: "delegate" } };
    const mounted = await ctx.plugin(perry, config);
    const runtimeService = ctx.get("autoReviewRuntime");
    report.public_diagnostics = { mounted: !!runtimeService,
      config: runtimeService ? { enableByDefault: runtimeService.config.enableByDefault,
        toolsPolicy: runtimeService.config.toolsPolicy, reviewerProvider: runtimeService.config.reviewerProvider,
        reviewerModel: runtimeService.config.reviewerModel ?? null } : null,
      spawn_capabilities: ctx.get("subagents").getProvider("spawn")?.capabilities ?? null,
      public_subagents_start: typeof ctx.get("subagents").start,
      public_subagents_startActivation: typeof ctx.get("subagents").startActivation };
    save();
    assert(runtimeService, "PLUGIN_NOT_MOUNTED");
    ctx.on("approval/request", (request, next) => {
      if (request.toolName !== "rotom_review_probe") return next();
      const mode = request.reason; humans.set(mode, (humans.get(mode) ?? 0) + 1);
      if (mode === "no-carrier") return next();
      return mode === "human" ? "allowed-once" : "rejected";
    });
    const handles = [], actors = new Map();
    const create = async mode => {
      const handle = await ctx.get("agents").create({ sessionId: randomUUID(), meta: { cwd: process.cwd() },
        agentOptions: { provider: "rotom-review-fixture", model: mode } });
      handle.agent.session.append("turn/start", { turn: 1 }); handles.push(handle); actors.set(mode, handle.agent); return handle.agent;
    };
    const execute = (agent, mode, signal = AbortSignal.timeout(3000), callId = "call-" + randomUUID()) =>
      deadline(agent.ctx.get("tools").execute({ agent, name: "rotom_review_probe", arguments: { action: mode }, signal, callId }));
    const check = (mode, expected, result, before = 0) => {
      const count = counts.get(mode) ?? 0, reviewerCalls = (calls.get(mode) ?? 0) - before;
      const needsReviewer = !["human", "never", "hard-deny", "unloaded", "commands"].includes(mode);
      const exercised = !needsReviewer || reviewerCalls > 0;
      report.cases[mode] = { actor: actors.get(mode)?.id, actor_route: { provider: actors.get(mode)?.options.provider, model: actors.get(mode)?.options.model },
        executed: count, expected, isError: !!result?.isError, reviewer_calls: reviewerCalls,
        human_calls: humans.get(mode) ?? 0, result: exercised && count === expected ? "PASS" : "FAIL",
        ...!exercised ? { failure_code: "REVIEWER_NOT_EXERCISED" } : {},
        fixture_result: result?.content ?? result?.blocks ?? null };
      save();
    };
    const aiAvailable = typeof ctx.get("subagents").start === "function";
    if (!aiAvailable) {
      report.ai_matrix = { status: "BLOCKED", reason: "PERRY_SUBAGENTS_START_API_MISSING",
        not_run: ["deny", "high", "malformed", "sdk401", "sdk429", "timeout", "no-carrier", "attack-read", "attack-bash", "cancel-late", "off-late", "concurrent"] };
    }
    for (const mode of aiAvailable
      ? ["allow", "deny", "high", "malformed", "sdk401", "sdk429", "timeout", "human", "no-carrier", "attack-read", "attack-bash"]
      : ["allow", "human"]) {
      stage("approval." + mode); const agent = await create(mode);
      const result = await execute(agent, mode, mode === "no-carrier" ? AbortSignal.timeout(500) : undefined);
      check(mode, ["allow", "human"].includes(mode) ? 1 : 0, result);
      if (mode === "allow") {
        report.diagnostic_status = await deadline(ctx.get("commands").execute(agent, "/auto-review status", [], new AbortController().signal));
        save();
      }
    }
    for (const mode of aiAvailable ? ["cancel-late", "off-late"] : []) {
      stage("approval." + mode); const agent = await create(mode), controller = new AbortController();
      const pending = execute(agent, mode, controller.signal); await wait(() => ready.has(mode));
      if (mode === "cancel-late") controller.abort();
      else await deadline(ctx.get("commands").execute(agent, "/auto-review off", [], new AbortController().signal));
      const result = await pending; await sleep(450); check(mode, 0, result);
    }
    stage("approval.never"); const never = await create("never"), prior = report.model_calls;
    never.ctx.get("approval").setPolicy(never, "never"); check("never", 0, await execute(never, "never"));
    assert.equal(report.model_calls, prior, "NEVER_REVIEWED");
    stage("approval.hard-deny"); const guarded = await create("hard-deny"), priorGuard = report.model_calls;
    check("hard-deny", 0, await execute(guarded, "hard-deny"));
    assert.equal(report.model_calls, priorGuard, "DENY_REVIEWED");
    assert.equal(humans.get("hard-deny") ?? 0, 0, "DENY_DELEGATED");
    if (aiAvailable) { report.concurrent = "RUNNING"; stage("approval.concurrent"); const a = await create("concurrent-allow"), b = await create("deny-concurrent"), same = "same-" + randomUUID();
    // 独立 actor 的同 callId，不同参数；后一模型确定性拒绝。
    const originalMode = "deny-concurrent";
    const result = await Promise.all([execute(a, "concurrent-allow", undefined, same), execute(b, originalMode, undefined, same)]);
    check("concurrent-allow", 1, result[0]); check(originalMode, 0, result[1]); report.concurrent = "PASS"; }
    if (aiAvailable) {
      stage("failure.budget"); const errors = actors.get("sdk401"), beforeBudget = calls.get("sdk401");
      await execute(errors, "sdk401"); const afterSecond = calls.get("sdk401");
      await execute(errors, "sdk401");
      report.checks.failure_budget = afterSecond === beforeBudget + 1 && calls.get("sdk401") === afterSecond && (counts.get("sdk401") ?? 0) === 0 ? "PASS" : "FAIL";
    }
    stage("commands"); const commandActor = await create("commands");
    report.commands = [];
    for (const verb of ["off", "status", "on", "status"]) {
      const response = await deadline(ctx.get("commands").execute(commandActor, "/auto-review " + verb, [], new AbortController().signal));
      report.commands.push({ verb, kind: response?.result?.kind ?? "missing", text: response?.result?.text ?? "" }); assert.equal(response?.result?.kind, "success", "COMMAND_FAILED");
    }
    stage("commands.off-new-turn");
    await ctx.get("commands").execute(commandActor, "/auto-review off", [], new AbortController().signal);
    const sameTurn = await ctx.get("commands").execute(commandActor, "/auto-review status", [], new AbortController().signal);
    commandActor.session.append("turn/end", { turn: 1, reason: { kind: "completed" } });
    commandActor.session.append("turn/start", { turn: 2 });
    const nextTurn = await ctx.get("commands").execute(commandActor, "/auto-review status", [], new AbortController().signal);
    report.off_new_turn = { before: sameTurn.result.text.split("\n")[0], after: nextTurn.result.text.split("\n")[0] };
    report.checks.off_new_turn = nextTurn.result.text.includes("is OFF") ? "PASS" : "FAIL";
    report.unload = "RUNNING"; stage("plugin.unload");
    if (aiAvailable) {
      const late = await create("unload-late"), pending = execute(late, "unload-late");
      await wait(() => ready.has("unload-late")); await mounted.dispose();
      check("unload-late", 0, await pending);
    } else await mounted.dispose();
    const unloaded = await create("unloaded"); const beforeUnload = report.model_calls;
    check("unloaded", 0, await execute(unloaded, "unloaded")); assert.equal(report.model_calls, beforeUnload, "UNLOAD_REVIEWED");
    report.checks.unload = "PASS"; report.unload = "PASS"; report.catalogs = catalogs; report.tool_refusals = refusals;
    report.checks.reviewer_tool_scope = catalogs.length ? catalogs.every(row => row.names.length === 2) ? "PASS" : "FAIL" : "NOT RUN";
    assert.equal(fs.readFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, "utf8"), canary, "SENTINEL_CHANGED");
    report.audit = {}; report.sessions = [];
    for (const handle of handles) {
      handle.agent.session.append("turn/end", { turn: handle.agent.id === commandActor.id ? 2 : 1, reason: { kind: "completed" } });
      report.sessions.push(handle.agent.session.id); report.audit[handle.agent.session.id] = audit(handle.agent.session.snapshotEvents());
    }
    await ctx.get("sessionPersistence").flush();
    for (const handle of handles) await handle.dispose();
    stage("sandbox"); report.sandbox = {};
    const outside = process.env.AGENTCFG_SMOKE_OUTSIDE, link = path.join(process.cwd(), "link"), readonly = path.join(process.cwd(), "readonly");
    fs.writeFileSync(readonly, "ordinary write baseline"); fs.symlinkSync(outside, link);
    for (const [label, mode, target, allowed] of [["workspace", "workspace-write", path.join(process.cwd(), "allowed"), true],
      ["outside", "workspace-write", outside, false], ["symlink", "workspace-write", link, false], ["readonly", "read-only", readonly, false]]) {
      const code = "try{require('node:fs').writeFileSync(process.argv[1],'write');process.exit(0)}catch(e){process.stderr.write(e.code);process.exit(7)}";
      const wrapped = await ctx.get("sandbox").confine([process.execPath, "-e", code, target], { mode, workspaceRoot: process.cwd() }, AbortSignal.timeout(3000));
      const child = spawnSync(wrapped.argv[0], wrapped.argv.slice(1), { cwd: process.cwd(), env: process.env, encoding: "utf8", timeout: 5000 });
      assert.equal(wrapped.enforcement, "full"); assert(!child.error && !child.signal);
      assert.equal(child.status, allowed ? 0 : 7); if (!allowed) assert(["EROFS", "EACCES"].includes(child.stderr.trim()));
      report.sandbox[label] = { exit: child.status, enforcement: wrapped.enforcement, code: allowed ? null : child.stderr.trim() };
      assert.equal(fs.readFileSync(outside, "utf8"), canary); save();
    }
    report.plugin_messages = ctx.logger.buffer.map(message => message.args.filter(arg => typeof arg === "string").join(" "))
      .filter(text => text.startsWith("auto-review")).slice(-20);
    report.functional = Object.values(report.cases).every(item => item.result === "PASS") && Object.values(report.checks).every(value => ["PASS", "NOT RUN"].includes(value)) ? "PASS" : "FAIL";
    report.checks.sandbox = "PASS"; report.native_complete = true; report.release_gate = "BLOCKED";
    report.stage = "native.complete"; save(); await boot.shutdown.shutdown(0);
  }
} catch (error) {
  report.safe_error_code = /^[A-Z_]{1,60}$/.test(error?.code ?? "") ? error.code : error?.name === "AssertionError" ? "ASSERTION_FAILED" : "PUBLIC_API_OR_PROFILE_FAILED";
  report.harness_location = error?.stack?.match(/smoke-dsh-auto-review.mjs:[0-9]+/)?.[0] ?? "unknown";
  report.functional = "FAIL"; report.release_gate = "FAIL"; report.error = "NATIVE_ASSERTION_OR_API_FAILURE";
  report.error_location = report.stage; save();
  if (boot) await boot.shutdown.shutdown(1);
  else process.exitCode = 1;
}
