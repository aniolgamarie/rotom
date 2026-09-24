// 单次只读 Pi 委托：封闭 loader、精确模型和显式 fetch，不创建管理者。
import { observeDelegateResponse } from "./delegate-response.ts";
import { workerLoader } from "./managed-worker.ts";
import { canonical, reject, text } from "./managed-types.ts";
import * as zlib from "node:zlib";

export async function runPiDelegate({ sdk, input, modelRuntime, agentDir, sessionManager, tools, supervisor, fetchRoute, report, auth = null, nativeTransport = null,
    now = () => Date.now() }) {
  const { request, grant } = input;
  const retryLimit = input.retry_limit ?? 0;
  if (!Number.isSafeInteger(retryLimit) || retryLimit < 0 || retryLimit > 3) reject("DELEGATE_RETRY_LIMIT", 2);
  if (request.backend !== "pi" || request.execution_boundary !== "agentcfg-tools" || request.execution_mode !== "delegate-readonly" || request.mode === "implement"
      || tools.some(tool => !["tk_read", "tk_grep", "tk_find", "tk_ls"].includes(tool.name))
      || canonical(tools.map(tool => tool.name).sort()) !== canonical([...grant.allowed_tools].sort())) reject("DELEGATE_TOOL_READONLY", 2);
  for (const key of ["pi-subagents:manager", "agentcfg.pi.manager.v1", "agentcfg.pi.managed.v1"]) if (globalThis[Symbol.for(key)]) reject("WORKER_MANAGER_FORBIDDEN", 5);
  const authorize = async () => {
    if (auth && (auth.provider_id !== request.requested_model.provider_id || typeof auth.apiKey !== "string" || !auth.apiKey
        || !Number.isFinite(auth.expires_at_ms) || now() >= auth.expires_at_ms)) reject("DELEGATE_CREDENTIAL_EXPIRED", 3);
    if (now() >= Date.parse(grant.expires_at)) reject("DELEGATE_DEADLINE", 4);
    const proof = await supervisor.call("authorize", { lease_id: request.lease_id, grant_generation: request.grant_generation });
    if (!proof.valid || proof.grant_generation !== request.grant_generation) reject("DELEGATE_GRANT_REVOKED", 4);
  };
  await authorize();
  const selected = request.requested_model, model = modelRuntime.getModel(selected.provider_id, selected.model_id);
  if (!model || model.provider !== selected.provider_id || model.id !== selected.model_id || !["openai-completions", "openai-responses", "openai-codex-responses", "cursor-native"].includes(model.api)
      || model.api === "openai-codex-responses" && (!auth || model.provider !== "openai-codex")) reject("DELEGATE_MODEL_UNSUPPORTED", 5);
  if (model.api === "cursor-native" && (!auth || model.provider !== "cursor" || nativeTransport?.api !== model.api || retryLimit !== 0)) reject("DELEGATE_MODEL_UNSUPPORTED", 5);
  const original = new Map(), requests = [];
  let session, timer, serial = Promise.resolve(), sequence = 0;
  const emit = (kind, phase) => {
    const event = { schema_version: 2, run_id: request.run_id, seq: ++sequence, timestamp: new Date(now()).toISOString(), kind, phase, artifact_id: null };
    serial = serial.then(() => report({ event })); return serial;
  };
  try {
    for (const name of ["stream", "streamSimple"]) {
      if (typeof modelRuntime[name] !== "function") reject("DELEGATE_TRANSPORT_MISSING", 5);
      original.set(name, modelRuntime[name]);
      const invoke = modelRuntime[name].bind(modelRuntime);
      modelRuntime[name] = (target, context, options = {}) => {
        if (target.provider !== selected.provider_id || target.id !== selected.model_id || target.baseUrl !== model.baseUrl) reject("DELEGATE_MODEL_UNBOUND", 2);
        if (model.api === "cursor-native") return nativeTransport.invoke(invoke, target, context, { ...options, apiKey: auth.apiKey }, authorize, requests);
        let attempts = 0;
        return invoke(target, context, { ...options, ...(auth ? { apiKey: auth.apiKey } : {}), maxRetries: retryLimit, transport: "sse", fetch: async (resource, init) => {
          await authorize();
          if (++attempts > 1 + retryLimit) reject("DELEGATE_RETRY_LIMIT", 5);
          const outbound = new Request(resource, init), base = model.baseUrl.replace(/\/+$/, "");
          const endpoint = model.api === "openai-codex-responses" ? base.endsWith("/codex/responses") ? base : base.endsWith("/codex") ? base + "/responses" : base + "/codex/responses"
            : base + (model.api === "openai-responses" ? "/responses" : "/chat/completions");
          if (outbound.method !== "POST" || outbound.url !== endpoint) reject("DELEGATE_ROUTE_MISMATCH", 4);
          const raw = Buffer.from(await outbound.arrayBuffer());
          if (raw.length > 16 * 1024 * 1024) reject("DELEGATE_REQUEST_OVERSIZE", 2);
          let bytes = raw;
          if (outbound.headers.get("content-encoding") === "zstd" && model.api === "openai-codex-responses") {
            if (typeof zlib.zstdDecompressSync !== "function") reject("DELEGATE_COMPRESSION_UNSUPPORTED", 5);
            bytes = zlib.zstdDecompressSync(raw, { maxOutputLength: 16 * 1024 * 1024 });
            outbound.headers.delete("content-encoding"); outbound.headers.delete("content-length");
          } else if (outbound.headers.has("content-encoding")) reject("DELEGATE_COMPRESSION_UNSUPPORTED", 5);
          const body = new TextDecoder("utf8", { fatal: true }).decode(bytes);
          if (JSON.parse(body).model !== selected.model_id) reject("DELEGATE_MODEL_UNBOUND", 2);
          const observed = observeDelegateResponse(await fetchRoute(endpoint, { method: "POST", headers: outbound.headers, body, signal: outbound.signal, redirect: "error" }), selected, model.api);
          requests.push(observed.observation); return observed.response;
        } });
      };
    }
    for (const name of ["complete", "completeSimple", "deferredFetch", "deferredCancel", "fetchDeferred", "cancelDeferred"]) if (typeof modelRuntime[name] === "function") {
      original.set(name, modelRuntime[name]); modelRuntime[name] = () => reject("DELEGATE_HELPER_DISABLED", 5);
    }
    const created = await sdk.createAgentSession({ cwd: request.cwd, agentDir, modelRuntime, model, thinkingLevel: "off", scopedModels: [{ model }],
      sessionManager, noTools: "builtin", tools: grant.allowed_tools,
      customTools: tools.map(tool => ({ ...tool, execute: async (...args) => { await authorize(); const result = await tool.execute(...args); await emit("checkpoint", "tool-completed"); return result; } })),
      resourceLoader: workerLoader(sdk, { system_prompt: input.system_prompt ?? "Perform the bounded readonly task. Report evidence and uncertainty. Do not delegate or change files." }),
      settingsManager: sdk.SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false, maxRetries: 0, provider: { maxRetries: 0 } },
        packages: [], extensions: [], skills: [], prompts: [], themes: [] }) });
    session = created.session;
    if (created.modelFallbackMessage || canonical(session.getActiveToolNames().sort()) !== canonical([...grant.allowed_tools].sort())) reject("DELEGATE_SESSION_MISMATCH", 5);
    session.setAutoCompactionEnabled(false); session.setAutoRetryEnabled(false);
    session.setActiveTools = names => { if (canonical([...names].sort()) !== canonical([...grant.allowed_tools].sort())) reject("DELEGATE_TOOL_READONLY", 2); };
    timer = setTimeout(() => { void session.abort().catch(() => {}); }, Math.max(1, Math.min(2147483647, Date.parse(grant.expires_at) - now())));
    await emit("ready", "started");
    const firstMessage = session.messages.length;
    await session.prompt(input.prompt);
    await serial;
    const last = session.messages.at(-1), final = session.getLastAssistantText();
    if (!requests.some(value => !value.failed && value.done) || requests.some(value => !value.done)) reject("DELEGATE_STREAM_INCOMPLETE", 5);
    if (session.isStreaming || session.messages.length <= firstMessage || last?.role !== "assistant" || last.stopReason !== "stop" || !text(final) || !final.trim()) reject("DELEGATE_RESULT_EMPTY", 5);
    nativeTransport?.verify();
    await emit("completed", "turn-completed");
    const messages = session.messages.slice(firstMessage).filter(message => message.role === "assistant");
    const total = key => messages.length && messages.every(message => Number.isSafeInteger(message.usage?.[key]) && message.usage[key] >= 0)
      ? messages.reduce((sum, message) => sum + message.usage[key], 0) : null;
    return { final, host_completed: true, observed_model: requests.find(value => value.model)?.model ?? null, resume_token: sessionManager.getSessionFile() ?? null,
      usage: { input_tokens: total("input"), output_tokens: total("output"), cost: null }, feedback_dispositions: [] };
  } catch (error) {
    await emit("failed", "terminated");
    throw error;
  } finally {
    clearTimeout(timer);
    try { await session?.dispose(); }
    finally {
      for (const [name, method] of original) modelRuntime[name] = method;
      try { await nativeTransport?.close(sessionManager); }
      finally { await fetchRoute.close?.(); }
    }
  }
}
