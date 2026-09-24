// 只由显式原生验收启动；使用真实 SDK/扩展和 supervisor，模型服务由私人夹具提供。
import { randomUUID, createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, lstatSync, existsSync, readdirSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { launch, privateFile, writePrivate } from "./launch.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { closed, digest, reject } from "./managed-types.ts";

export const nativeSessionScenarios = new Set(["taskkeeper-proxy-fix", "taskkeeper-proxy-second-view", "host-resources", "migration-runtime-conflicts", "permission-denials", "ordinary-cancel", "parent-loss", "readseek-tools", "delegate-presets", "delegate-batch", "taskkeeper-inspect", "taskkeeper-fix", "taskkeeper-second-view",
  "taskkeeper-budget", "taskkeeper-quota", "taskkeeper-missing-result", "taskkeeper-pause-resume", "taskkeeper-stop", "taskkeeper-schedule"]);

async function until(read, ready, seconds = 600) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const value = await read();
    if (ready(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  reject("NATIVE_SCENARIO_TIMEOUT", 5);
}

export async function nativeCommand(session, runner, command, value, allowStopping = false, progress = () => {}) {
  progress("command-" + value.split(" ")[0] + "-started");
  const before = session.messages.length;
  await command.handler(value, runner.createCommandContext());
  const responses = session.messages.slice(before).filter(row => row.role === "custom" && row.customType === "task-keeper:status");
  if (!responses.length) reject("NATIVE_COMMAND_RESULT_UNVERIFIED", 5);
  for (const response of responses) {
    const details = response.details;
    const code = typeof details === "string" ? details : Number.isInteger(details?.exit_code) && details.exit_code !== 0 ? details.code : null;
    if (code !== null) {
      if (allowStopping && code === "JOB_STILL_STOPPING") return false;
      const known = new Set(["JOB_REQUIRES_RECONCILIATION", "POLICY_CHANGED_REQUIRES_RECONCILIATION", "EXECUTION_NOT_RECONCILED", "NO_RETRYABLE_STEP", "RESUME_CONTROL_REVOKED"]);
      progress("command-rejected" + (known.has(code) ? "-" + code : ""));
      reject("NATIVE_COMMAND_REJECTED", 5);
    }
  }
  progress("command-" + value.split(" ")[0] + "-finished");
  return true;
}

export async function nativeUserCLI(runtime, name, args, spawnProcess = spawn) {
  if (!["model-delegate.py", "model-delegate-batch.py"].includes(name)) reject("NATIVE_CLI_UNSUPPORTED", 2);
  return new Promise((resolveDone, rejectDone) => {
    const child = spawnProcess(runtime.supervisor.options.python, ["-B", "-I", join(runtime.runtimeRoot, "supervisor/scripts", name), ...args], {
      cwd: runtime.instanceRoot, env: { HOME: join(runtime.instanceRoot, "user-home"), PATH: process.env.PATH ?? "/usr/bin:/bin", PYTHONDONTWRITEBYTECODE: "1" }, stdio: ["ignore", "pipe", "pipe"] });
    const chunks = []; let bytes = 0, failed = false, killTimer;
    const stop = () => { if (failed) return; failed = true; child.kill(); killTimer = setTimeout(() => child.kill("SIGKILL"), 2000); killTimer.unref?.(); };
    const timer = setTimeout(stop, 30000);
    child.stdout.on("data", chunk => { bytes += chunk.length; if (bytes > 1024 * 1024) stop(); else chunks.push(chunk); });
    child.stderr.on("data", () => {});
    child.once("error", () => { clearTimeout(timer); clearTimeout(killTimer); rejectDone(new Error("NATIVE_CLI_UNAVAILABLE")); });
    child.once("close", code => {
      clearTimeout(timer); clearTimeout(killTimer);
      if (code !== 0 || failed) { rejectDone(new Error("NATIVE_CLI_FAILED")); return; }
      try { resolveDone(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
      catch { rejectDone(new Error("NATIVE_CLI_RESULT_INVALID")); }
    });
  });
}

export async function exerciseNativeSession(host, input, progress = () => {}) {
  if (!nativeSessionScenarios.has(input.scenario)) reject("NATIVE_SCENARIO_UNSUPPORTED", 2);
  const session = host.session, errors = [];
  await session.bindExtensions({ mode: "print", onError: () => errors.push("NATIVE_EXTENSION_ERROR") });
  const active = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (!entry?.manager || entry.manager.getMaxConcurrent() !== 2 || !active?.supervisor) reject("NATIVE_MANAGER_UNVERIFIED", 5);
  const tools = session.getActiveToolNames(), roles = Object.keys(active.manifest.role_bindings);
  if (!tools.includes("Agent") || tools.includes("codex_delegate") || tools.some(name => /^codex_(agent|scout|review)/.test(name))) reject("NATIVE_TOOLS_UNVERIFIED", 5);
  if (active.manifest.plugins.includes("pi-todo") && !tools.includes("todo")) reject("NATIVE_TODO_UNAVAILABLE", 5);
  if (roles.some(name => name.startsWith("codex-"))) reject("NATIVE_RETIREMENT_UNVERIFIED", 5);
  const declared = new Set(active.manifest.allowed_models.map(row => row.provider + "/" + row.model));
  if (host.services.modelRuntime.getModels().some(row => !declared.has(row.provider + "/" + row.id))) reject("NATIVE_MODELS_UNVERIFIED", 5);
  const facts = { sdk_session: true, manager_limit: 2, tools: [...tools].sort(), roles: [...roles].sort(), real_account_used: false, transport: "direct" };
  if (input.scenario === "host-resources" && active.manifest.plugins.includes("pi-todo")) {
    const runner = session.extensionRunner, todo = runner.getToolDefinition("todo"), context = runner.createContext();
    const call = async params => {
      const value = await todo.execute(randomUUID(), params, new AbortController().signal, undefined, context);
      if (value?.isError || value?.details?.error || !Array.isArray(value?.details?.tasks)) reject("NATIVE_TODO_UNVERIFIED", 5);
      return value.details.tasks;
    };
    const subject = "agentcfg native Todo " + randomUUID();
    const created = (await call({ action: "create", subject })).find(row => row.subject === subject);
    if (!created || created.status !== "pending") reject("NATIVE_TODO_UNVERIFIED", 5);
    const finished = (await call({ action: "update", id: created.id, status: "completed" })).find(row => row.id === created.id);
    if (finished?.status !== "completed") reject("NATIVE_TODO_UNVERIFIED", 5);
    const removed = (await call({ action: "delete", id: created.id })).find(row => row.id === created.id);
    if (removed?.status !== "deleted") reject("NATIVE_TODO_UNVERIFIED", 5);
    facts.todo_roundtrip = true;
  }
  if (input.scenario === "parent-loss" && !tools.includes("kernel_task")) {
    if (!entry.external || !active.manifest.model_bindings.scout) reject("NATIVE_DELEGATE_UNAVAILABLE", 5);
    const binding = active.manifest.model_bindings.scout;
    const request = { backend: "pi", mode: "investigate", preset: "scout", task: "Read code.txt without changing it.", cwd: input.project,
      model: { provider_id: binding.provider, model_id: binding.model }, timeout_seconds: 120 };
    const run = await entry.external.submit_delegate({ request_id: randomUUID(), idempotency_key: randomUUID(),
      instance_id: active.owner.instance_id, policy_digest: digest(active.manifest.permission_policy), request_digest: digest(request), backend_request: request });
    if (!run.lease_id) reject("NATIVE_DELEGATE_UNVERIFIED", 5);
    await until(() => active.supervisor.call("inspect", { lease_id: run.lease_id }), lease => lease.state === "running" && !!lease.process_identity, 30);
    writePrivate(join(dirname(input.output), "parent-loss-ready.json"), JSON.stringify({ nonce: input.nonce, runtime_identity: input.runtime_identity,
      facts: { ...facts, child_execution_kind: "external" } }) + "\n");
    await new Promise(() => {});
  }
  if (input.scenario === "ordinary-cancel") {
    const id = entry.manager.spawn(entry.pi, entry.getContext(), "scout", "Read code.txt and report its content without changing it.",
      { description: "Native ordinary cancellation", cwd: input.project, isBackground: true });
    const startedPath = join(dirname(input.output), "model-request-started.json");
    await until(async () => existsSync(startedPath) ? JSON.parse(privateFile(startedPath)) : null,
      value => value?.nonce === input.nonce && value.runtime_identity === input.runtime_identity, 30);
    const record = entry.manager.getRecord(id);
    if (record?.status !== "running" || !record.session?.isStreaming || !entry.manager.abort(id)) reject("NATIVE_ORDINARY_CANCEL_UNVERIFIED", 5);
    // stopped 状态先于异步 SDK 收尾；必须同时观察 promise 和流结束。
    let settled = false;
    Promise.resolve(record.promise).then(() => { settled = true; }, () => { settled = true; });
    await until(async () => settled && !record.session.isStreaming && !entry.manager.hasRunning(), Boolean, 30);
    if (record.status !== "stopped" || errors.length || readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_ORDINARY_CANCEL_UNVERIFIED", 5);
    return { ...facts, ordinary_session_started: true, cancel_after_request_verified: true, sdk_stream_settled: true,
      manager_stopped: true, source_preserved: true, activity_drained: true };
  }
  if (["host-resources", "migration-runtime-conflicts", "permission-denials"].includes(input.scenario)) {
    // 验收控制者显式批准本合成项目的会话提示；每次 IO 仍须通过固定策略与监督准入。
    active.permissionAccess.setMode(session.sessionManager.getSessionId(), "cwd", input.project);
    await session.prompt("Native fixture: read code.txt and report its content without modifying it.");
    const denied = input.scenario === "permission-denials";
    if (!session.getLastAssistantText()?.trim() || !session.messages.some(row => row.role === "toolResult" && row.toolName === "read"
        && (denied ? row.isError === true && row.content?.some(part => part.type === "text" && part.text.includes("PI_CONTROL_REJECTED")) : !row.isError))) reject("NATIVE_PROMPT_UNVERIFIED", 5);
    if (readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_SOURCE_CHANGED", 5);
    if (errors.length) reject("NATIVE_EXTENSION_ERROR", 5);
    return { ...facts, model_roundtrip: true, ...(denied ? { guarded_denial: true } : { guarded_read: true }), source_preserved: true };
  }
  if (input.scenario === "readseek-tools") {
    // ReadSeek九工具真实宿主流程：检索/搜索/定义/引用/视图/读取/写入/编辑/符号重命名经监督控制器与原生worker，
    // 越界写入必须被拒；源项目与git元数据不得被改动。
    // 扩展在before_agent_start才激活readSeek工具；先热身一轮再核对活动工具名。
    if (!active.manifest.plugins.includes("pi-readseek")) reject("NATIVE_READSEEK_UNAVAILABLE", 5);
    active.permissionAccess.setMode(session.sessionManager.getSessionId(), "cwd", input.project);
    await session.prompt("Native readseek fixture: acknowledge readiness without calling any tool.");
    const readseekNames = session.getActiveToolNames().filter(name => name.startsWith("readSeek_"));
    if (!readseekNames.length) reject("NATIVE_READSEEK_UNAVAILABLE", 5);
    const denied = join(dirname(input.project), "local.toml");
    const steps = [
      { prompt: "Native readseek: use readSeek_grep to find 'original' in this project.", tool: "readSeek_grep",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("code.txt")) },
      { prompt: "Native readseek: use readSeek_search to search Python AST for function definitions with pattern 'def $NAME($$$ARGS):' plus its body line in this project.", tool: "readSeek_search",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("test_bounded_change")) },
      { prompt: "Native readseek: use readSeek_digest to read code.txt.", tool: "readSeek_digest",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("original")) },
      { prompt: "Native readseek: use readSeek_view to view the structure of sample.pdf.", tool: "readSeek_view",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("sample") && JSON.stringify(row.content).includes("Page 1")) },
      { prompt: "Native readseek: use readSeek_write to create notes.py with content 'draft one', a variable value = 1, print(value), and a function helper returning value.", tool: "readSeek_write",
        verify: rows => rows.some(row => !row.isError) && readFileSync(join(input.project, "notes.py"), "utf8").includes("draft one") },
      { prompt: "Native readseek: use readSeek_edit to replace 'draft one' with 'draft two' in notes.py.", tool: "readSeek_edit",
        verify: rows => rows.some(row => !row.isError) && readFileSync(join(input.project, "notes.py"), "utf8").includes("draft two") },
      { prompt: "Native readseek: use readSeek_def to find the definition of symbol 'helper' in notes.py.", tool: "readSeek_def",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("notes.py") && JSON.stringify(row.content).includes("helper")) },
      { prompt: "Native readseek: use readSeek_refs to find all references to symbol 'value' in notes.py.", tool: "readSeek_refs",
        verify: rows => rows.some(row => !row.isError && JSON.stringify(row.content).includes("notes.py") && JSON.stringify(row.content).includes("value")) },
      { prompt: "Native readseek: use readSeek_rename to rename symbol value to renamed at line 2 of notes.py, then verify the definition, the print call and helper's returned reference are all updated.", tool: "readSeek_rename",
        verify: rows => {
          if (!rows.some(row => !row.isError)) return false;
          const content = readFileSync(join(input.project, "notes.py"), "utf8");
          // 验证符号重命名：赋值、print 调用与 helper 返回引用都要更新。
          return content.includes("renamed = 1") && content.includes("print(renamed)") && content.includes("return renamed")
            && !content.includes("value = 1") && !content.includes("print(value)");
        } },
      { prompt: "Native readseek: attempt readSeek_write on the denied local.toml and confirm it is rejected.", tool: "readSeek_write",
        verify: rows => rows.some(row => row.isError === true) },
    ];
    for (const step of steps) {
      progress("readseek-" + step.tool);
      const before = session.messages.length;
      await session.prompt(step.prompt);
      const rows = session.messages.slice(before).filter(row => row.role === "toolResult" && row.toolName === step.tool);
      if (!step.verify(rows)) {
        // 失败时保留原始工具结果供审计，不猜原因。
        writePrivate(join(dirname(input.output), "readseek-failed-step.json"), JSON.stringify({ step: step.tool, rows }) + "\n");
        reject("NATIVE_READSEEK_UNVERIFIED", 5);
      }
    }
    if (readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_SOURCE_CHANGED", 5);
    if (existsSync(denied) && readFileSync(denied, "utf8").includes("must not land")) reject("NATIVE_READSEEK_DENIAL_UNVERIFIED", 5);
    const entries = readdirSync(input.project).filter(name => name !== ".git" && name !== ".readseek").sort();
    if (JSON.stringify(entries) !== JSON.stringify(["code.txt", "notes.py", "sample.pdf", "test_native_fixture.py"])) reject("NATIVE_READSEEK_STRAY_FILES", 5);
    if (errors.length) reject("NATIVE_EXTENSION_ERROR", 5);
    return { ...facts, grep_verified: true, search_verified: true, read_verified: true, view_verified: true, write_verified: true, edit_verified: true,
      def_verified: true, refs_verified: true, rename_verified: true, denied_write_rejected: true, source_preserved: true, activity_drained: true };
  }
  if (input.scenario === "delegate-presets") {
    const presets = ["general", "context", "challenge", "plan", "research", "review", "scout"];
    if (!tools.includes("model_delegate") || presets.some(name => !active.manifest.options.model_delegate?.presets?.includes(name))) reject("NATIVE_DELEGATE_UNAVAILABLE", 5);
    active.permissionAccess.setMode(session.sessionManager.getSessionId(), "cwd", input.project);
    const runs = new Set();
    for (const preset of presets) {
      progress("delegate-preset-" + preset);
      const before = session.messages.length;
      await session.prompt("Native delegate preset " + preset + ": delegate a readonly inspection of code.txt.");
      const results = session.messages.slice(before).filter(row => row.role === "toolResult" && row.toolName === "model_delegate");
      const result = results[0]?.details;
      if (results.length !== 1 || results[0].isError || result?.state !== "completed" || result.verification !== "verified-execution"
          || result.process_terminated !== true || result.resources_reclaimed !== true || result.task_acceptance !== "unverified"
          || !result.artifact_ref || !result.result_excerpt?.trim() || runs.has(result.run_id)) reject("NATIVE_DELEGATE_UNVERIFIED", 5);
      runs.add(result.run_id);
    }
    if (errors.length || readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_DELEGATE_UNVERIFIED", 5);
    await until(async () => entry.manager.hasRunning(), running => !running, 30);
    return { ...facts, presets_verified: presets, delegate_runs: runs.size, verified_execution_only: true, source_preserved: true, activity_drained: true };
  }
  if (input.scenario === "delegate-batch") {
    if (!tools.includes("model_delegate")) reject("NATIVE_DELEGATE_UNAVAILABLE", 5);
    const binding = active.manifest.model_bindings.scout, batchId = "native-" + randomUUID();
    const items = ["general", "review", "scout"].map(preset => ({ backend: "pi", mode: "investigate", preset,
      task: "Read code.txt and report its content without modifying files.", cwd: input.project,
      model: { provider_id: binding.provider, model_id: binding.model }, timeout_seconds: 120, context_artifact: null, feedback_required: false }));
    const path = join(dirname(input.output), "delegate-batch-input.json"); writePrivate(path, JSON.stringify(items) + "\n");
    const call = (action, extra = []) => nativeUserCLI(active, "model-delegate-batch.py", [action, "--instance", input.instance_root, "--batch-id", batchId, ...extra]);
    const submitted = await call("submit", ["--input", path]), repeated = await call("submit", ["--input", path]);
    if (submitted.dispatch_ids?.length !== 3 || JSON.stringify(submitted.dispatch_ids) !== JSON.stringify(repeated.dispatch_ids)) reject("NATIVE_BATCH_IDEMPOTENCY_UNVERIFIED", 5);
    let peak = 0;
    const result = await until(async () => {
      peak = Math.max(peak, entry.manager.listAgents().filter(row => row.status === "running").length);
      return call("status");
    }, row => ["completed", "partial", "canceled"].includes(row.state) && !entry.manager.hasRunning());
    if (result.state !== "completed" || result.result_refs?.length !== 3 || new Set(result.result_refs).size !== 3 || peak > 2
        || readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_BATCH_UNVERIFIED", 5);
    await until(async () => entry.manager.hasRunning(), running => !running, 30);
    return { ...facts, batch_results: 3, batch_idempotency_verified: true, user_cli_verified: true, source_preserved: true, activity_drained: true, peak_manager_running: peak };
  }
  const runner = session.extensionRunner, tool = runner.getToolDefinition("kernel_task"), command = runner.getCommand("orch");
  if (!tool || !command || !tools.includes("kernel_task")) reject("NATIVE_TASKKEEPER_UNAVAILABLE", 5);
  const status = async id => (await tool.execute(randomUUID(), { action: "status", ...(id ? { jobId: id } : {}) },
    new AbortController().signal, undefined, runner.createContext())).details;
  const control = (value, allowStopping = false) => nativeCommand(session, runner, command, value, allowStopping, progress);
  const previous = new Set((await status()).map(row => row.id));
  const fixing = ["taskkeeper-fix", "taskkeeper-proxy-fix"].includes(input.scenario), scheduled = input.scenario === "taskkeeper-schedule";
  const notBefore = new Date(Date.now() + 1500).toISOString();
  const extra = ["taskkeeper-second-view", "taskkeeper-proxy-second-view"].includes(input.scenario) ? " --second-opinion" : scheduled ? " --not-before " + notBefore : "";
  await control((scheduled ? "schedule " : "") + (fixing ? "fix" : "inspect") + extra + " -- Native fixture: inspect code.txt" + (fixing ? " and change its content to changed" : ""));
  const rows = await status(), created = rows.filter(row => !previous.has(row.id));
  if (created.length !== 1) reject("NATIVE_TASK_SUBMISSION_UNVERIFIED", 5);
  const id = created[0].id;
  progress("task-submitted");
  if (scheduled) {
    const observed = await status(id);
    if (!observed.schedule || Date.parse(notBefore) > Date.now() && entry.manager.hasRunning()) reject("NATIVE_SCHEDULE_UNVERIFIED", 5);
  }
  if (["taskkeeper-pause-resume", "taskkeeper-stop", "parent-loss"].includes(input.scenario)) {
    await until(async () => {
      const running = [...active.managedBackend.runs.entries()].find(([, run]) => run.descriptor.task_id === id && run.descriptor.role_id === "task-keeper-reader");
      return running ? active.supervisor.call("inspect", { lease_id: running[0] }) : null;
    }, lease => lease?.state === "running" && !!lease.process_identity);
    progress("worker-running");
    if (input.scenario === "parent-loss") {
      writePrivate(join(dirname(input.output), "parent-loss-ready.json"), JSON.stringify({ nonce: input.nonce, runtime_identity: input.runtime_identity, facts }) + "\n");
      await new Promise(() => {});
    }
    await control((input.scenario === "taskkeeper-stop" ? "stop " : "pause ") + id);
    const paused = await status(id);
    if (!["PAUSED", "CANCELLED"].includes(paused.status)) reject("NATIVE_PAUSE_UNVERIFIED", 5);
    // pause让当前步骤收尾；它不同于stop，冷环境下不能用30秒硬停止窗口判断。
    await until(async () => entry.manager.hasRunning(), running => !running, input.scenario === "taskkeeper-pause-resume" ? 180 : 30);
    progress("manager-drained");
    if (input.scenario === "taskkeeper-stop") return { ...facts, stop_requested: true, worker_started_before_control: true, activity_drained: true };
    // manager 结束与工作流收尾不是同一瞬间；只对明确的“仍在停止”短暂等待重试。
    await until(() => control("resume " + id, true), resumed => resumed, 30);
  }
  const negative = ["taskkeeper-budget", "taskkeeper-missing-result"].includes(input.scenario);
  const result = await until(() => status(id), value => ["COMPLETED", "BLOCKED", "PARTIAL", "CANCELLED"].includes(value.status)
    || input.scenario === "taskkeeper-quota" && value.status === "WAITING_QUOTA");
  progress("task-observed-" + result.status.toLowerCase());
  if (input.scenario === "taskkeeper-quota") {
    if (result.status !== "WAITING_QUOTA") reject("NATIVE_QUOTA_UNVERIFIED", 5);
    await control("stop " + id);
    await until(async () => entry.manager.hasRunning(), running => !running, 30);
    return { ...facts, quota_wait_observed: true, activity_drained: true };
  }
  if (negative) {
    if (result.status !== "BLOCKED" || !result.failureGroups?.length) reject("NATIVE_REJECTION_UNVERIFIED", 5);
    if (input.scenario === "taskkeeper-budget" && !result.failureGroups.some(row => row.code === "BUDGET_DENIED")) reject("NATIVE_BUDGET_UNVERIFIED", 5);
  } else if (result.status !== "COMPLETED" || !result.receipt || result.receipt.snapshot !== result.snapshot) reject("NATIVE_RECEIPT_UNVERIFIED", 5);
  if (readFileSync(join(input.project, "code.txt"), "utf8") !== "original\n") reject("NATIVE_SOURCE_CHANGED", 5);
  if (fixing && (readFileSync(join(result.cwd, "code.txt"), "utf8") !== "changed\n" || !result.checks?.length)) reject("NATIVE_FIX_UNVERIFIED", 5);
  if (["taskkeeper-second-view", "taskkeeper-proxy-second-view"].includes(input.scenario) && result.secondOpinion?.agreementCurrent !== true) reject("NATIVE_SECOND_VIEW_UNVERIFIED", 5);
  if (scheduled && (!Number.isSafeInteger(result.schedule?.admittedAt) || result.schedule.admittedAt < Date.parse(notBefore))) reject("NATIVE_SCHEDULE_UNVERIFIED", 5);
  if (errors.length) reject("NATIVE_EXTENSION_ERROR", 5);
  await until(async () => entry.manager.hasRunning(), running => !running, 30);
  return { ...facts, job_status: result.status, receipt_observed: !!result.receipt, source_preserved: true,
    ...(input.scenario === "taskkeeper-budget" ? { budget_denial_observed: true } : {}),
    checks: result.checks?.length ?? 0, activity_drained: true, ...(scheduled ? { scheduled_timestamp_verified: true } : {}),
    ...(["taskkeeper-second-view", "taskkeeper-proxy-second-view"].includes(input.scenario) ? { second_view_verified: true } : {}),
    ...(input.scenario === "taskkeeper-pause-resume" ? { resumed: true, worker_started_before_control: true } : {}) };
}

export function validateNativeProvider(provider, input, manifest, environment) {
  const endpoint = new URL(provider.baseUrl);
  const variable = /^\$(AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16})$/.exec(provider.apiKey)?.[1];
  const proxy = ["taskkeeper-proxy-fix", "taskkeeper-proxy-second-view"].includes(input.scenario);
  if (endpoint.protocol !== "http:" || endpoint.pathname !== "/v1" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash
      || !variable || environment[variable] !== "synthetic-native-key") reject("NATIVE_ACCOUNT_INPUT_DENIED", 4);
  if (proxy) {
    const route = manifest.options.network?.routes?.["native-direct"];
    const credential = "AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update("native-direct").digest("hex").slice(0, 16).toUpperCase();
    if (endpoint.hostname !== "agentcfg-native.invalid" || endpoint.port || route?.mode !== "proxy"
        || route.proxy_url !== "http://127.0.0.1:" + input.provider_port || route.credential_ref !== "secret:native-proxy-key"
        || JSON.stringify(route.provider_ids) !== '["native-fixture"]' || environment[credential] !== "Bearer synthetic-proxy-key") reject("NATIVE_ACCOUNT_INPUT_DENIED", 4);
  } else if (endpoint.hostname !== "127.0.0.1" || endpoint.port !== String(input.provider_port)) reject("NATIVE_ACCOUNT_INPUT_DENIED", 4);
}

async function main(path) {
  if (!isAbsolute(path)) reject("NATIVE_INPUT_PATH", 2);
  const input = JSON.parse(privateFile(path));
  closed(input, ["schema_version", "nonce", "scenario", "instance_root", "project", "runtime_identity", "output", "provider_port"]);
  if (input.schema_version !== 1 || !/^[a-f0-9]{64}$/.test(input.nonce) || !nativeSessionScenarios.has(input.scenario)
      || !Number.isSafeInteger(input.provider_port) || input.provider_port < 1024 || input.provider_port > 65535
      || input.output !== join(dirname(path), "scenario-result.json")) reject("NATIVE_INPUT_INVALID", 2);
  const runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), ".."), installed = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  const engine = typeof globalThis.Bun !== "undefined" ? "bun" : "node", version = engine === "bun" ? globalThis.Bun.version : process.version;
  if (installed.runtime_identity !== input.runtime_identity || installed.engine !== engine || installed.toolchains[engine] !== version) reject("NATIVE_ENGINE_UNVERIFIED", 5);
  if (process.env.HOME !== join(input.instance_root, "user-home") || process.env.PI_CODING_AGENT_DIR !== join(input.instance_root, "pi-home")) reject("NATIVE_ENVIRONMENT_UNVERIFIED", 5);
  const manifest = JSON.parse(privateFile(join(input.instance_root, "pi-home/agentcfg-manifest.json")));
  if (!manifest.allowed_models?.length || manifest.allowed_models.some(row => !/^agentcfg-native-[a-z-]+$/.test(row.model))
      || existsSync(join(input.instance_root, "pi-home/auth.json"))) reject("NATIVE_ACCOUNT_INPUT_DENIED", 4);
  const models = JSON.parse(privateFile(join(input.instance_root, "pi-home/models.json")));
  for (const provider of Object.values(models.providers ?? {})) validateNativeProvider(provider, input, manifest, process.env);
  const supervisor = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const sdk = await import(pathToFileURL(resolve(runtimeRoot, installed.entrypoint)).href);
  let facts, failure;
  const progress = phase => writePrivate(join(dirname(path), "scenario-progress.json"), JSON.stringify({ phase, at: new Date().toISOString() }) + "\n");
  try {
    const result = await launch({ sdk: { ...sdk, runPrintMode: async host => { facts = await exerciseNativeSession(host, input, progress); return 0; } },
      manifest, installed, instanceRoot: input.instance_root, runtimeRoot, cwd: input.project, engine, supervisor, argv: ["--print"] });
    progress("launch-settled");
    if (result.code !== 0 || !facts) reject("NATIVE_SCENARIO_UNVERIFIED", 5);
  } catch (error) { failure = typeof error?.message === "string" && /^NATIVE_[A-Z_]+$/.test(error.message) ? error.message : "NATIVE_SCENARIO_FAILED"; }
  const parent = lstatSync(dirname(input.output));
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid?.() || (parent.mode & 0o777) !== 0o700) reject("NATIVE_OUTPUT_DIRECTORY", 4);
  writeFileSync(input.output, JSON.stringify({ schema_version: 1, nonce: input.nonce, scenario: input.scenario,
    runtime_identity: input.runtime_identity, status: failure ? "failed" : "passed", failure_code: failure ?? null, facts: facts ?? null }) + "\n", { flag: "wx", mode: 0o600 });
  return failure ? 5 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = process.argv[2] === "--input" && process.argv.length === 4 ? await main(process.argv[3]) : 2; }
  catch { process.stderr.write("原生验收未完成；检查私人实例、冻结运行包和监督状态。\n"); process.exitCode = 5; }
}
