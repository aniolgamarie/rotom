// 显式正式配方功能验收；人工构造 ask，最终执行原生 write，不声称 OS 边界。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { runSandboxReviewCases } from "./dsh-sandbox-review-cases.mjs";

const runtime = process.argv[2], root = process.env.AGENTCFG_SMOKE_ROOT;
assert(runtime && path.isAbsolute(runtime) && root);
assert(["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"].every(key => process.env[key]?.startsWith(root + "/")));
assert(process.cwd().startsWith(root + "/"));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)));
const smokeMode = process.env.AGENTCFG_SMOKE_MODE;
const manual = smokeMode === "manual";
const diagnosticOnly = process.env.AGENTCFG_SMOKE_DIAGNOSTIC_ALLOW_ONLY === "1";
const report = { nonce: process.env.AGENTCFG_SMOKE_NONCE, functional: "FAIL", mode: smokeMode,
  parent_driver: "public-followup/model-tool-call", approval_reviewer_path: "inline-tool-less",
  cases: {}, reviewer_catalogs: [], created_agents: [], native_write_results: [], model_calls: 0,
  known_lifecycle_gate: "NOT REVALIDATED (historical 0.12.17 failures retained)", forced_ask: "synthetic public tools/pre-execute handler; native workspace writes normally bypass review",
  os_sandbox_proven: false, accounts: "NOT RUN", http_model: "NOT RUN" };
