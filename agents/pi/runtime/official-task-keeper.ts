// Full受信initializer独占issuer；不给global runtime/model参数提供注册能力。
import { join, dirname, relative, isAbsolute, sep } from "node:path";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";
import { captureOperationInput } from "./private-operation-input.ts";
import { TaskKeeperDelegateAdapter } from "./official-task-keeper-delegate.ts";
const fail = code => { throw new Error(code); };
const fields = ["schema_version", "profile_id", "runtime_identity", "slice_identity", "lock_identity", "capability_projection", "provider_projection", "source_projection", "config_identity", "policy_digest", "checker_identity"];
export function createOfficialTaskKeeper({ manifest, installed, runtimeRoot, instanceRoot, cwd, sessionManager,
  supervisor, issuer, configurationSnapshot, semanticModelDescriptions, policySnapshot, importCore = url => import(url) }) {
  if (manifest.profile_id !== "pi-full" || !manifest.plugins.includes("task-keeper")
      || manifest.plugin_capabilities?.["task-keeper"]?.capability_id !== "task-workflow"
      || !manifest.options.task_keeper?.enabled || typeof issuer?.open !== "function" || typeof issuer?.retire !== "function") fail("DELEGATE_TASK_ISSUER_UNAVAILABLE");
  const fixed = structuredClone(manifest), install = structuredClone(installed), sessionId = sessionManager.getSessionId();
  let retired = false, pending, store, service, failure = false, contract, publicConfig;
  const check = async () => {
    if (retired || sessionManager.getSessionId() !== sessionId) fail("DELEGATE_TASK_SOURCE_STALE");
    policySnapshot();
    const current = await configurationSnapshot();
    if (publicConfig === undefined) publicConfig = captureOperationInput(current).value;
    else if (!isDeepStrictEqual(current, publicConfig)) fail("DELEGATE_TASK_SOURCE_STALE");
  };
  const initialize = ctx => pending ??= (async () => {
    if (retired || ctx.sessionManager.getSessionId() !== sessionId || ctx.cwd !== cwd) fail("DELEGATE_TASK_SOURCE_STALE");
    policySnapshot();
    const row = install.resources.extensions.filter(row => row.capability_id === "task-workflow");
    if (row.length !== 1) fail("DELEGATE_TASK_SOURCE_UNAVAILABLE");
    const entry = realpathSync(join(runtimeRoot, row[0].path)), root = realpathSync(runtimeRoot);
    const tail = relative(root, entry);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep) || !entry.endsWith("/@agentcfg/pi-task-keeper/index.mjs")) fail("DELEGATE_TASK_SOURCE_UNAVAILABLE");
    const core = await importCore(pathToFileURL(join(dirname(entry), "core.mjs")).href);
    if (retired || typeof core.Store !== "function" || typeof core.TaskServiceCore !== "function"
        || typeof core.readConfigForDirectory !== "function") fail("DELEGATE_TASK_SOURCE_UNAVAILABLE");
    contract = await supervisor.call("delegate_runtime_contract_v3", {});
    if (!contract || Object.keys(contract).sort().join() !== [...fields].sort().join() || contract.schema_version !== 3
        || contract.profile_id !== "pi-full" || contract.runtime_identity !== install.runtime_identity
        || contract.slice_identity !== install.slice_identity || contract.lock_identity !== install.lock_identity
        || contract.checker_identity !== "delegate-runtime-contract-v3") fail("DELEGATE_TASK_CONTRACT_INVALID");
    if (retired) fail("DELEGATE_TASK_SOURCE_STALE");
    const configPath = join(instanceRoot, "pi-home/task-keeper/config.json"), config = core.readConfigForDirectory(configPath, cwd);
    store = new core.Store(join(instanceRoot, "pi-home/task-keeper"));
    service = new core.TaskServiceCore(ctx.pi ?? { appendEntry: ctx.appendEntry }, store, config, ctx, () => {},
      path => core.readConfigForDirectory(configPath, path), {}, ({ owner, config }) => new TaskKeeperDelegateAdapter({
        store, owner, config, manifest: fixed, installed: install, supervisor, issuer, policySnapshot,
        async semanticContext() {
          await check();if(typeof semanticModelDescriptions!=="function")fail("INPUT_SNAPSHOT_MODEL_METADATA_UNAVAILABLE");
          const descriptors=captureOperationInput(await semanticModelDescriptions()).value;await check();
          return {configuration:captureOperationInput(await configurationSnapshot()).value,models:descriptors};
        },
        runtimeContract() {
          if (retired) fail("DELEGATE_TASK_SOURCE_STALE");
          policySnapshot(); return structuredClone(contract);
        } }));
    if (retired) fail("DELEGATE_TASK_SOURCE_STALE");
    return service;
  })().catch(() => { failure = true; throw new Error("DELEGATE_TASK_INITIALIZER_UNAVAILABLE"); });
  let pi;
  const factory = api => {
    pi = api;
    api.on("session_start", async (_event, ctx) => {
      try { await initialize({ ...ctx, pi: api }); } catch { /* 可选workflow失败不能关闭普通编辑会话。 */ }
    });
    api.on("session_shutdown", async () => close());
  };
  const tool = { name: "kernel_task", label: "Task Keeper", description: "Readonly workflow candidate. A model cannot authorize implement/worktree writes; missing maintenance or strict budget qualification is unavailable.",
    parameters: { type: "object", additionalProperties: false, required: ["action"], properties: {
      action: { type: "string", enum: ["submit", "status", "cancel"] }, goal: { type: "string", maxLength: 4096 }, job_id: { type: "string", maxLength: 128 } } },
    async execute(_id, input, signal, _update, ctx) {
      try {
        const args = captureOperationInput(input).value;
        if (!args || Object.keys(args).some(key => !["action", "goal", "job_id"].includes(key)) || signal?.aborted) fail("DELEGATE_TASK_INPUT_INVALID");
        await check();
        if (!ctx || !pi || failure) fail("DELEGATE_TASK_INITIALIZER_UNAVAILABLE");
        const active = await initialize({ ...ctx, pi }); await check();
        let result;
        if (args.action === "submit" && typeof args.goal === "string" && args.goal.trim() && args.job_id === undefined) {
          // 原TaskService会经原maintenance/workspace入口，不把普通文件批准当Git写许可。
          result = active.submit("inspect", args.goal);
        } else if (args.action === "status" && typeof args.job_id === "string" && args.goal === undefined) result = await active.inspect(args.job_id);
        else if (args.action === "cancel" && typeof args.job_id === "string" && args.goal === undefined) { active.pause(args.job_id, true); result = active.get(args.job_id); }
        else fail("DELEGATE_TASK_INPUT_INVALID");
        await check();
        // 任务正文/私有token不复制进公开状态。
        const status = { id: result.id, status: result.status, reason: result.reason,
          ...(result.evidence?{evidence:{currentness:result.evidence.currentness,checkedAt:result.evidence.checkedAt,
            counts:result.evidence.summary?Object.fromEntries(["total","current","stale","invalid","failed","unknown"].map(key=>[key,result.evidence.summary[key]])):null}}:{}) };
        return { content: [{ type: "text", text: JSON.stringify(status) }], details: status, isError: result.status === "FAILED" || result.status === "BLOCKED" };
      } catch { return { content: [{ type: "text", text: "DELEGATE_TASK_UNAVAILABLE" }], details: { code: "DELEGATE_TASK_UNAVAILABLE" }, isError: true }; }
    } };
  let closing;
  const close = () => closing ??= (async () => {
    retired = true;
    try { if (pending) await pending.catch(() => {}); await service?.dispose(); }
    finally { store?.close(); }
  })();
  return Object.freeze({ tool, factory, retire() { retired = true; }, close });
}
