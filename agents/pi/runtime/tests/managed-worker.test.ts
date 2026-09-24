import { createHash } from "node:crypto";
import { digest } from "../managed-types.ts";
import assert from "node:assert/strict";
import { test } from "node:test";
import { runManagedWorker, validateWorkerInput } from "../managed-worker.ts";
import { descriptor } from "./fixtures.ts";

function fixture() {
  const value = { ...descriptor(), role_digest: createHash("sha256").update("fixture role").digest("hex"), result_schema_digest: digest({}) }, calls = [], reports = [];
  const input = { descriptor: value, context: { schema_version: 1, manager_run_id: "run", lease_id: "lease", prompt: "fixture prompt",
    role: { id: value.role_id, digest: value.role_digest, definition: "fixture role", system_prompt: "fixture role", tools: value.allowed_tools },
    model: { provider_id: value.provider_id, model_id: value.model_id, model_digest: value.model_digest, api: "openai-completions" },
    route: { id: "direct", type: "direct", base_url: "https://fixture.invalid/v1", proxy_url: null },
    root_bindings: { project: { path: "/fixture/candidate", identity: "a".repeat(64) } }, artifacts: {}, result_schema: {}, minimum_remaining: 0, database: { root: "/fixture/state", filename: "runtime.db", owner: { scopeId: "task", token: "private", epoch: 1 } } } };
  const session = { thinkingLevel: "medium", isStreaming: false, messages: [{ role: "assistant", stopReason: "stop" }],
    getActiveToolNames: () => ["tk_read"], setAutoCompactionEnabled: value => calls.push(["compaction", value]),
    setAutoRetryEnabled: value => calls.push(["retry", value]), async prompt() { calls.push(["prompt"]); },
    getLastAssistantText: () => "fixture final", async abort() { calls.push(["abort"]); }, dispose() { calls.push(["dispose"]); } };
  const sdk = { parseFrontmatter: body => ({ body }), createExtensionRuntime: () => ({}),
    SettingsManager: { inMemory: settings => { calls.push(["settings", settings]); return settings; } },
    SessionManager: { inMemory: cwd => ({ cwd, fresh: true }) },
    async createAgentSession(options) { calls.push(["session", options]); return { session }; } };
  const modelRuntime = { getModel: (provider, id) => ({ provider, id, api: "openai-completions", reasoning: true }) };
  const transport = { api: "openai-completions", certified: true, model_digest: value.model_digest, route_id: "direct",
    async bind() { calls.push(["bind"]); return { async close() { calls.push(["transport-close"]); } }; } };
  const tools = [{ name: "tk_read", async execute() { calls.push(["read"]); return { content: [] }; } }];
  let valid = true;
  const supervisor = { async call(method, args) { calls.push([method]); return { valid, grant_generation: args.grant_generation }; } };
  return { calls, reports, session, input, transport, revoke() { valid = false; },
    options: { sdk, input, agentDir: "/fixture/private-worker", modelRuntime, transport, tools, supervisor,
      report: async value => { reports.push(value); }, now: () => Date.parse("2026-09-16T00:00:00Z") } };
}

test("fresh worker passes an explicit empty loader, exact tools and no retry to SDK", async () => {
  const f = fixture();
  const result = await runManagedWorker(f.options);
  const options = f.calls.find(([name]) => name === "session")[1];
  assert.equal(options.sessionManager.fresh, true);
  assert.equal(options.noTools, "builtin");
  assert.deepEqual(options.tools, ["tk_read"]);
  assert.deepEqual(options.resourceLoader.getExtensions().extensions, []);
  assert.deepEqual(options.resourceLoader.getSkills().skills, []);
  assert.deepEqual(options.resourceLoader.getAgentsFiles().agentsFiles, []);
  assert.throws(() => options.resourceLoader.extendResources({}), /RESOURCE_DISCOVERY_DISABLED/);
  assert.equal(options.settingsManager.retry.provider.maxRetries, 0);
  assert.equal(result.state, "execution_settled");
  assert.equal(result.termination_confirmed, false);
  assert.deepEqual(f.reports.filter(value => value.event).map(value => value.event.sequence), [1, 2]);
  assert.equal(f.calls.at(-1)[0], "transport-close");
});

test("worker denies helper tools, provider mismatch, unmetered transport and second manager before SDK", async () => {
  for (const mutation of [
    f => { f.input.descriptor.allowed_tools = ["model_delegate"]; f.input.context.role.tools = ["model_delegate"]; },
    f => { f.input.context.model.provider_id = "another"; },
    f => { f.transport.certified = false; },
    f => { f.input.context.route.proxy_url = "https://user:password@fixture.invalid"; },
  ]) {
    const f = fixture(); mutation(f);
    await assert.rejects(runManagedWorker(f.options));
    assert.equal(f.calls.some(([name]) => name === "session"), false);
  }
  const f = fixture(), key = Symbol.for("pi-subagents:manager");
  globalThis[key] = {};
  try { await assert.rejects(runManagedWorker(f.options), /MANAGER_FORBIDDEN/); }
  finally { delete globalThis[key]; }
  assert.equal(f.calls.length, 0);
});

test("worker tools reauthorize and failed final turn cannot reuse earlier assistant text", async () => {
  const f = fixture();
  f.session.prompt = async () => {
    const options = f.calls.find(([name]) => name === "session")[1];
    f.revoke();
    await assert.rejects(options.customTools[0].execute("call"), /GRANT_STALE/);
  };
  await assert.rejects(runManagedWorker(f.options), /GRANT_STALE/);
  assert.equal(f.calls.some(([name]) => name === "read"), false);
  const failed = fixture(); failed.session.messages[0].stopReason = "error";
  await assert.rejects(runManagedWorker(failed.options), /EXECUTION_FAILED/);
  assert.equal(failed.reports.find(value => value.result).result.state, "execution_failed");
  assert.equal(failed.calls.at(-1)[0], "transport-close");
});

test("worker refuses a silently clamped thinking level before any model request", async () => {
  const f = fixture();
  f.session.thinkingLevel = "off";
  await assert.rejects(runManagedWorker(f.options), /THINKING_LEVEL_UNSUPPORTED/);
  assert.equal(f.calls.some(([name]) => name === "prompt"), false);
});

test("a budget rejection absorbed by SDK still reaches the task receipt as a budget failure", async () => {
  const f = fixture();
  f.transport.budgetExhausted = true;
  f.session.messages[0].stopReason = "error";
  await assert.rejects(runManagedWorker(f.options), /BUDGET_EXHAUSTED/);
  assert.equal(f.reports.find(row => row.result).result.failure_code, "BUDGET_EXHAUSTED");
});
