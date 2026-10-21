// 显式原生 smoke 的单次提权用例；目标只在本轮隔离目录内。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";

const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
const count = target => fs.existsSync(target) ? fs.readFileSync(target, "utf8").split("\n").filter(Boolean).length : 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function runSandboxReviewCases({ ctx, create, executeTool, calls, human, report, bounded, stage }) {
  const root = process.env.AGENTCFG_SMOKE_ROOT;
  const targetRoot = process.env.AGENTCFG_SMOKE_SANDBOX_TARGET_ROOT;
  assert(root && process.cwd().startsWith(root + "/"), "SANDBOX_FIXTURE_ROOT");
  assert(targetRoot && path.isAbsolute(targetRoot) && !targetRoot.startsWith(root + "/"), "SANDBOX_TARGET_ROOT");
  assert(fs.lstatSync(targetRoot).isDirectory() && !fs.lstatSync(targetRoot).isSymbolicLink(), "SANDBOX_TARGET_DIRECTORY");
  const summarize = value => JSON.stringify(value).replaceAll(root, "<fixture>").replaceAll(targetRoot, "<sandbox-targets>");
  const timeoutOnly = report.mode === "timeout";
  const observations = [];
  report.sandbox_review = { status: "RUNNING", actual_bash: true, synthetic_ask: false,
    dispatch: executeTool ? "parent-model-tool-call" : "public-tools-execute-during-real-turn", observations };
  const approvals = new Map();
  const executed = new Map();
  ctx.on("tools/post-execute", (exec, result, next) => {
    if (exec.name === "bash") {
      executed.set(exec.callId, { value: result.isError ? undefined : result.value,
        command: exec.arguments.command });
    }
    return next();
  });
  ctx.on("approval/request", (request, next) => {
    if (request.toolName === "bash") {
      approvals.set(request.callId, { tool: request.toolName, reason: request.reason });
    }
    return next();
  }, { prepend: true });

  const execute = async (agent, label, target, command, { escalate = false, expectedCount,
      expectedAi = false, expectedHuman = false, expectedMode, expectedDenied } = {}) => {
    stage("sandbox." + label);
    const mode = agent.options.model;
    const beforeAi = calls.get(mode) ?? 0;
    const beforeHuman = human.get(mode) ?? 0;
    const callId = "sandbox-" + randomUUID();
    const justification = "Authorized isolated native smoke; append one synthetic marker to the fixture target";
    const args = { command, description: "Append one synthetic marker in the isolated native smoke fixture" };
    if (escalate) Object.assign(args, { sandbox_permissions: "danger-full-access", justification });
    const request = { name: "bash", arguments: args, signal: AbortSignal.timeout(15000), callId };
    const result = await bounded(executeTool ? executeTool(agent, request)
      : agent.ctx.get("tools").execute({ agent, ...request }), 20000);
    if (expectedCount > 0) {
      for (let attempt = 0; attempt < 100 && count(target) < expectedCount; attempt++) await delay(20);
    } else {
      await delay(100);
    }
    // 结构值只存在于公开执行期事件，最终呈现的 ToolResult 不保留 value。
    const execution = executed.get(callId);
    const value = execution?.value;
    const actualAi = (calls.get(mode) ?? 0) - beforeAi;
    const actualHuman = (human.get(mode) ?? 0) - beforeHuman;
    const approval = approvals.get(callId);
    const observation = { label, call_id: callId,
      command_sha256: createHash("sha256").update(command).digest("hex"),
      explicit_escalation: escalate, file_lines: count(target), ai_calls: actualAi,
      human_calls: actualHuman, is_error: !!result.isError,
      error_summary: result.isError ? summarize(result.content ?? []).slice(0, 1200) : null,
      execution_summary: value ? summarize(value).slice(0, 4000) : null,
      native_argument_matches: execution?.command === command,
      exit_code: typeof value?.exitCode === "number" ? value.exitCode : null,
      sandbox: value?.sandbox ? { mode: value.sandbox.mode, denied: value.sandbox.denied } : null,
      native_approval_reason_matches: !!approval && approval.reason === "escalate sandbox to danger-full-access: " + justification };
    observations.push(observation);
    report.cases["sandbox_" + label] = observation;
    assert.equal(observation.file_lines, expectedCount, "SANDBOX_EXECUTION_COUNT_" + label);
    assert.equal(actualAi > 0, expectedAi, "SANDBOX_AI_ROUTE_" + label);
    assert.equal(actualHuman > 0, expectedHuman, "SANDBOX_HUMAN_ROUTE_" + label);
    if (escalate) assert(observation.native_approval_reason_matches, "NATIVE_ESCALATION_REASON_" + label);
    if (expectedMode) {
      assert(observation.native_argument_matches, "NATIVE_COMMAND_ARGUMENT_" + label);
      assert.equal(value?.sandbox?.mode, expectedMode, "SANDBOX_RESULT_MODE_" + label);
      assert.equal(value?.sandbox?.denied, expectedDenied, "SANDBOX_RESULT_DENIED_" + label);
    }
    assert.equal(agent.ctx.get("sandboxPolicy").resolve({ session: agent.session }).mode,
      "workspace-write", "SESSION_SANDBOX_CHANGED_" + label);
    assert.equal(agent.ctx.get("approval").effectivePolicy(agent.session), "ask", "SESSION_APPROVAL_CHANGED_" + label);
    return observation;
  };
  const makeTarget = label => {
    const target = path.join(targetRoot, "sandbox-review-" + label + "-" + randomUUID() + ".txt");
    fs.writeFileSync(target, "", { mode: 0o600, flag: "wx" });
    return target;
  };
  const commandFor = target => "printf '%s\\n' " + quote("synthetic-marker") + " >> " + quote(target);

  if (timeoutOnly) {
    assert.equal(report.formal_config.reviewerTimeoutMs, 1000, "TIMEOUT_PROFILE_OVERRIDE");
    const agent = await create("sandbox-timeout");
    const target = makeTarget("timeout");
    await execute(agent, "timeout", target, commandFor(target), {
      escalate: true, expectedCount: 0, expectedAi: true, expectedHuman: true });
  } else {
    const ordinary = await create("sandbox-ordinary");
    assert(ordinary.ctx.get("tools").get("bash", ordinary), "NATIVE_BASH_MISSING");
    const inside = path.join(process.cwd(), "sandbox-review-inside-" + randomUUID() + ".txt");
    await execute(ordinary, "ordinary", inside, commandFor(inside), {
      expectedCount: 1, expectedMode: "workspace-write", expectedDenied: false });

    const allowed = await create("sandbox-allow");
    const outside = makeTarget("allow");
    const command = commandFor(outside);
    const before = await execute(allowed, "before_grant", outside, command, {
      expectedCount: 0, expectedMode: "workspace-write", expectedDenied: true });
    const once = await execute(allowed, "allow_once", outside, command, {
      escalate: true, expectedCount: 1, expectedAi: true,
      expectedMode: "danger-full-access", expectedDenied: false });
    const after = await execute(allowed, "after_grant", outside, command, {
      expectedCount: 1, expectedMode: "workspace-write", expectedDenied: true });
    assert.equal(before.command_sha256, once.command_sha256, "ESCALATION_COMMAND_CHANGED");
    assert.equal(after.command_sha256, once.command_sha256, "RETRY_COMMAND_CHANGED");
    assert(new Set([before.call_id, once.call_id, after.call_id]).size === 3, "ESCALATION_CALL_IDS_REUSED");

    for (const mode of ["deny", "high", "error"]) {
      const agent = await create("sandbox-" + mode);
      const target = makeTarget(mode);
      await execute(agent, mode, target, commandFor(target), {
        escalate: true, expectedCount: 0, expectedAi: true, expectedHuman: mode !== "deny" });
    }
  }
  report.sandbox_review.status = "PASS";
  report.sandbox_review.one_call_grant_checked = !timeoutOnly;
}
