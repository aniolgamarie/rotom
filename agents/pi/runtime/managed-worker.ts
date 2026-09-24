// fresh worker 的 SDK 边界。调用者必须提供已认证 transport、受限工具和监督通道。
// 本模块导入不启动 SDK；只有显式执行函数会创建一个无扩展的内存 session。
import { createHash, randomUUID } from "node:crypto";
import { assertDescriptor, canonical, clone, closed, digest, isProtocolError, list, reject, sha, text } from "./managed-types.ts";

const toolsAllowed = new Set(["tk_read", "tk_find", "tk_grep", "tk_ls", "tk_write", "tk_edit", "structured_output"]);
const managerKeys = [Symbol.for("pi-subagents:manager"), Symbol.for("agentcfg.pi.managed.v1")];

export function validateWorkerInput(input) {
  closed(input, ["descriptor", "context"]);
  assertDescriptor(input.descriptor);
  const descriptor = input.descriptor, context = input.context;
  closed(context, ["schema_version", "manager_run_id", "lease_id", "prompt", "role", "model", "route", "root_bindings", "artifacts", "result_schema", "database", "minimum_remaining"]);
  if (!Number.isSafeInteger(context.minimum_remaining) || context.minimum_remaining < 0) reject();
  closed(context.database, ["root", "filename", "owner"]);
  closed(context.database.owner, ["scopeId", "token", "epoch"]);
  if (!text(context.database.root) || !context.database.root.startsWith("/") || context.database.filename !== "runtime.db"
      || !text(context.database.owner.scopeId) || !text(context.database.owner.token) || !Number.isSafeInteger(context.database.owner.epoch)
      || context.database.owner.epoch < 1) reject("WORKER_DATABASE_BINDING", 4);
  closed(context.role, ["id", "digest", "definition", "system_prompt", "tools"]);
  closed(context.model, ["provider_id", "model_id", "model_digest", "api"]);
  closed(context.route, ["id", "type", "base_url", "proxy_url"]);
  if (context.schema_version !== 1 || ![context.manager_run_id, context.lease_id, context.prompt, context.role.system_prompt].every(text)
      || context.role.id !== descriptor.role_id || context.role.digest !== descriptor.role_digest || !text(context.role.definition)
      || createHash("sha256").update(context.role.definition).digest("hex") !== descriptor.role_digest || !list(context.role.tools)
      || canonical(context.role.tools) !== canonical(descriptor.allowed_tools)
      || descriptor.allowed_tools.some(name => !toolsAllowed.has(name))
      || context.model.provider_id !== descriptor.provider_id || context.model.model_id !== descriptor.model_id
      || context.model.model_digest !== descriptor.model_digest || context.model.api !== "openai-completions"
      || context.route.id !== descriptor.route_id || !["direct", "proxy"].includes(context.route.type)
      || !context.root_bindings || Object.getPrototypeOf(context.root_bindings) !== Object.prototype
      || !context.artifacts || Object.getPrototypeOf(context.artifacts) !== Object.prototype
      || digest(context.result_schema) !== descriptor.result_schema_digest) reject("WORKER_BINDING_MISMATCH", 5);
  for (const root of Object.values(context.root_bindings)) {
    closed(root, ["path", "identity"]);
    if (!text(root.path) || !root.path.startsWith("/") || !sha(root.identity)) reject("WORKER_BINDING_MISMATCH", 5);
  }
  if ([...descriptor.read_roots, ...descriptor.write_roots].some(root => !Object.hasOwn(context.root_bindings, root))
      || Object.keys(context.artifacts).some(id => !descriptor.allowed_artifact_ids.includes(id))) reject("WORKER_BINDING_MISMATCH", 5);
  let base, proxy;
  try { base = new URL(context.route.base_url); proxy = context.route.proxy_url === null ? null : new URL(context.route.proxy_url); }
  catch { reject("WORKER_ROUTE_INVALID", 2); }
  if (!["http:", "https:"].includes(base.protocol) || base.username || base.password || base.search || base.hash
      || context.route.type === "direct" && proxy !== null || context.route.type === "proxy" && !proxy
      || proxy && (!["http:", "https:"].includes(proxy.protocol) || proxy.username || proxy.password || proxy.search || proxy.hash)) reject("WORKER_ROUTE_INVALID", 2);
  return clone(input);
}