const save = () => fs.writeFileSync(process.env.AGENTCFG_SMOKE_RESULT, JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
const stage = name => { report.stage = name; save(); };
const bounded = async (work, ms = 15000) => {
  let timer;
  try { return await Promise.race([work, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("FIXTURE_TIMEOUT")), ms); })]); }
  finally { clearTimeout(timer); }
};
let boot;
try {
  stage("boot.formal-bundles");
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  boot = await bounded(runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_SMOKE_PATCH, process.env.AGENTCFG_SMOKE_HEADLESS, process.env.AGENTCFG_SMOKE_PRESET], args: [],
    packageManager: { command: "/bin/false", args: [], env: {} } }), 30000);
  const ctx = boot.ctx;
  const presets = ctx.get("agentPresets");
  assert(presets, "PUBLIC_PRESET_REGISTRY_MISSING");
  report.preset = await presets.resolve("standard");
  report.reviewer_preset = await presets.resolve("rotom-auto-review");
  const service = ctx.get("autoReviewRuntime");
  const expected = JSON.parse(fs.readFileSync(process.env.AGENTCFG_SMOKE_EXPECTED, "utf8"));
  assert.equal(!!service, !manual, "FORMAL_PLUGIN_TOGGLE");
  if (service) {
    for (const [field, value] of Object.entries(expected)) {
      let actual = service.config[field];
      if (field === "riskRules") {
        actual = actual.map(({ field, pattern, policy }) => ({ field, pattern, policy }));
      }
      assert.deepEqual(actual, value, "FORMAL_FIELD_" + field);
    }
    assert.equal(service.config.reviewerModel, undefined);
    report.formal_config = Object.fromEntries(Object.keys(expected).map(key => [key, service.config[key]]));
  }
  const { LlmAdapter } = await moduleAt("@deepseek-ai/dsh-llm");
  const calls = new Map(), human = new Map(), successfulWrites = new Map(), handles = [], parentStates = new Map(), pendingResults = new Map();
  report.parent_model_calls = 0;
  report.timeout_observations = [];
  report.approval_requests = [];
  ctx.on("approval/request", (request, next) => {
    report.approval_requests.push({ tool_name: request.toolName, has_agent: !!request.agent,
      model_tag: request.agent?.options.model, call_id_present: typeof request.callId === "string",
      reason_kind: request.reason === "synthetic formal review request" ? "synthetic-file-ask"
        : /^escalate sandbox to /.test(request.reason ?? "") ? "sandbox-escalation" : "other" });
    return next();
  }, { prepend: true });
  const statusSummary = async agent => {
    const command = await ctx.get("commands").execute(agent, "/auto-review status", [], new AbortController().signal);
    const text = command.result?.text ?? "";
    return { result_kind: command.result?.kind, on: /Auto-review is ON/.test(text),
      verdict_budget: text.match(/AI verdicts this turn: ([0-9]+\/[0-9]+)/)?.[1] ?? null,
      failure_budget: text.match(/Reviewer failures this turn: ([0-9]+\/[0-9]+)/)?.[1] ?? null,
      fallbacks: text.match(/([0-9]+) fallbacks/)?.[1] ?? null,
      audit_disabled: text.includes("Session-log audit is disabled") };
  };
  const sentinel = fs.readFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, "utf8");
  class Fake extends LlmAdapter {
    providerRetryPolicy() { return { mode: "normal", maxRetries: 0 }; }
    async resolveModel(provider, model) { return { provider, id: model, name: model, inputModalities: ["text"], context: { contextWindow: 262144 }, defaultMaxTokens: 4096 }; }
    async *stream(options) {
      const modelTag = options.model;
      const mode = modelTag.replace(/^sandbox-/, "");
      const names = options.tools?.map(tool => tool.name) ?? [];
      const carrier = options.tools?.find(tool => tool.parameters?.properties?.decision && tool.parameters?.properties?.reason);
      if (carrier) {
        assert.equal(mode, "activation-probe", "CONDITIONAL_PRESET_PROBE_ONLY");
        report.reviewer_catalogs.push({ mode: modelTag, names, path: "independent-preset-probe" });
        assert.deepEqual([...names].sort(), ["rotom_review_context", "structured_output"].sort());
        const argumentsText = JSON.stringify({ decision: "allow", reason: "independent diagnostic", riskLevel: "low" });
        const id = "probe-" + randomUUID();
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "block-end", index: 0, block: { type: "tool-call", id, name: carrier.name, arguments: argumentsText } };
        yield { type: "finish", reason: { kind: "tool-calls" } };
        return;
      }
      if (names.length) {
        report.parent_model_calls++;
        assert(report.parent_model_calls < 150, "PARENT_MODEL_BUDGET");
        const state = parentStates.get(options.sessionId);
        assert(state, "PARENT_STREAM_STATE_MISSING");
        let abort;
        const planned = await new Promise(resolve => {
          abort = () => resolve(null);
          options.signal.addEventListener("abort", abort, { once: true });
          state.gate = resolve;
          for (const ready of state.waiters.splice(0)) ready();
          if (options.signal.aborted) abort();
        });
        options.signal.removeEventListener("abort", abort);
        state.gate = null;
        if (!planned) {
          yield { type: "finish", reason: { kind: "aborted" } };
          return;
        }
        const argumentsText = JSON.stringify(planned.arguments);
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "tool-call-delta", index: 0, id: planned.callId, name: planned.name, argumentsDelta: argumentsText };
        yield { type: "block-end", index: 0, block: { type: "tool-call", id: planned.callId, name: planned.name, arguments: argumentsText } };
        yield { type: "finish", reason: { kind: "tool-calls" } };
        return;
      }
      report.model_calls++;
      assert(report.model_calls < 60, "REVIEWER_MODEL_BUDGET");
      assert.equal(options.sessionId, undefined, "INLINE_REVIEWER_HAS_NO_SESSION");
      assert.equal(options.temperature, 0, "INLINE_REVIEWER_TEMPERATURE");
      assert(options.system.includes("read-only safety reviewer"), "INLINE_REVIEWER_SYSTEM");
      calls.set(modelTag, (calls.get(modelTag) ?? 0) + 1);
      report.reviewer_catalogs.push({ mode: modelTag, names, path: "inline-tool-less" });
      assert(!JSON.stringify(options.messages).includes(sentinel), "SENTINEL_LEAK");
      if (mode === "error") {
        yield { type: "finish", reason: { kind: "error", failure: { code: "AUTHENTICATION_FAILED", message: "synthetic SDK failure", retryable: false } } };
        return;
      }
      if (mode === "timeout") {
        const started = Date.now();
        await new Promise(resolve => {
          if (options.signal.aborted) resolve();
          else options.signal.addEventListener("abort", resolve, { once: true });
        });
        report.timeout_observations.push({ mode: modelTag, abort_observed: options.signal.aborted, elapsed_ms: Date.now() - started });
        yield { type: "finish", reason: { kind: "aborted" } };
        return;
      }
      if (mode === "attack") {
        const id = "attack-" + randomUUID();
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "block-end", index: 0, block: { type: "tool-call", id, name: "read", arguments: JSON.stringify({ file_path: process.env.AGENTCFG_SMOKE_OUTSIDE }) } };
        yield { type: "finish", reason: { kind: "tool-calls" } };
        return;
      }
      const text = JSON.stringify({ decision: mode === "deny" ? "deny" : "allow", reason: "deterministic fixture verdict", riskLevel: mode === "high" ? "high" : "low" });
      yield { type: "block-start", index: 0, blockType: "text" };
      yield { type: "text-delta", index: 0, text };
      yield { type: "block-end", index: 0, block: { type: "text", text } };
      yield { type: "finish", reason: { kind: "stop" } };
      save();
    }
  }
  ctx.get("llm").registerAdapter(["rotom-formal-fixture"], new Fake());
  ctx.on("agent/created", ({ agent }) => {
    report.created_agents.push({ id: agent.id, provider: agent.options.provider, model: agent.options.model,
      parent: agent.session.header.parentSessionId ?? null, delegationDepth: agent.session.header.delegationDepth ?? null });
  });
  ctx.on("tools/result", (exec, result) => {
    pendingResults.get(exec.callId)?.(result);
    pendingResults.delete(exec.callId);
    if (exec.name === "write") {
      report.native_write_results.push({ callId: exec.callId, target: path.basename(exec.arguments.file_path), isError: !!result.isError });
      if (!result.isError) successfulWrites.set(exec.arguments.file_path, (successfulWrites.get(exec.arguments.file_path) ?? 0) + 1);
    }
    if (exec.name === "read" && exec.arguments.file_path === process.env.AGENTCFG_SMOKE_OUTSIDE) {
      report.attack_read = { isError: !!result.isError };
      assert(result.isError, "REVIEWER_READ_EXECUTED");
      assert(!JSON.stringify(result).includes(sentinel), "ATTACK_RESULT_LEAK");
    }
  });
  // Perry 已从正式 bundle 挂载；回答器排在后面，仅接收其 delegate。
  ctx.on("approval/request", (request, next) => {
    const mode = request.agent.options.model;
    human.set(mode, (human.get(mode) ?? 0) + 1);
    if (mode === "error" || mode === "sandbox-error") throw new Error("synthetic human fallback failure");
    if (manual && mode === "manual") return "allowed-once";
    return "rejected";
  });
  const waitForParent = async agent => {
    const state = parentStates.get(agent.session.id);
    if (!state.gate) await bounded(new Promise(resolve => state.waiters.push(resolve)));
    assert(state.gate, "PARENT_STREAM_NOT_READY");
    assert(agent.session.snapshotEvents().some(event => event.type === "request/header"), "REAL_PARENT_HEADER_MISSING");
    return state;
  };
  const executeTool = async (agent, request) => {
    const state = await waitForParent(agent);
    const result = new Promise(resolve => pendingResults.set(request.callId, resolve));
    const dispatch = state.gate;
    state.gate = null;
    dispatch(request);
    const value = await bounded(result, 20000);
    await waitForParent(agent);
    return value;
  };
  const create = async mode => {
    const handle = await ctx.get("agents").create({ sessionId: randomUUID(), meta: { cwd: process.cwd() },
      agentOptions: { provider: "rotom-formal-fixture", model: mode }, setup: async agentCtx => { await presets.mount(agentCtx, "standard"); } });
    handles.push(handle);
    const agent = handle.agent;
    parentStates.set(agent.session.id, { gate: null, waiters: [] });
    const tools = agent.ctx.get("tools"), names = tools.schemas(agent).map(tool => tool.name);
    assert(tools.get("write", agent), "NATIVE_WRITE_NOT_IN_PRESET");
    assert(names.some(name => /subagent|task/.test(name)), "PARENT_DELEGATION_MISSING");
    report.parent_catalog = names;
    report.approval_policy = agent.ctx.get("approval").effectivePolicy(agent.session);
    assert.equal(report.approval_policy, "ask");
    assert.equal(agent.ctx.get("sandboxPolicy").resolve({ session: agent.session }).mode, "workspace-write");
    // 只对标记请求构造 ask；不改变原生 write 定义。
    agent.ctx.on("tools/pre-execute", (exec, next) => exec.name === "write" && path.basename(exec.arguments.file_path).startsWith("ask-")
      ? { kind: "ask", reason: "synthetic formal review request" } : next(), { prepend: true });
    agent.followup({ id: randomUUID(), role: "user", content: [{ type: "text", text: "Authorized isolated fixture turn; execute only the next deterministic test call." }], source: { kind: "user" } });
    await waitForParent(agent);
    return agent;
  };
  const activationProbe = async parent => {
    stage("diagnostic.public-activation");
    const beforeAgents = report.created_agents.length, beforeCatalogs = report.reviewer_catalogs.length;
    const probe = { independent_of_approval: true, parent_action_executed: false, provider: "spawn",
      preset: "rotom-auto-review", started: false };
    report.activation_probe = probe;
    let activation;
    try {
      activation = await bounded(ctx.get("subagents").startActivation({ provider: "spawn",
        label: "independent public activation diagnostic", delivery: "caller", signal: AbortSignal.timeout(10000),
        request: { parent, agentPreset: "rotom-auto-review", maxDepth: (parent.session.header.delegationDepth ?? 0) + 1,
          agentOptions: { model: "activation-probe" },
          prompt: [{ type: "text", text: "Return a synthetic allow/low structured verdict; no parent action is authorized by this diagnostic." }],
          outputSchema: { type: "object", properties: { decision: { type: "string", enum: ["allow", "deny"] },
            reason: { type: "string" }, riskLevel: { type: "string", enum: ["low", "medium", "high"] } },
            required: ["decision", "reason"] } } }), 15000);
      probe.started = true;
      const result = await bounded(activation.result, 15000);
      probe.stop_reason = result.stopReason;
      probe.structured_verdict = result.structured ? { decision: result.structured.decision, riskLevel: result.structured.riskLevel } : null;
    } catch (error) {
      probe.error = { name: error.name, code: typeof error.code === "string" ? error.code : null,
        message: String(error.message).replaceAll(runtime, "<runtime>").replaceAll(root, "<fixture>").slice(0, 1000) };
    } finally {
      if (activation) {
        try { await activation.dispose(); }
        catch (error) { probe.dispose_error = { name: error.name }; }
      }
      probe.created_agents = report.created_agents.length - beforeAgents;
      probe.catalogs = report.reviewer_catalogs.slice(beforeCatalogs);
      save();
    }
  };
  const execute = async (agent, label, allowed, expectReview, expectHuman) => {
    stage("write." + label);
    const target = path.join(process.cwd(), "ask-" + label + ".txt"), mode = agent.options.model;
    const aiBefore = calls.get(mode) ?? 0, humanBefore = human.get(mode) ?? 0;
    const callId = "write-" + label + "-" + randomUUID();
    const beforeStatus = manual ? null : await statusSummary(agent);
    const executionTimeout = mode === "timeout" ? expected.reviewerTimeoutMs + 15000 : 10000;
    const result = await bounded(executeTool(agent, { name: "write", arguments: { file_path: target, content: "fixture " + label },
      signal: AbortSignal.timeout(executionTimeout), callId }), executionTimeout + 1000);
    const count = successfulWrites.get(target) ?? 0, ai = (calls.get(mode) ?? 0) - aiBefore, humans = (human.get(mode) ?? 0) - humanBefore;
    report.cases[label] = { native_success_results: count, file_exists: fs.existsSync(target), ai_calls: ai, human_calls: humans, isError: !!result.isError, dispatch: "parent-model-tool-call" };
    const events = agent.session.snapshotEvents();
    const asked = events.filter(event => event.type === "approval/asked" && event.data.callId === callId);
    report.cases[label].diagnostics = { before_status: beforeStatus, after_status: manual ? null : await statusSummary(agent),
      event_type_counts: events.reduce((counts, event) => { counts[event.type] = (counts[event.type] ?? 0) + 1; return counts; }, {}),
      asked_call_id_matched: asked.length === 1,
      decided_matches_asked: asked.length === 1 && events.some(event => event.type === "approval/decided" && event.data.id === asked[0].data.id) };
    save();
    if (diagnosticOnly && label === "allow") {
      await activationProbe(agent);
      stage("write." + label);
    }
    assert.equal(count, allowed ? 1 : 0, "WRITE_COUNT_" + label);
    assert.equal(fs.existsSync(target), allowed, "FILE_OUTCOME_" + label);
    if (allowed) assert.equal(fs.readFileSync(target, "utf8"), "fixture " + label);
    assert.equal(ai > 0, expectReview, "REVIEW_ROUTE_" + label);
    assert.equal(humans > 0, expectHuman, "HUMAN_ROUTE_" + label);
    save();
  };
  const normal = await create(manual ? "manual" : "allow");
  const commandNames = ctx.get("commands").list(normal).map(command => command.name);
  assert.equal(commandNames.includes("auto-review"), !manual);
  report.auto_review_command = commandNames.includes("auto-review");
  if (!manual) {
    if (smokeMode === "timeout") {
      assert.equal(expected.reviewerTimeoutMs, 1000, "FORMAL_TIMEOUT_FIXTURE_OVERRIDE");
      await execute(await create("timeout"), "timeout", false, true, true);
      const timeout = report.timeout_observations.find(value => value.mode === "timeout");
      assert(timeout?.abort_observed && timeout.elapsed_ms > 0 && timeout.elapsed_ms < 10000, "FINITE_REVIEW_CANCELLATION");
    } else {
      assert.equal(expected.reviewerTimeoutMs, 90000, "FORMAL_DEFAULT_TIMEOUT");
      report.command_status = await ctx.get("commands").execute(normal, "/auto-review status", [], new AbortController().signal);
      await execute(normal, "allow", true, true, false);
      if (!diagnosticOnly) {
        for (const [mode, humanExpected] of [["deny", false], ["high", true], ["error", true], ["attack", true]]) {
          await execute(await create(mode), mode, false, true, humanExpected);
        }
        const reviewerChildren = report.created_agents.filter(agent => agent.parent !== null).length;
        assert.equal(reviewerChildren, 0, "INLINE_REVIEW_MUST_NOT_CREATE_CHILDREN");
        report.reviewer_boundary = { path: "inline-tool-less", tools_exposed: [], child_agents_created: reviewerChildren, result: "PASS" };
        const budget = await create("budget");
        for (let index = 1; index <= 3; index++) await execute(budget, "budget-" + index, true, true, false);
        await execute(budget, "budget-4", false, false, true);
        const errors = await create("error");
        await execute(errors, "error-first", false, true, true);
        await execute(errors, "error-budget", false, false, true);
        const unknown = await create("unknown");
        unknown.ctx.get("tools").register({ name: "rotom_formal_unknown", description: "constant fixture for unknown policy mapping",
          parameters: { type: "object", properties: {}, additionalProperties: false },
          output: { schema: { type: "string" }, render: (_args, value) => [{ type: "text", text: value }] }, execute: async () => { throw new Error("UNKNOWN_TOOL_EXECUTED"); } });
        unknown.ctx.on("tools/pre-execute", (exec, next) => exec.name === "rotom_formal_unknown" ? { kind: "ask", reason: "escalate sandbox to workspace-write: synthetic unknown request" } : next(), { prepend: true });
        const unknownResult = await executeTool(unknown, { name: "rotom_formal_unknown", arguments: {}, signal: AbortSignal.timeout(2000), callId: "unknown" });
        assert(unknownResult.isError && (human.get("unknown") ?? 0) === 1 && (calls.get("unknown") ?? 0) === 0);
        report.cases.unknown = { human_calls: human.get("unknown"), ai_calls: 0, isError: true, spoofed_sandbox_reason: true };
        const never = await create("never");
        never.ctx.get("approval").setPolicy(never, "never");
        await execute(never, "never", false, false, false);
        const before = report.model_calls;
        const nativeTarget = path.join(process.cwd(), "native-normal.txt");
        const native = await executeTool(normal, { name: "write", arguments: { file_path: nativeTarget, content: "ordinary workspace write" },
          signal: AbortSignal.timeout(2000), callId: "native-normal" });
        assert(!native.isError && fs.readFileSync(nativeTarget, "utf8") === "ordinary workspace write");
        assert.equal(report.model_calls, before);
        report.cases.native_normal = { native_success_results: successfulWrites.get(nativeTarget), ai_calls: 0 };
        assert.equal(fs.readFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, "utf8"), sentinel);
        assert.equal(report.attack_read, undefined, "INLINE_ATTACK_MUST_NOT_EXECUTE_READ");
      }
    }
    if (!diagnosticOnly) await runSandboxReviewCases({ ctx, create, calls, human, report, bounded, stage, executeTool });
  } else {
    await execute(normal, "manual", true, false, true);
    assert.equal(report.model_calls, 0);
  }
  for (const handle of handles) await handle.dispose();
  report.functional = "PASS";
  report.stage = "complete";
  save();
  await boot.shutdown.shutdown(0);
} catch (error) {
  report.functional = "FAIL";
  report.error = { name: error.name, message: String(error.message).slice(0, 300), location: report.stage };
  save();
  console.error(report.error);
  try { await boot?.shutdown.shutdown(1); } catch {}
  process.exitCode = 1;
}
