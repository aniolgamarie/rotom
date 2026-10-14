// 显式正式配方功能验收；人工构造 ask，最终执行原生 write，不声称 OS 边界。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const runtime = process.argv[2], root = process.env.AGENTCFG_SMOKE_ROOT;
assert(runtime && path.isAbsolute(runtime) && root);
assert(["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"].every(key => process.env[key]?.startsWith(root + "/")));
assert(process.cwd().startsWith(root + "/"));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)));
const manual = process.env.AGENTCFG_SMOKE_MODE === "manual";
const report = { nonce: process.env.AGENTCFG_SMOKE_NONCE, functional: "FAIL", mode: manual ? "manual" : "formal",
  cases: {}, reviewer_catalogs: [], created_agents: [], native_write_results: [], model_calls: 0,
  known_lifecycle_gate: "FAIL (accepted)", forced_ask: "synthetic public tools/pre-execute handler; native workspace writes normally bypass review",
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
  const service = ctx.get("autoReviewRuntime");
  const expected = JSON.parse(fs.readFileSync(process.env.AGENTCFG_SMOKE_EXPECTED, "utf8"));
  assert.equal(!!service, !manual, "FORMAL_PLUGIN_TOGGLE");
  if (service) {
    for (const [field, value] of Object.entries(expected)) assert.deepEqual(service.config[field], value, "FORMAL_FIELD_" + field);
    assert.equal(service.config.reviewerModel, undefined);
    report.formal_config = Object.fromEntries(Object.keys(expected).map(key => [key, service.config[key]]));
  }
  const { LlmAdapter } = await moduleAt("@deepseek-ai/dsh-llm");
  const calls = new Map(), steps = new Map(), human = new Map(), successfulWrites = new Map(), handles = [], agentsBySession = new Map();
  const sentinel = fs.readFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, "utf8");
  class Fake extends LlmAdapter {
    providerRetryPolicy() { return { mode: "normal", maxRetries: 0 }; }
    async resolveModel(provider, model) { return { provider, id: model, name: model, inputModalities: ["text"], context: { contextWindow: 262144 }, defaultMaxTokens: 4096 }; }
    async *stream(options) {
      report.model_calls++;
      assert(report.model_calls <= 45, "MODEL_BUDGET");
      const mode = options.model;
      calls.set(mode, (calls.get(mode) ?? 0) + 1);
      const n = steps.get(options.sessionId) ?? 0;
      steps.set(options.sessionId, n + 1);
      const carrier = options.tools?.find(tool => tool.parameters?.properties?.decision && tool.parameters?.properties?.reason);
      const names = options.tools?.map(tool => tool.name) ?? [];
      const reviewerDepth = agentsBySession.get(options.sessionId)?.session.header.delegationDepth;
      report.reviewer_catalogs.push({ mode, names, delegationDepth: reviewerDepth });
      assert.equal(reviewerDepth, 1, "REVIEWER_DEPTH_LIMIT");
      assert(carrier, "STRUCTURED_CARRIER_MISSING");
      // 原生深度限制仍呈现 subagent，但 depth=1 下执行不能创建 depth=2 的下级。
      const subagent = options.tools.find(tool => tool.name === "subagent");
      assert(subagent, "NATIVE_DELEGATION_LIMIT_TOOL_MISSING");
      assert.deepEqual([...names].sort(), ["rotom_review_context", carrier.name, "subagent"].sort(), "REVIEWER_TOOL_FACE");
      if (mode === "attack-subagent") report.delegation_schema = subagent;
      assert(!JSON.stringify(options.messages).includes(sentinel), "SENTINEL_LEAK");
      if (mode === "error") {
        yield { type: "finish", reason: { kind: "error", failure: { code: "AUTHENTICATION_FAILED", message: "synthetic SDK failure", retryable: false } } };
        return;
      }
      if ((mode === "attack" || mode === "attack-subagent") && n > 0) { yield { type: "finish", reason: { kind: "stop" } }; return; }
      let name, args;
      if (n === 0 && mode === "attack-subagent") {
        name = "subagent";
        args = Object.fromEntries((report.delegation_schema.parameters.required ?? []).map(key => {
          const schema = report.delegation_schema.parameters.properties[key];
          return [key, schema.enum?.[0] ?? (schema.type === "string" ? "Diagnostic no-op; do not use tools" : schema.type === "boolean" ? false : schema.type === "number" || schema.type === "integer" ? 1 : {})];
        }));
        report.delegation_arguments = args;
      } else if (n === 0) {
        name = mode === "attack" ? "read" : "rotom_review_context";
        args = mode === "attack" ? { file_path: process.env.AGENTCFG_SMOKE_OUTSIDE } : {};
      } else {
        name = carrier.name;
        args = { decision: mode === "deny" ? "deny" : "allow", reason: "deterministic fixture verdict", riskLevel: mode === "high" ? "high" : "low" };
      }
      const id = "fixture-" + randomUUID(), argumentsText = JSON.stringify(args);
      yield { type: "block-start", index: 0, blockType: "tool-call" };
      yield { type: "tool-call-delta", index: 0, id, name, argumentsDelta: argumentsText };
      yield { type: "block-end", index: 0, block: { type: "tool-call", id, name, arguments: argumentsText } };
      yield { type: "finish", reason: { kind: "tool-calls" } };
      save();
    }
  }
  ctx.get("llm").registerAdapter(["rotom-formal-fixture"], new Fake());
  ctx.on("agent/created", ({ agent }) => {
    agentsBySession.set(agent.session.id, agent);
    report.created_agents.push({ id: agent.id, provider: agent.options.provider, model: agent.options.model,
      parent: agent.session.header.parentSessionId ?? null, delegationDepth: agent.session.header.delegationDepth ?? null });
  });
  ctx.on("tools/result", (exec, result) => {
    if (exec.name === "subagent" && exec.agent?.options.model === "attack-subagent") report.delegation_attempt = { isError: !!result.isError, result };
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
    if (mode === "error") throw new Error("synthetic human fallback failure");
    if (manual && mode === "manual") return "allowed-once";
    return "rejected";
  });
  const create = async mode => {
    const handle = await ctx.get("agents").create({ sessionId: randomUUID(), meta: { cwd: process.cwd() },
      agentOptions: { provider: "rotom-formal-fixture", model: mode }, setup: async agentCtx => { await presets.mount(agentCtx, "standard"); } });
    handles.push(handle);
    const agent = handle.agent;
    agent.session.append("turn/start", { turn: 1 });
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
    return agent;
  };
  const execute = async (agent, label, allowed, expectReview, expectHuman) => {
    stage("write." + label);
    const target = path.join(process.cwd(), "ask-" + label + ".txt"), mode = agent.options.model;
    const aiBefore = calls.get(mode) ?? 0, humanBefore = human.get(mode) ?? 0;
    const result = await bounded(agent.ctx.get("tools").execute({ agent, name: "write", arguments: { file_path: target, content: "fixture " + label },
      signal: AbortSignal.timeout(10000), callId: "write-" + label + "-" + randomUUID() }));
    const count = successfulWrites.get(target) ?? 0, ai = (calls.get(mode) ?? 0) - aiBefore, humans = (human.get(mode) ?? 0) - humanBefore;
    report.cases[label] = { native_success_results: count, file_exists: fs.existsSync(target), ai_calls: ai, human_calls: humans, isError: !!result.isError };
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
    report.command_status = await ctx.get("commands").execute(normal, "/auto-review status", [], new AbortController().signal);
    await execute(normal, "allow", true, true, false);
    for (const [mode, humanExpected] of [["deny", false], ["high", true], ["error", true], ["attack", true]]) {
      await execute(await create(mode), mode, false, true, humanExpected);
    }
    const delegationParent = await create("attack-subagent");
    const countBefore = report.created_agents.length;
    await execute(delegationParent, "attack-subagent", false, true, true);
    assert(report.delegation_attempt?.isError, "NATIVE_DEPTH_DENIAL_MISSING");
    assert(JSON.stringify(report.delegation_attempt.result).includes("subagent depth 2 exceeds maxDepth 1"), "NATIVE_DEPTH_REASON");
    assert.equal(report.created_agents.length, countBefore + 1, "EXTRA_DELEGATION_CHILD_CREATED");
    report.delegation_boundary = { native_max_depth: 1, attempted_depth: 2, extra_children: 0,
      tool_hidden: false, provider: "spawn", presentation: "native", result: "PASS" };
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
    unknown.ctx.on("tools/pre-execute", (exec, next) => exec.name === "rotom_formal_unknown" ? { kind: "ask", reason: "unknown policy mapping" } : next(), { prepend: true });
    const unknownResult = await unknown.ctx.get("tools").execute({ agent: unknown, name: "rotom_formal_unknown", arguments: {}, signal: AbortSignal.timeout(2000), callId: "unknown" });
    assert(unknownResult.isError && (human.get("unknown") ?? 0) === 1 && (calls.get("unknown") ?? 0) === 0);
    report.cases.unknown = { human_calls: human.get("unknown"), ai_calls: 0, isError: true };
    const never = await create("never");
    never.ctx.get("approval").setPolicy(never, "never");
    await execute(never, "never", false, false, false);
    const before = report.model_calls;
    const nativeTarget = path.join(process.cwd(), "native-normal.txt");
    const native = await normal.ctx.get("tools").execute({ agent: normal, name: "write", arguments: { file_path: nativeTarget, content: "ordinary workspace write" },
      signal: AbortSignal.timeout(2000), callId: "native-normal" });
    assert(!native.isError && fs.readFileSync(nativeTarget, "utf8") === "ordinary workspace write");
    assert.equal(report.model_calls, before);
    report.cases.native_normal = { native_success_results: successfulWrites.get(nativeTarget), ai_calls: 0 };
    assert.equal(fs.readFileSync(process.env.AGENTCFG_SMOKE_OUTSIDE, "utf8"), sentinel);
    assert(report.attack_read?.isError, "ATTACK_NOT_EXERCISED");
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