export function workerLoader(sdk, role) {
  const extensions = { extensions: [], errors: [], runtime: sdk.createExtensionRuntime() };
  return Object.freeze({
    getExtensions: () => extensions,
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => role.system_prompt,
    getSystemPromptSource: () => undefined,
    getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [],
    extendResources: () => reject("WORKER_RESOURCE_DISCOVERY_DISABLED", 5),
    reload: async () => {},
  });
}

export async function runManagedWorker({ sdk, input, agentDir, modelRuntime, transport, tools, supervisor, report, signal, observation,
    now = () => Date.now() }) {
  const { descriptor, context } = validateWorkerInput(input);
  if (sdk.parseFrontmatter(context.role.definition).body.trim() !== context.role.system_prompt) reject("WORKER_ROLE_MISMATCH", 5);
  if (managerKeys.some(key => globalThis[key] !== undefined)) reject("WORKER_MANAGER_FORBIDDEN", 5);
  if (!transport || transport.api !== "openai-completions" || transport.certified !== true || typeof transport.bind !== "function"
      || transport.model_digest !== descriptor.model_digest || transport.route_id !== descriptor.route_id) reject("UNSUPPORTED_TRANSPORT", 5);
  if (!Array.isArray(tools) || new Set(tools.map(tool => tool.name)).size !== tools.length
      || canonical(tools.map(tool => tool.name).sort()) !== canonical([...descriptor.allowed_tools].sort())
      || tools.some(tool => typeof tool.execute !== "function")) reject("WORKER_TOOLS_MISMATCH", 5);
  let deadlineReached = false;
  const authorize = async () => {
    if (signal?.aborted) reject("GRANT_REVOKED", 4);
    if (deadlineReached || now() >= Date.parse(descriptor.deadline)) reject("DEADLINE_EXCEEDED", 4);
    const result = await supervisor.call("authorize", { lease_id: context.lease_id, grant_generation: descriptor.grant_generation });
    if (result.valid !== true || result.grant_generation !== descriptor.grant_generation) reject("GRANT_STALE", 4);
  };
  await authorize();
  const model = modelRuntime.getModel(descriptor.provider_id, descriptor.model_id);
  if (!model || model.provider !== descriptor.provider_id || model.id !== descriptor.model_id || model.api !== "openai-completions") reject("UNBOUND_MODEL", 2);
  if (descriptor.thinking !== "off" && model.reasoning !== true) reject("THINKING_LEVEL_UNSUPPORTED", 2);
  const bound = await transport.bind(modelRuntime, { descriptor, context, authorize });
  if (!bound || typeof bound.close !== "function") reject("UNSUPPORTED_TRANSPORT", 5);
  const active = new Set(), producer = randomUUID();
  let candidateDigest = descriptor.snapshot_digest, mutationSequence = 0;
  let sequence = 0, session, reportTail = Promise.resolve();
  const publish = (phase, resultDigest = null) => {
    const event = { task_id: descriptor.task_id, step_id: descriptor.step_id, attempt_id: descriptor.attempt_id,
      manager_run_id: context.manager_run_id, producer_id: producer, sequence: ++sequence, event_id: randomUUID(), phase,
      request_id: null, ordinal: null, usage_id: null, process_identity: null,
      active_tool_ids: [...active], external_work_ids: [], candidate_digest: candidateDigest,
      result_digest: resultDigest, termination_confirmed: false };
    reportTail = reportTail.then(() => report({ event }));
    return reportTail;
  };
  const customTools = tools.map(tool => ({ ...tool, execute: async (...args) => {
    await authorize();
    const id = typeof args[0] === "string" ? args[0] : randomUUID();
    active.add(id); await publish("tool_started");
    try {
      const result = await tool.execute(...args);
      if (["tk_write", "tk_edit"].includes(tool.name)) {
        const details = result.details;
        if (!sha(details?.candidate_digest) || !Number.isSafeInteger(details?.mutation_sequence) || details.mutation_sequence < 1) reject("MUTATION_EVIDENCE_MISSING", 5);
        if (details.mutation_sequence > mutationSequence) { candidateDigest = details.candidate_digest; mutationSequence = details.mutation_sequence; }
        else if (details.mutation_sequence === mutationSequence && candidateDigest !== details.candidate_digest) reject("MUTATION_EVIDENCE_CONFLICT", 4);
      }
      observation?.tool(tool.name, id, args[1], result);
      return result;
    } catch (error) { observation?.toolError(tool.name, id, error.code); throw error; }
    finally { active.delete(id); await publish("tool_settled"); }
  } }));
  const stop = () => { void session?.abort().catch(() => {}); };
  let timer;
  try {
    const settingsManager = sdk.SettingsManager.inMemory({ compaction: { enabled: false },
      retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0 } }, packages: [], extensions: [], skills: [], prompts: [], themes: [] });
    const created = await sdk.createAgentSession({ cwd: descriptor.cwd, agentDir, modelRuntime, model,
      thinkingLevel: descriptor.thinking, scopedModels: [{ model }], settingsManager,
      resourceLoader: workerLoader(sdk, context.role), sessionManager: sdk.SessionManager.inMemory(descriptor.cwd),
      noTools: "builtin", tools: [...descriptor.allowed_tools], customTools });
    session = created.session;
    if (session.thinkingLevel !== descriptor.thinking) reject("THINKING_LEVEL_UNSUPPORTED", 2);
    if (created.modelFallbackMessage || canonical(session.getActiveToolNames().sort()) !== canonical([...descriptor.allowed_tools].sort())) reject("WORKER_SESSION_MISMATCH", 5);
    session.setAutoCompactionEnabled(false); session.setAutoRetryEnabled(false);
    // 动态工具选择、角色切换和资源 reload 都不能扩大这里的 allowlist。
    session.setActiveTools = names => {
      if (canonical([...names].sort()) !== canonical([...descriptor.allowed_tools].sort())) reject("WORKER_TOOLS_MISMATCH", 5);
    };
    signal?.addEventListener("abort", stop, { once: true });
    timer = setTimeout(() => { deadlineReached = true; stop(); }, Math.max(1, Math.min(2147483647, Date.parse(descriptor.deadline) - now())));
    await publish("started");
    await authorize();
    await session.prompt(context.prompt);
    await reportTail;
    if (typeof bound.finish === "function") await bound.finish();
    if (active.size || session.isStreaming) reject("EXECUTION_UNSETTLED", 4);
    const last = session.messages.at(-1);
    if (!last || last.role !== "assistant" || last.stopReason !== "stop") reject(transport.budgetExhausted === true ? "BUDGET_EXHAUSTED" : "EXECUTION_FAILED", 5);
    const final = session.getLastAssistantText();
    if (!text(final) || !final.trim()) reject("EVIDENCE_EMPTY", 5);
    await authorize();
    const result = { schema_version: 1, attempt_id: descriptor.attempt_id, manager_run_id: context.manager_run_id,
      request_digest: digest(descriptor), candidate_digest: candidateDigest, response_text: final,
      requested_model: { provider_id: descriptor.provider_id, model_id: descriptor.model_id }, observed_model: transport.observed_model ?? null,
      state: "execution_settled", failure_code: null, termination_confirmed: false };
    await publish("execution_settled", digest(result));
    await report({ result });
    return result;
  } catch (error) {
    const failure = { schema_version: 1, attempt_id: descriptor.attempt_id, manager_run_id: context.manager_run_id,
      request_digest: digest(descriptor), candidate_digest: candidateDigest, response_text: "",
      requested_model: { provider_id: descriptor.provider_id, model_id: descriptor.model_id }, observed_model: transport.observed_model ?? null,
      state: "execution_failed", failure_code: observation?.denials.at(-1)?.code ?? (isProtocolError(error) ? error.code : "EXECUTION_FAILED"),
      termination_confirmed: false };
    await publish("execution_failed", digest(failure));
    await report({ result: failure });
    throw error;
  } finally {
    clearTimeout(timer); signal?.removeEventListener("abort", stop);
    try { if (session) { try { await session.abort(); } finally { session.dispose(); } } }
    finally { await bound.close(); }
  }
}
