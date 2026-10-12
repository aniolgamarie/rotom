// 独立显式原生入口：仅公开 API，人工审批由确定性回答器驱动，不冒充 AI reviewer。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

const runtime = process.argv[2];
const root = process.env.AGENTCFG_SMOKE_ROOT;
if (!runtime || !path.isAbsolute(runtime) || !root || !["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"].every(name => process.env[name]?.startsWith(root + "/"))) {
  throw new Error("An explicit isolated native environment and sealed runtime are required");
}
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
const output = process.env.AGENTCFG_SMOKE_RESULT;
let evidence = process.argv[3] === "--read-audit" ? JSON.parse(fs.readFileSync(output, "utf8"))
  : { kind: "native-manual-approval-no-account", nonce: process.env.AGENTCFG_SMOKE_NONCE, cwd: process.cwd(), checks: {} };
const save = () => fs.writeFileSync(output, JSON.stringify(evidence, null, 2) + "\n", { mode: 0o600 });
const stage = name => { evidence.stage = name; save(); };
const waitFor = async predicate => {
  for (let i = 0; i < 100 && !predicate(); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(predicate(), "native fixture did not reach the expected state");
};
const auditOf = events => events.filter(event => ["approval/asked", "approval/decided"].includes(event.type))
  .map(event => event.type === "approval/asked"
    ? { type: event.type, id: event.data.id, callId: event.data.callId }
    : { type: event.type, id: event.data.id, outcome: event.data.outcome });
const assertAudit = events => {
  const asked = events.filter(event => event.type === "approval/asked");
  const decided = events.filter(event => event.type === "approval/decided");
  assert(asked.length >= 8, "approval audit cases missing");
  assert.equal(new Set(asked.map(event => event.id)).size, asked.length);
  assert.equal(decided.length, asked.length);
  for (const event of asked) {
    assert(event.callId, "asked event has no tool call identity");
    assert.equal(decided.filter(item => item.id === event.id).length, 1);
  }
};

async function protocolChecks() {
  const { buildRunPayload } = await moduleAt("dsh-cursor-subscription");
  const { Reader, Writer } = await moduleAt("dsh-cursor-subscription/proto");
  const bytes = (input, field) => {
    const reader = new Reader(input);
    while (!reader.done) {
      const tag = reader.tag();
      if (tag.field === field && tag.wireType === 2) return reader.bytes();
      reader.skip(tag.wireType);
    }
    throw new Error("expected public protobuf field is missing");
  };
  const action = payload => new TextDecoder().decode(bytes(bytes(bytes(bytes(bytes(payload, 1), 2), 1), 1), 1));
  const text = value => [{ type: "text", text: value }];
  const task = "LAST_ACTUAL_TASK_MARKER";
  const options = { messages: [
    { role: "user", content: text("HISTORICAL_USER_MARKER") },
    { role: "assistant", content: text("HISTORICAL_ASSISTANT_MARKER") },
    { role: "user", content: text(task) },
    ...["AGENTS.md", "rules", "plugin-context"].map(source => ({ role: "user", source: { kind: "plugin", plugin: source }, content: text("RUNTIME_" + source) })),
  ] };
  const checkpoint = new Writer().bytes(1, new Uint8Array(32).fill(7)).finish();
  const persisted = { checkpoint, blobs: new Map() };
  const cold = action(buildRunPayload(options, "fixture", undefined).payload);
  const warmPayload = buildRunPayload(options, "fixture", persisted).payload;
  const warm = action(warmPayload);
  assert(cold.includes("[USER]\n" + task) && cold.includes("[RUNTIME CONTEXT]\nRUNTIME_AGENTS.md"));
  assert(warm.includes(task) && warm.includes("RUNTIME_AGENTS.md") && warm.includes("RUNTIME_rules"));
  assert(!warm.includes("HISTORICAL_ASSISTANT_MARKER") && !warm.includes("HISTORICAL_USER_MARKER"));
  assert.deepEqual(bytes(bytes(warmPayload, 1), 1), checkpoint);
  const compacted = { messages: [{ role: "user", source: { kind: "compact-checkpoint", compactionId: "fixture-compaction" }, content: text("COMPACT_SUMMARY") }, ...options.messages] };
  assert(action(buildRunPayload(compacted, "fixture", undefined).payload).includes(task));
  const tool = { messages: [...options.messages, { role: "assistant", content: [{ type: "tool-call", id: "fixture-call", name: "fixture-tool", arguments: {} }] },
    { role: "user", content: [{ type: "tool-result", toolCallId: "fixture-call", content: text("TOOL_RESULT_MARKER") }] }] };
  for (const state of [undefined, persisted]) {
    assert(action(buildRunPayload(tool, "fixture", state).payload).includes("[TOOL RESULT for fixture-call]\nTOOL_RESULT_MARKER"));
  }
  return { kind: "pure-public-protocol-mock", cold_start_task: "PASS", checkpoint_task: "PASS", compact_checkpoint: "PASS", tool_result: "PASS" };
}

async function cursorMocks() {
  const { CursorAuthService, CursorCredentialStore, CursorLoginCoordinator, CREDENTIAL_REF, PROVIDER } = await moduleAt("dsh-cursor-subscription");
  const { TerminalCursorAdapter, createLoginHandler } = await moduleAt("rotom-dsh-cursor-terminal");
  let stored;
  const credentials = { resolve: async () => stored === undefined ? undefined : { value: stored },
    set: async (_ref, value) => { stored = value; }, unset: async () => { stored = undefined; } };
  const store = new CursorCredentialStore(credentials, CREDENTIAL_REF);
  const canary = "synthetic-provider-secret-error-body";
  const denied = new CursorAuthService(store, { fetch: async () => { throw new Error(canary); } });
  const adapter = new TerminalCursorAdapter({ auth: denied, fallbackModels: [], createAgentRun: () => { throw new Error(canary); } });
  const stream = [];
  for await (const chunk of adapter.stream({ messages: [], model: "fixture" })) stream.push(chunk);
  assert(!JSON.stringify(stream).includes(canary));
  assert.equal(stream.at(-1).reason.kind, "error");
  assert.equal(stream.at(-1).reason.failure.code, "MISSING_CREDENTIAL");
  await store.write({ type: "oauth", access: "synthetic-access", refresh: "synthetic-refresh", expires: Date.now() - 1000 });
  const handler = createLoginHandler(new CursorLoginCoordinator(denied), adapter);
  const status = await handler({ rawInput: "status", signal: new AbortController().signal });
  assert(status.text.includes("expired; login required"));
  let resolveRefresh;
  let created = 0;
  const auth = new CursorAuthService(store, { fetch: () => new Promise(resolve => { resolveRefresh = resolve; }) });
  const racing = new TerminalCursorAdapter({ auth, fallbackModels: [], fetchModels: async () => [{ id: "fixture" }],
    createAgentRun: () => { created++; throw new Error(canary); } });
  const lazy = racing.stream({ messages: [], model: "fixture" });
  racing.cancelRequests();
  racing.resumeRequests();
  const stale = [];
  for await (const chunk of lazy) stale.push(chunk);
  assert.equal(created, 0);
  assert.equal(stale.at(-1).reason.kind, "aborted");
  const inflight = racing.stream({ messages: [], model: "fixture" })[Symbol.asyncIterator]();
  const pending = inflight.next();
  await waitFor(() => resolveRefresh !== undefined);
  racing.cancelRequests();
  await auth.logout();
  racing.resumeRequests();
  resolveRefresh({ ok: true, json: async () => ({ accessToken: "synthetic-late-access" }) });
  const late = await pending;
  assert.equal(created, 0);
  assert.equal(late.value.reason.kind, "aborted");
  assert.equal(await store.read(), undefined);
  await inflight.return();
  await store.write({ type: "oauth", access: "synthetic-access", refresh: "synthetic-refresh", expires: Date.now() + 3600000 });
  const preparedOld = await racing.prepareCall(PROVIDER, "fixture");
  racing.cancelRequests();
  racing.resumeRequests();
  const preparedNew = await racing.prepareCall(PROVIDER, "fixture");
  const old = []; const fresh = [];
  for await (const chunk of preparedOld.stream({ messages: [], model: "fixture" })) old.push(chunk);
  for await (const chunk of preparedNew.stream({ messages: [], model: "fixture" })) fresh.push(chunk);
  assert.equal(old.at(-1).reason.kind, "aborted");
  assert.equal(created, 1, "old prepared stream must not create a request in the new generation");
  assert(!JSON.stringify(fresh).includes(canary));
  let resolveLogin; let cancelled = 0;
  const cancellable = createLoginHandler({ start: () => new Promise(resolve => { resolveLogin = resolve; }), cancel: async () => { cancelled++; } }, adapter);
  const controller = new AbortController();
  const login = cancellable({ rawInput: "start", signal: controller.signal });
  await waitFor(() => resolveLogin !== undefined);
  controller.abort(); resolveLogin({ id: "synthetic-login", phase: "pending" });
  await login; await cancellable.dispose();
  assert(cancelled >= 1);
  const later = new AbortController();
  const afterStart = createLoginHandler({ start: async () => ({ id: "started-login", phase: "pending" }), cancel: async () => { cancelled++; } }, adapter);
  await afterStart({ rawInput: "start", signal: later.signal });
  const beforeCancel = cancelled;
  later.abort(); await waitFor(() => cancelled > beforeCancel); await afterStart.dispose();
  await store.clear(); racing.cancelRequests(); adapter.cancelRequests();
  return { redaction: "PASS", expired_status: "PASS", cancelled_login: "PASS", late_refresh_no_request: "PASS", prepared_generations: "PASS", model_calls: 0 };
}

let booted;
try {
  if (process.argv[3] === "--protocol-only") {
    evidence.kind = "pure-public-api-no-host";
    stage("pure.protocol");
    evidence.protocol = await protocolChecks();
    stage("pure.cursor-mocks");
    evidence.cursor_mocks = await cursorMocks();
    evidence.checks.pure_mock = "PASS";
    save();
    process.exit(0);
  }
  stage("host.boot");
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_SMOKE_PATCH], args: [],
    packageManager: { command: process.execPath, args: [process.env.AGENTCFG_SMOKE_LAUNCHER, "--deny-package-operation"], env: {} } });
  const { ctx } = booted;
  if (process.argv[3] === "--read-audit") {
    evidence = JSON.parse(fs.readFileSync(output, "utf8"));
    stage("audit.restart-open");
    const handle = await ctx.get("sessionPersistence").open(process.env.AGENTCFG_SMOKE_SESSION, "read");
    let events;
    try {
      stage("audit.restart-read");
      events = auditOf((await handle.read()).events);
    } finally {
      await handle.close();
    }
    stage("audit.restart-compare");
    assertAudit(events);
    assert.deepEqual(events, evidence.audit);
    evidence.checks.audit_restart = "PASS";
    evidence.audit_restart_complete = true;
    evidence.stage = "audit.restart-complete";
    save(); await booted.shutdown.shutdown(0);
  } else {
    stage("host.agent-created");
    await waitFor(() => ctx.get("agents").list().length > 0);
    const main = ctx.get("agents").list()[0];
    assert.equal(main.session.header.cwd, process.cwd(), "native TUI session did not preserve the explicit business cwd");
    evidence.commands = ctx.get("commands").list(main).map(command => command.name);
    evidence.providers = ctx.get("llm").listProviders().map(provider => provider.id);
    const ui = ctx.get("settings").describe({ redactSecrets: true }).find(row => row.ns === "dsh-tui")?.value;
    evidence.tui_settings = { whale: ui?.whale, whaleIdle: ui?.whaleIdle, minimal: ui?.minimal,
      sidePanelOpen: ui?.sidePanel?.open, sidePanelPanels: ui?.sidePanel?.panels };
    assert.equal(ui?.whale, true);
    assert.equal(ui?.whaleIdle, false);
    assert.equal(ui?.minimal, false);
    assert.equal(ui?.sidePanel?.open, false);
    assert(evidence.commands.includes("auth") && evidence.commands.includes("cursor-login"));
    assert(evidence.providers.includes("cursor-subscription"));
    const status = await ctx.get("commands").execute(main, "/cursor-login status", [], new AbortController().signal);
    assert.equal(status?.result?.kind, "success");
    assert(!process.env.AGENTCFG_DOTENV_SENTINEL);
    assert(!process.env.AGENTCFG_HOME_DOTENV_SENTINEL);
    evidence.checks.host = "PASS";
    stage("host.protocol");
    evidence.protocol = await protocolChecks();
    stage("host.cursor-mocks");
    evidence.cursor_mocks = await cursorMocks();
    save();
    const handle = await ctx.get("agents").create({ sessionId: randomUUID(), meta: { cwd: process.cwd() } });
    const agent = handle.agent;
    evidence.sessionId = agent.session.id;
    agent.session.append("turn/start", { turn: 1 });
    const tools = agent.ctx.get("tools"); const approval = agent.ctx.get("approval");
    const counts = new Map(); const name = "rotom_native_counter";
    const release = tools.register({ name, description: "Temporary native approval counter",
      parameters: { type: "object", properties: { action: { type: "string" } }, required: ["action"] },
      output: { schema: { type: "integer" }, render: (_args, value) => [{ type: "text", text: String(value) }] },
      execute: async args => { counts.set(args.action, (counts.get(args.action) ?? 0) + 1); return counts.get(args.action); } });
    const gate = agent.ctx.on("tools/pre-execute", async (exec, next) => exec.name === name
      ? { kind: "ask", reason: exec.arguments.action } : next(), { prepend: true });
    let late; let answerCalls = 0;
    const answer = agent.ctx.on("approval/request", async (request, next) => {
      if (request.toolName !== name) return next();
      answerCalls++;
      if (request.reason === "no-answer") return next();
      if (request.reason === "handler-throw") throw new Error("synthetic handler failure");
      if (request.reason === "invalid-outcome") return "invalid-outcome";
      if (request.reason === "cancel") return new Promise(resolve => { late = resolve; });
      return request.reason.includes("reject") ? "rejected" : "allowed-once";
    }, { prepend: true });
    const execute = async (action, signal = new AbortController().signal, callId = action + "-" + randomUUID()) => {
      const result = await tools.execute({ callId, name, arguments: { action }, agent, signal });
      return { count: counts.get(action) ?? 0, isError: result.isError };
    };
    evidence.approval = {};
    stage("approval.allow");
    evidence.approval.allow = await execute("allow"); assert.equal(counts.get("allow"), 1);
    save();
    for (const action of ["reject", "no-answer", "handler-throw", "invalid-outcome"]) {
      stage("approval." + action);
      const signal = action === "no-answer" ? AbortSignal.timeout(50) : new AbortController().signal;
      evidence.approval[action] = await execute(action, signal); assert.equal(counts.get(action) ?? 0, 0);
      if (action === "no-answer") {
        assert(signal.aborted, "unanswered native human route must end through caller timeout");
        evidence.approval[action].route = "native human handler delegated; caller timeout cancelled; no human clicked";
        evidence.human_click = "NOT RUN";
        evidence.no_human_carrier = "NOT RUN";
      }
      save();
    }
    stage("approval.never");
    approval.setPolicy(agent, "never"); const before = answerCalls;
    evidence.approval.never = await execute("never"); assert.equal(counts.get("never") ?? 0, 0); assert.equal(answerCalls, before);
    save();
    approval.setPolicy(agent, "ask");
    const cancellation = new AbortController(); const pending = execute("cancel", cancellation.signal);
    stage("approval.cancel-late-allow");
    await waitFor(() => late !== undefined);
    cancellation.abort(); evidence.approval.cancel = await pending; late("allowed-once");
    await new Promise(resolve => setTimeout(resolve, 20)); assert.equal(counts.get("cancel") ?? 0, 0);
    save();
    stage("approval.concurrent");
    const callId = "shared-" + randomUUID();
    const concurrent = await Promise.all([execute("concurrent-allow", undefined, callId), execute("concurrent-reject", undefined, callId)]);
    assert.equal(counts.get("concurrent-allow"), 1); assert.equal(counts.get("concurrent-reject") ?? 0, 0);
    evidence.approval.concurrent = concurrent;
    save();
    stage("approval.guard-deny");
    const guard = tools.guard(exec => exec.name === name ? { kind: "deny", reason: "deterministic deny" } : undefined);
    evidence.approval.guard = await execute("guard"); assert.equal(counts.get("guard") ?? 0, 0);
    save();
    guard(); answer(); gate(); release();
    agent.session.append("turn/end", { turn: 1, reason: { kind: "completed" } });
    stage("audit.flush");
    evidence.audit = auditOf(agent.session.snapshotEvents()); assertAudit(evidence.audit);
    const unanswered = evidence.audit.find(event => event.type === "approval/asked" && event.callId.startsWith("no-answer-"));
    assert.equal(evidence.audit.find(event => event.type === "approval/decided" && event.id === unanswered?.id)?.outcome, "cancelled");
    await ctx.get("sessionPersistence").flush(); await handle.dispose();
    evidence.checks.manual_approval = "PASS"; save();
    const outside = process.env.AGENTCFG_SMOKE_OUTSIDE;
    fs.writeFileSync(outside, "baseline ordinary write"); fs.writeFileSync(outside, "synthetic outside sentinel");
    const link = path.join(process.cwd(), "outside-link"); fs.symlinkSync(outside, link);
    const readonly = path.join(process.cwd(), "readonly.txt"); fs.writeFileSync(readonly, "baseline ordinary write");
    evidence.sandbox = {};
    for (const [label, mode, target, allowed] of [
      ["workspace-write", "workspace-write", path.join(process.cwd(), "allowed.txt"), true],
      ["outside-denied", "workspace-write", outside, false], ["symlink-denied", "workspace-write", link, false],
      ["read-only-denied", "read-only", readonly, false],
    ]) {
      stage("sandbox." + label);
      assert(fs.existsSync(path.dirname(target)) && (allowed || fs.existsSync(target)));
      const script = "const fs=require('node:fs');try{fs.writeFileSync(process.argv[1],'native write');process.exit(0)}catch(e){process.stderr.write(e.code||'ERROR');process.exit(7)}";
      const wrapped = await ctx.get("sandbox").confine([process.execPath, "-e", script, target], { mode, workspaceRoot: process.cwd() }, new AbortController().signal);
      const result = spawnSync(wrapped.argv[0], wrapped.argv.slice(1), { cwd: process.cwd(), env: process.env, encoding: "utf8", timeout: 10000 });
      evidence.sandbox[label] = { exit: result.status, enforcement: wrapped.enforcement, error_code: result.stderr?.trim(),
        classification: result.error || result.signal || result.status === null ? "runner-failure" : result.status === 0 ? "write-allowed" : "permission-denied" };
      assert(!result.error && !result.signal && result.status !== null, "sandbox runner failed");
      assert.equal(wrapped.enforcement, "full");
      if (allowed) assert.equal(result.status, 0);
      else { assert.equal(result.status, 7); assert(["EROFS", "EACCES"].includes(result.stderr.trim()), "denial did not prove write permission enforcement"); }
      assert.equal(fs.readFileSync(outside, "utf8"), "synthetic outside sentinel");
      save();
    }
    evidence.checks.sandbox = "PASS";
    evidence.native_complete = true;
    evidence.stage = "native.complete";
    save(); await booted.shutdown.shutdown(0);
  }
} catch (error) {
  evidence.error = error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "NATIVE_OPERATION_FAILED";
  evidence.error_location = evidence.stage ?? "native.start";
  save();
  if (booted) await booted.shutdown.shutdown(1); else process.exitCode = 1;
}
