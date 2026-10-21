// 官方公开 Agent/Teams API 验收；不构造会话日志或伪造成员身份。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const runtime = process.argv[2], root = process.env.AGENTCFG_SMOKE_ROOT, phase = process.env.AGENTCFG_SMOKE_PHASE;
assert(runtime && path.isAbsolute(runtime) && root && process.cwd().startsWith(root + "/"));
assert(["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"].every(key => process.env[key]?.startsWith(root + "/")));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)));
const report = { phase, functional: "FAIL", cases: {}, model_calls: 0, real_accounts: "NOT RUN" };
const save = () => fs.writeFileSync(process.env.AGENTCFG_SMOKE_RESULT, JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
const bounded = async promise => {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("FIXTURE_TIMEOUT")), 20000); })]); }
  finally { clearTimeout(timer); }
};
let boot, handle;
try {
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  boot = await bounded(runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_SMOKE_PATCH, process.env.AGENTCFG_SMOKE_HEADLESS, process.env.AGENTCFG_SMOKE_PRESET],
    args: [], packageManager: { command: "/bin/false", args: [], env: {} } }));
  const ctx = boot.ctx, teams = ctx.get("agentTeams"), presets = ctx.get("agentPresets");
  assert(ctx.get("autoReviewRuntime"), "PERRY_COMPOSITION_MISSING");
  report.cases.perry_coexists = "PASS";
  const enabled = phase === "on" || phase === "resume";
  assert.equal(!!teams, enabled, "EXPLICIT_SERVICE_SELECTION");
  const { LlmAdapter } = await moduleAt("@deepseek-ai/dsh-llm");
  const created = new Map(), seen = new Map(), processing = new Map();
  let leadId, spawned = false, spawnResult, holdSession, requestWrite = false, writeResult;
  report.reviewer_calls = 0;
  ctx.on("agent/created", ({ agent }) => created.set(agent.id, agent));
  ctx.on("tools/result", (exec, result) => {
    if (exec.name === "spawn_teammate") {
      assert(!result.isError, "MODEL_SPAWN_FAILED");
      spawnResult = result;
    }
    if (exec.name === "write") writeResult = result;
  });
  class Fake extends LlmAdapter {
    providerRetryPolicy() { return { mode: "normal", maxRetries: 0 }; }
    async resolveModel(provider, model) { return { provider, id: model, name: model, inputModalities: ["text"], context: { contextWindow: 262144 }, defaultMaxTokens: 4096 }; }
    async *stream(options) {
      report.model_calls++;
      assert(report.model_calls < 30, "MODEL_BUDGET");
      if (!options.sessionId && options.system?.includes("read-only safety reviewer")) {
        assert.equal(options.tools?.length ?? 0, 0, "INLINE_REVIEWER_TOOL_LEAK");
        report.reviewer_calls++;
        const text = JSON.stringify({ decision: "allow", riskLevel: "low", reason: "Authorized synthetic fixture write." });
        yield { type: "block-start", index: 0, blockType: "text" };
        yield { type: "block-end", index: 0, block: { type: "text", text } };
        yield { type: "finish", reason: { kind: "stop" } };
        return;
      }
      seen.set(options.sessionId, (seen.get(options.sessionId) ?? 0) + 1);
      processing.get(options.sessionId)?.();
      processing.delete(options.sessionId);
      if (options.sessionId === holdSession) {
        // 保留真实运行中的 continuation，服务 API 只接受当前登记的精确 Agent。
        await new Promise(resolve => {
          if (options.signal.aborted) resolve();
          else options.signal.addEventListener("abort", resolve, { once: true });
        });
        yield { type: "finish", reason: { kind: "aborted" } };
        return;
      }
      if (options.sessionId === leadId && requestWrite) {
        requestWrite = false;
        const id = randomUUID(), argumentsText = JSON.stringify({ file_path: path.join(process.cwd(), "ask-team.txt"), content: "Synthetic reviewed Team write." });
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "block-end", index: 0, block: { type: "tool-call", id, name: "write", arguments: argumentsText } };
        yield { type: "finish", reason: { kind: "tool-calls" } };
        return;
      }
      if (phase === "on" && options.sessionId === leadId && !spawned) {
        spawned = true;
        assert(options.tools.some(tool => tool.name === "spawn_teammate"), "TEAM_TOOL_NOT_ASSEMBLED");
        const id = randomUUID(), argumentsText = JSON.stringify({ name: "fresh-worker", description: "Isolated fixture worker", prompt: "Return a deterministic fixture acknowledgement.", context: "fresh" });
        yield { type: "block-start", index: 0, blockType: "tool-call" };
        yield { type: "block-end", index: 0, block: { type: "tool-call", id, name: "spawn_teammate", arguments: argumentsText } };
        yield { type: "finish", reason: { kind: "tool-calls" } };
        return;
      }
      yield { type: "block-start", index: 0, blockType: "text" };
      yield { type: "block-end", index: 0, block: { type: "text", text: "Synthetic fixture acknowledgement." } };
      yield { type: "finish", reason: { kind: "stop" } };
    }
  }
  ctx.get("llm").registerAdapter(["rotom-team-fixture"], new Fake());
  const options = { agentOptions: { provider: "rotom-team-fixture", model: "fixture" }, setup: async scoped => { await presets.mount(scoped, "standard"); } };
  if (phase === "resume") {
    const state = JSON.parse(fs.readFileSync(process.env.AGENTCFG_SMOKE_STATE, "utf8"));
    handle = await ctx.get("agents").resume({ ...options, resumeSessionId: state.lead });
    const lead = handle.agent;
    assert.deepEqual(teams.listMembers(lead).filter(m => m.role === "teammate").map(m => m.name).sort(), ["fork-worker", "fresh-worker"]);
    assert.equal(teams.getTask(lead, state.completed).status, "completed");
    const held = teams.getTask(lead, state.held);
    assert.equal(held.status, "in_progress");
    assert.equal(held.ownerName, "fresh-worker");
    report.cases.restart_roster_and_tasks = "PASS";
  } else {
    leadId = randomUUID();
    handle = await ctx.get("agents").create({ ...options, sessionId: leadId, meta: { cwd: process.cwd() } });
    const lead = handle.agent, names = lead.ctx.get("tools").schemas(lead).map(t => t.name);
    report.catalog = names;
    assert.equal(names.includes("spawn_teammate"), enabled);
    if (!enabled) {
      assert(names.some(name => /subagent|task/.test(name)), "ORDINARY_DELEGATION_MISSING");
      report.cases.ordinary_delegation_restored = "PASS";
    } else {
      lead.followup({ id: randomUUID(), role: "user", content: [{ type: "text", text: "Run the authorized isolated teammate fixture." }], source: { kind: "user" } });
      await bounded(lead.whenIdle());
      assert(spawnResult, "REAL_TOOL_RESULT_MISSING");
      let members = teams.listMembers(lead);
      let fresh = created.get(members.find(m => m.name === "fresh-worker").id);
      assert(fresh, "EXACT_LIVE_TEAMMATE_MISSING");
      await bounded(fresh.whenIdle());
      const forked = await bounded(teams.spawnTeammate(lead, { name: "fork-worker", description: "Fork fixture", prompt: [{ type: "text", text: "Return a fixture acknowledgement." }], context: "fork", provider: "fork", signal: AbortSignal.timeout(15000) }));
      const fork = created.get(forked.member.id);
      await bounded(fork.whenIdle());
      members = teams.listMembers(lead);
      assert.equal(members.length, 3);
      assert.equal(members.find(m => m.name === "fork-worker").context, "fork");
      report.cases.model_spawn_fresh_and_public_fork = "PASS";
      const prior = seen.get(fresh.id) ?? 0;
      holdSession = fresh.id;
      const processed = new Promise(resolve => processing.set(fresh.id, resolve));
      const accepted = await teams.sendMessage(lead, { target: "fresh-worker", content: [{ type: "text", text: "Synthetic continuation message." }], signal: AbortSignal.timeout(15000) });
      assert(accepted.messageId);
      await bounded(processed);
      fresh = ctx.get("agents").get(holdSession);
      assert(fresh, "CURRENT_LIVE_CONTINUATION_MISSING");
      assert((seen.get(fresh.id) ?? 0) > prior, "ACCEPTED_MESSAGE_NOT_PROCESSED");
      report.cases.inbox_acceptance_and_separate_processing = "PASS";
      const task = await teams.createTask(lead, { subject: "Fixture task", description: "CAS lifecycle", writeScopes: ["fixture.txt"] });
      const claimed = await teams.updateTask(fresh, { taskId: task.id, expectedRevision: task.revision, action: "claim" });
      await assert.rejects(teams.updateTask(lead, { taskId: task.id, expectedRevision: task.revision, action: "claim" }), error => error.code === "TEAM_TASK_STALE_REVISION");
      const completed = await teams.updateTask(fresh, { taskId: task.id, expectedRevision: claimed.revision, action: "complete" });
      assert.equal(completed.status, "completed");
      const held = await teams.createTask(lead, { subject: "Retained assignment", description: "Interrupt does not release ownership" });
      await teams.updateTask(fresh, { taskId: held.id, expectedRevision: held.revision, action: "claim" });
      teams.interrupt(lead, "fresh-worker");
      await bounded(fresh.whenIdle());
      assert.equal(teams.getTask(lead, held.id).ownerName, "fresh-worker");
      report.cases.task_cas_complete_and_retained_claim = "PASS";
      assert(lead.session.snapshotEvents().some(e => e.type === "team/task"));
      // 通过公开测试 handler 仅让这个合成 write 进入真实 pending 审批链。
      lead.ctx.on("tools/pre-execute", (exec, next) => exec.name === "write" && path.basename(exec.arguments.file_path) === "ask-team.txt"
        ? { kind: "ask", reason: "synthetic Team composition review" } : next(), { prepend: true });
      await bounded(lead.whenIdle());
      requestWrite = true;
      lead.followup({ id: randomUUID(), role: "user", content: [{ type: "text", text: "Authorize one synthetic fixture file write in this isolated workspace." }], source: { kind: "user" } });
      await bounded(lead.whenIdle());
      assert(writeResult && !writeResult.isError, "TEAM_REVIEWED_WRITE_FAILED");
      assert.equal(report.reviewer_calls, 1);
      assert.equal(fs.readFileSync(path.join(process.cwd(), "ask-team.txt"), "utf8"), "Synthetic reviewed Team write.");
      report.cases.team_pending_write_reviewed_by_perry = "PASS";
      fs.writeFileSync(process.env.AGENTCFG_SMOKE_STATE, JSON.stringify({ lead: lead.id, completed: completed.id, held: held.id }), { mode: 0o600 });
    }
  }
  await bounded(handle.dispose());
  handle = null;
  await bounded(boot.shutdown.shutdown(0));
  boot = null;
  report.cases.fixture_shutdown = "PASS";
  report.functional = "PASS";
} catch (error) {
  report.error = { name: error.name, code: error.code ?? null, message: String(error.message).replaceAll(runtime, "<runtime>").replaceAll(root, "<fixture>").slice(0, 1200) };
} finally {
  try { if (handle) await bounded(handle.dispose()); } catch { report.cleanup_error = true; }
  try { if (boot) await bounded(boot.shutdown.shutdown(1)); } catch { report.cleanup_error = true; }
  save();
}
process.exitCode = report.functional === "PASS" ? 0 : 1;
