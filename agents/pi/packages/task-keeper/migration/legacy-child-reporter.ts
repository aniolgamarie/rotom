import {usageAccountPlan} from "../usage/pricing.ts";
import {resolveRecoveryPolicy} from "../policies/recovery.ts";
import { UsageLedger } from "../usage/ledger.ts";
import { UsageCapture, observeUsage } from "../usage/capture.ts";
import { assertWriterAllowed } from "../contracts/writers.ts";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { createReadTool, createWriteTool, createEditTool, createGrepTool, createFindTool, createLsTool } from "@earendil-works/pi-coding-agent";
import { readFileSync, realpathSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { resolve, join, dirname, basename, relative, sep } from "node:path";
import { configurationPolicyDigest, readConfig, readConfigForDirectory } from "../config.ts";
import { Store } from "../store/database.ts";
import { Artifacts } from "../store/artifacts.ts";
import { ContractError, identifier, newId, digest } from "../contracts/primitives.ts";
import { workspaceResource } from "../workspace/worktree.ts";
import { processIdentity, originalProcessStopped } from "./process-identity.ts";
import { scrub } from "../reliability/classifier.ts";
import { presentedReads, textPayload } from "../verification/read-causality.ts";
import type { ChildDescriptor, ChildObservation, ReadDelivery } from "./child-contract.ts";
import { installHttpTransport } from "./http-transport.ts";
import { runtimeIdentity } from "./runtime-identity.ts";
import { taskKeeperRuntimeIdentity } from "./task-keeper-identity.ts";
import { modelBindingDigest } from "./capabilities.ts";
import { readQuotaTelemetry } from "./telemetry.ts";
import { routeNotBefore, ensureExecutionTransportLease, admitTransportRequest } from "../reliability/incidents.ts";

export function guardedPath(root: string, path: unknown, write: boolean): string {
  if (typeof path !== "string") throw new ContractError("INVALID_TOOL_PATH");
  if (path.startsWith("~") || path.startsWith("@")) throw new ContractError("AMBIGUOUS_TOOL_PATH");
  const target = resolve(root, path), rel = relative(root, target);
  if (rel === ".." || rel.startsWith(`..${sep}`) || rel.split(sep).includes(".git")) throw new ContractError("TOOL_PATH_OUTSIDE_SCOPE");
  if (write && target === root) throw new ContractError("TOOL_PATH_OUTSIDE_SCOPE");
  let existing = target;
  while (!existsSync(existing)) {
    const parent = dirname(existing); if (parent === existing) throw new ContractError("INVALID_TOOL_PATH");
    existing = parent;
  }
  const actual = realpathSync(existing);
  if (actual !== root && !actual.startsWith(root + sep)) throw new ContractError("TOOL_SYMLINK_ESCAPE");
  return target;
}

/** Explicit child-only entry. No guarded tools exist before a healthy descriptor/ledger handshake. */
export default function childReporter(pi: ExtensionAPI): void {
  let usageCapture: UsageCapture | null = null;
  let descriptor: ChildDescriptor | null = null, store: Store | null = null, observation: ChildObservation | null = null;
  let monitor: ReturnType<typeof setInterval> | null = null, requestCount = 0;
  let transport: ReturnType<typeof installHttpTransport> | null = null;
  let requestSecrets: string[] = [];
  let configPath = "";
  let mainMessagesDigest: string | null = null;
  let activeMainRequest: number | null = null;
  const requestOrdinals = new Map<string, number>(), mainAttempts = new Map<string, ReadDelivery[]>(), successfulReads = new Map<number, ReadDelivery[]>();
  const pendingStructured = new Map<string, { requestOrdinal: number; valueDigest: string }>();
  const active = new Set<string>();
  const assertGrant = () => {
    if (!descriptor || !store) throw new ContractError("CHILD_NOT_READY");
    if (descriptor.runtimeDigest !== taskKeeperRuntimeIdentity()) throw new ContractError("CHILD_TASK_KEEPER_RUNTIME_CHANGED");
    if (!Number.isSafeInteger(descriptor.expiresAt) || Date.now() >= descriptor.expiresAt) throw new ContractError("CHILD_DEADLINE_EXPIRED");
    store.assertOwner(descriptor.owner);
    const grant = store.get<{ nonce: string; active: boolean }>("child-grants", descriptor.id);
    if (!grant?.active || grant.nonce !== descriptor.nonce || originalProcessStopped(descriptor.parentProcess) !== false) {
      throw new ContractError("CHILD_GRANT_REVOKED");
    }
    if (!descriptor.policyDigest || !descriptor.sourceCwd || !descriptor.routeId) throw new ContractError("CHILD_POLICY_BINDING_REQUIRED");
    const current = readConfigForDirectory(configPath, descriptor.sourceCwd);
    if (configurationPolicyDigest(current) !== descriptor.policyDigest) throw new ContractError("CHILD_POLICY_CHANGED");
    if (!descriptor.readOnly) assertWriterAllowed(current.limits.writersPerJob);
    return current;
  };
  const record = (kind: string, payload: Record<string, unknown>) => {
    if (!descriptor || !store || !observation) return;
    observation.sequence++;
    const appended = store.append({ id: `${observation.producerId}:${observation.sequence}`, producer: observation.producerId, seq: observation.sequence,
      scopeId: descriptor.owner.scopeId, kind, payload });
    if (appended === "conflict") throw new ContractError("CHILD_EVENT_CONFLICT");
    observation.activeTools = [...active];
    store.put("child-observations", observation.producerId, observation);
  };
  const setup = (prompt: string, ctx: ExtensionContext) => {
    if (!runtimeIdentity().supported) throw new ContractError("CHILD_RUNTIME_NOT_CERTIFIED");
    // The executor may prefix the task with a label. Repeated copies of the same owned ID are harmless.
    const matches = [...new Set([...prompt.matchAll(/TASK_KEEPER_DESCRIPTOR:([a-zA-Z0-9_-]+)/g)].map((match) => match[1]))];
    if (matches.length !== 1) throw new ContractError("CHILD_DESCRIPTOR_REQUIRED");
    const id = matches[0]; identifier(id);
    configPath = process.env.PI_TASK_KEEPER_CONFIG ?? join(process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi/agent"), "task-keeper.json");
    const config = readConfig(configPath);
    const dbPath = config.storage.path.startsWith("~/") ? join(homedir(), config.storage.path.slice(2)) : resolve(config.storage.path);
    descriptor = JSON.parse(readFileSync(join(dirname(dbPath), "child-contexts", `${id}.json`), "utf8")) as ChildDescriptor;
    if (descriptor.id !== id || descriptor.storePath !== dbPath || realpathSync(descriptor.cwd) !== realpathSync(ctx.cwd)) throw new ContractError("CHILD_DESCRIPTOR_MISMATCH");
    store = new Store(dirname(dbPath), basename(dbPath)); assertGrant();
    usageCapture = new UsageCapture(store);
    if (config.usage.enabled) new UsageLedger(store).begin({id:descriptor.analyticsTaskId??descriptor.jobId,sessionId:descriptor.owner.scopeId,title:"Managed task",workflow:"managed",contractDigest:descriptor.policyDigest});
    if (ctx.model?.provider !== descriptor.provider || ctx.model?.id !== descriptor.model || pi.getThinkingLevel() !== descriptor.thinking) {
      throw new ContractError("CHILD_MODEL_CONTRACT_MISMATCH");
    }
    if (ctx.model.api !== "openai-completions") throw new ContractError("PROVIDER_PROTOCOL_NOT_CERTIFIED");
    if (modelBindingDigest(ctx.model) !== descriptor.modelDigest) throw new ContractError("CHILD_MODEL_BINDING_CHANGED");
    const root = realpathSync(ctx.cwd);
    const producerId = newId("child"), leaseId = `lease-${producerId}`, identity = processIdentity();
    if (!identity) throw new ContractError("CHILD_PROCESS_IDENTITY_UNKNOWN");
    store.prepare(descriptor.owner, leaseId, "child-lease", { descriptorId: id, process: identity }, [
      { id: "native-children", capacity: descriptor.maxChildren, units: 1 },
      { id: descriptor.readOnly ? "native-readers" : `writer-${workspaceResource(root)}`, capacity: descriptor.readOnly ? descriptor.maxReaders : 1, units: 1 },
    ]);
    observation = { ready: true, descriptorId: id, process: identity, producerId, leaseId, cwd: root,
      provider: ctx.model.provider, model: ctx.model.id, thinking: pi.getThinkingLevel(), settled: false, activeTools: [], stopReason: null,
      modelDigest: modelBindingDigest(ctx.model), runtimeDigest: taskKeeperRuntimeIdentity(), externalWork: [],
      toolErrors: [], requestGate: false, requestDenials: [], lastResponse: null, lastError: null, fileReads: [], artifactReads: [], sequence: 0 };
    const target = { baseUrl: ctx.model.baseUrl, model: ctx.model.id, token: 1 };
    const assertRequest = () => {
      const current = assertGrant(), route = current.routes[descriptor!.routeId];
      if (!route || !readQuotaTelemetry(current, route).eligible) throw new ContractError("QUOTA_TELEMETRY_NOT_ELIGIBLE");
      if (routeNotBefore(store!, route) > Date.now()) throw new ContractError("SHARED_ROUTE_NOT_BEFORE");
      const grant = store!.get<{ parentIntentId?: string }>("child-grants", descriptor!.id);
      ensureExecutionTransportLease(store!, descriptor!.owner, descriptor!.id, descriptor!.jobId, grant?.parentIntentId ?? null, route);
    };
    transport = installHttpTransport(() => ctx.model?.api === "openai-completions" ? target : null, {
      before: (attempt) => {
        requestOrdinals.set(attempt.id, activeMainRequest ?? 0);
        if (activeMainRequest !== null) successfulReads.delete(activeMainRequest);
        observation!.lastResponse = null;observation!.lastRequestTimeout=null; requestSecrets = attempt.secrets;
        try {
          assertRequest();
          if (attempt.model !== descriptor!.model) throw new ContractError("HTTP_MODEL_CONTRACT_MISMATCH");
          if (descriptor!.protected) {
            store!.reserveRequest(descriptor!.owner, leaseId, attempt.id, descriptor!.budgetLimits);
          }
          const messages = (attempt.payload as {messages?: unknown})?.messages;
          if (activeMainRequest !== null && messages && mainMessagesDigest === digest(messages)) {
            mainAttempts.set(attempt.id, presentedReads([...observation!.fileReads, ...observation!.artifactReads], attempt.payload, requestCount));
          }
          observeUsage(store,()=>usageCapture?.attempt(attempt.id));
          record("http_attempt", { requestId: attempt.id, model: attempt.model, requestOrdinal: activeMainRequest,
            presentedReads: (mainAttempts.get(attempt.id) ?? []).map(read => ({ toolCallId: read.toolCallId, payloadDigest: read.payloadDigest })) });
        } catch (error) {
          observation!.requestDenials.push(error instanceof ContractError ? error.code : "request_admission_failed");
          ctx.abort();
          try { record("request_denied", { requestId: attempt.id, reason: observation!.requestDenials.at(-1)! }); } catch { /* Fail closed even when storage fails. */ }
          throw error;
        }
      },
      recheck: (attempt) => {
        try { assertRequest(); }
        catch (error) {
          observation!.requestDenials.push(error instanceof ContractError ? error.code : "request_admission_failed");
          ctx.abort();
          try { record("request_denied", { requestId: attempt.id, reason: observation!.requestDenials.at(-1)! }); } catch { /* Remain denied. */ }
          throw error;
        }
      },
      invokeWithin: (_attempt, invoke) => {
        try {
          const current = assertGrant(), route = current.routes[descriptor!.routeId];
          const grant = store!.get<{ parentIntentId?: string }>("child-grants", descriptor!.id);
          // Commit the final grant decision before invoking I/O. A cancellation
          // that precedes this decision cannot authorize an auxiliary request.
          admitTransportRequest(store!, descriptor!.owner, descriptor!.id, descriptor!.jobId, grant?.parentIntentId ?? null, route, _attempt.id, () => {
            const latest = assertGrant(), actualRoute = latest.routes[descriptor!.routeId];
            if (!actualRoute || !readQuotaTelemetry(latest, actualRoute).eligible) throw new ContractError("QUOTA_TELEMETRY_NOT_ELIGIBLE");
            if (routeNotBefore(store!, actualRoute) > Date.now()) throw new ContractError("SHARED_ROUTE_NOT_BEFORE");
          });
          invoke();
        } catch (error) {
          observation!.requestDenials.push(error instanceof ContractError ? error.code : "request_admission_failed");
          ctx.abort();
          try { record("request_denied", { requestId: _attempt.id, reason: observation!.requestDenials.at(-1)! }); } catch { /* Remain denied. */ }
          throw error;
        }
      },
      requestTimeoutMs:()=>{const current=assertGrant(),route=current.routes[descriptor!.routeId];return Math.min(resolveRecoveryPolicy(current,route,route).requestTimeoutMs,descriptor!.timeoutMs,descriptor!.expiresAt-Date.now());},
      requestTimedOut:(attempt)=>{observation!.lastError="REQUEST_TIMEOUT";observation!.lastRequestTimeout={requestId:attempt.id,at:Date.now()};record("request_timeout",{requestId:attempt.id,code:"REQUEST_TIMEOUT"});},
      meteringEnabled:()=>usageCapture?.hasActive()??false,
      metering:(attempt,zero)=>observeUsage(store,()=>usageCapture?.metering(attempt.id,zero)),
      response: (attempt, response) => {
        observeUsage(store,()=>usageCapture?.response(attempt.id,response.status));
        if (descriptor!.protected) store!.settleRequest(attempt.id, "sent");
        observation!.lastResponse = response;
        const ordinal = requestOrdinals.get(attempt.id);
        if (ordinal !== undefined && mainAttempts.has(attempt.id)) {
          if (response.status >= 200 && response.status < 300) successfulReads.set(ordinal, mainAttempts.get(attempt.id)!);
          else successfulReads.delete(ordinal);
        }
        record("http_response", { requestId: attempt.id, status: response.status, headers: response.headers });
      },
      error: (attempt, invoked, error) => {
        if(!invoked)observeUsage(store,()=>usageCapture?.notSent(attempt.id));
        const request = descriptor!.protected ? store!.request(attempt.id) : null;
        if (request && ["reserved", "unknown"].includes(String(request.state))) store!.settleRequest(attempt.id, invoked ? "unknown" : "not_sent");
        const cause = error instanceof Error && error.cause instanceof Error ? error.cause.message : "";
        record("http_transport_error", { requestId: attempt.id, invoked,
          error: scrub(`${error instanceof Error ? error.message : "transport failed"}; ${cause}`, requestSecrets) });
      },
    }, descriptor.protected);
    observation.requestGate = descriptor.protected && transport.intact();
    record("child_ready", { descriptorId: id, cwd: root, provider: ctx.model.provider, model: ctx.model.id, thinking: pi.getThinkingLevel() });
    if (!store.get<ChildObservation>("child-observations", producerId)?.ready) throw new ContractError("CHILD_CHANNEL_FAILED");
    const tools = [createReadTool(root), createGrepTool(root), createFindTool(root), createLsTool(root),
      ...(descriptor.readOnly ? [] : [createWriteTool(root), createEditTool(root)])];
    for (const base of tools) {
      const tool = base as unknown as ToolDefinition;
      const writes = tool.name === "write" || tool.name === "edit";
      pi.registerTool({ ...tool, name: `tk_${tool.name}`, label: `Task Keeper ${tool.name}`, executionMode: writes ? "sequential" : "parallel",
        description: tool.description + (tool.name === "read" ? " Also reads approved artifact:<id> references. Follow the returned next URI for artifact pagination; offset/limit are for files only." : ""),
        execute: async (toolCallId, args, signal, onUpdate, context) => {
          assertGrant();
          const parameters = args as Record<string, unknown>;
          if (tool.name === "read" && typeof parameters.path === "string" && parameters.path.startsWith("artifact:")) {
            const match = /^artifact:(artifact-[a-f0-9]{64})(?::(\d+))?$/.exec(parameters.path);
            if (!match || parameters.offset !== undefined || parameters.limit !== undefined) throw new ContractError("USE_ARTIFACT_NEXT_URI");
            const allowed = descriptor!.allowedArtifacts.find((artifact) => artifact.id === match[1]);
            if (!allowed) throw new ContractError("ARTIFACT_NOT_ATTACHED_TO_STEP");
            const { content, artifact } = new Artifacts(store!).read(allowed.id, descriptor!.jobId, allowed.snapshot);
            const start = Number(match[2] ?? "0");
            if (!Number.isSafeInteger(start) || start < 0 || start > content.length || (start < content.length && (content[start] & 0xc0) === 0x80)) throw new ContractError("INVALID_ARTIFACT_CURSOR");
            let end = Math.min(content.length, start + 24000);
            while (end < content.length && (content[end] & 0xc0) === 0x80) end--;
            const text = JSON.stringify({ id: artifact.id, jobId: artifact.jobId, snapshot: artifact.snapshot,
              source: artifact.source, start, end, total: content.length, next: end < content.length ? `artifact:${artifact.id}:${end}` : null }) + "\n" + content.subarray(start, end).toString("utf8");
            observation!.artifactReads.push({ id: artifact.id, start, end, total: content.length, toolCallId, payloadDigest: digest(text), readRequest: requestCount });
            record("artifact_read", { artifactId: artifact.id, start, end, total: content.length, toolCallId, readRequest: requestCount });
            return { content: [{ type: "text", text }], details: { artifactId: artifact.id } };
          }
          const path = guardedPath(root, parameters.path ?? root, writes);
          // Pass the checked absolute path, so the underlying tool cannot expand '~' or '@' outside the scope.
          const result = await tool.execute(toolCallId, { ...parameters, path }, signal, onUpdate, context);
          if (tool.name === "read" && !("isError" in result && result.isError) && result.content.every((part) => part.type === "text")) {
            const firstLine = typeof parameters.offset === "number" ? parameters.offset : 1;
            const limit = typeof parameters.limit === "number" ? parameters.limit : 2000;
            const count = readFileSync(path, "utf8").split("\n").length;
            const outputLines = (result.details as { truncation?: { outputLines?: number } } | undefined)?.truncation?.outputLines ?? count;
            observation!.fileReads.push({ path: relative(root, path), firstLine, lastLine: Math.min(count, firstLine + Math.min(limit, outputLines) - 1),
              toolCallId, payloadDigest: digest(textPayload(result.content)!), readRequest: requestCount });
            record("file_read", { path: relative(root, path), firstLine, lastLine: observation!.fileReads.at(-1)!.lastLine });
          }
          return result;
        } });
    }
    pi.setActiveTools([...tools.map((tool) => `tk_${tool.name}`), ...(pi.getAllTools().some((tool) => tool.name === "structured_output") ? ["structured_output"] : [])]);
    pi.events.emit("subagent:acknowledge-extension", { id: "task-keeper.reporter.v1" });
    monitor = setInterval(() => {
      try { assertGrant(); } catch {
        const stop = store?.get<{ stop?: boolean }>("child-grants", descriptor!.id)?.stop;
        if (stop || active.size === 0) ctx.abort();
      }
    }, 250); monitor.unref();
  };
  pi.on("before_agent_start", (event, ctx) => {
    try {
      if (!observation?.ready) setup(event.prompt, ctx);
      assertGrant();
    } catch (error) {
      ctx.abort();
      try {
        const configPath = process.env.PI_TASK_KEEPER_CONFIG ?? join(process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi/agent"), "task-keeper.json");
        if (!existsSync(configPath)) throw new Error("No owned configuration");
        const config = readConfig(configPath);
        const path = config.storage.path.startsWith("~/") ? join(homedir(), config.storage.path.slice(2)) : resolve(config.storage.path);
        if (!config.enabled || !existsSync(path)) throw new Error("No owned state");
        const directory = join(dirname(path), "child-errors"); mkdirSync(directory, { recursive: true, mode: 0o700 });
        const id = /TASK_KEEPER_DESCRIPTOR:([a-zA-Z0-9_-]+)/.exec(event.prompt)?.[1] ?? `unmatched-${process.pid}`;
        writeFileSync(join(directory, `${id}.json`), JSON.stringify({ error: scrub(error instanceof Error ? error.message : String(error)), pid: process.pid,
          nonce: descriptor?.nonce ?? null, process: processIdentity() }), { mode: 0o600 });
      } catch { /* The missing reporter channel remains an explicit parent-side failure. */ }
      throw error;
    }
  });
  pi.on("before_provider_request", (event, ctx) => {
    if(descriptor && usageCapture && !usageCapture.hasActive()) observeUsage(store,()=>usageCapture!.begin({sessionId:ctx.sessionManager.getSessionId(),provider:descriptor!.provider,model:descriptor!.model,modelVersion:descriptor!.modelDigest,
      role:descriptor!.stepId,taskId:descriptor!.analyticsTaskId??descriptor!.jobId,accountPlanRef:usageAccountPlan(assertGrant().usage,descriptor!.provider,descriptor!.model),quotes:assertGrant()?.usage.priceBooks},assertGrant()?.usage.enabled===true));
    try {
      assertGrant(); requestCount++; activeMainRequest = requestCount;
      const messages = (event.payload as {messages?: unknown})?.messages;
      mainMessagesDigest = messages ? digest(messages) : null;
      record("model_input", { requestOrdinal: requestCount, messagesDigest: mainMessagesDigest });
      if (!ctx.model || !descriptor || modelBindingDigest(ctx.model) !== descriptor.modelDigest || pi.getThinkingLevel() !== descriptor.thinking) throw new ContractError("CHILD_MODEL_BINDING_CHANGED");
      if (descriptor?.protected && !transport?.intact()) throw new ContractError("HTTP_GATE_REPLACED");
      if (descriptor && requestCount > descriptor.maxModelTurns) throw new ContractError("CHILD_MODEL_TURN_LIMIT");
    } catch { ctx.abort(); }
  });
  pi.on("session_before_compact", (event, ctx) => {
    if (!observation) return;
    try {
      assertGrant();
      const operations = observation.contextOperations ??= [];
      if (operations.length >= 100) throw new ContractError("CONTEXT_OPERATION_LIMIT");
      const operation = { id: newId("compact"), reason: event.reason, status: "running" as const };
      operations.push(operation); record("compaction_start", { ...operation });
      observeUsage(store,()=>{if(descriptor)usageCapture?.begin({sessionId:ctx.sessionManager.getSessionId(),provider:descriptor.provider,model:descriptor.model,modelVersion:descriptor.modelDigest,role:"compaction",taskId:descriptor.analyticsTaskId??descriptor.jobId,accountPlanRef:usageAccountPlan(assertGrant().usage,descriptor!.provider,descriptor!.model),quotes:assertGrant()?.usage.priceBooks},assertGrant()?.usage.enabled===true);});
    } catch { ctx.abort(); return { cancel: true }; }
  });
  pi.on("session_compact", event => {
    observeUsage(store,()=>usageCapture?.end(event.fromExtension?undefined:event.compactionEntry?.usage,"success",Date.now(),"operation-aggregate"));
    const operation = observation?.contextOperations?.findLast(item => item.status === "running");
    if (operation) { operation.status = "completed"; record("compaction_end", { id: operation.id, reason: event.reason }); }
  });
  pi.on("session_compact_failed", event => {
    observeUsage(store,()=>usageCapture?.end(undefined,"failure"));
    const operation = observation?.contextOperations?.findLast(item => item.status === "running");
    if (operation) { operation.status = "failed"; operation.error = scrub(event.errorMessage ?? (event.aborted ? "compaction_aborted" : "compaction_failed"), requestSecrets);
      record("compaction_failed", { id: operation.id, reason: event.reason, error: operation.error }); }
  });
  pi.on("tool_execution_start", (event) => {
    observeUsage(store,()=>{if(observation)usageCapture?.tool(`${observation.producerId}:${event.toolCallId}`,null);});
    active.add(event.toolCallId);
    if (event.toolName === "structured_output") {
      try { pendingStructured.set(event.toolCallId, { requestOrdinal: requestCount, valueDigest: digest(event.args?.value) }); }
      catch { pendingStructured.delete(event.toolCallId); }
    }
    if (["tk_find", "tk_grep"].includes(event.toolName)) observation?.externalWork?.push(event.toolCallId);
    record("tool_start", { toolCallId: event.toolCallId, toolName: event.toolName });
  });
  pi.on("tool_execution_end", (event) => {
    observeUsage(store,()=>{if(observation)usageCapture?.tool(`${observation.producerId}:${event.toolCallId}`,!!event.isError);});
    active.delete(event.toolCallId);
    if (event.toolName === "structured_output") {
      const value = pendingStructured.get(event.toolCallId); pendingStructured.delete(event.toolCallId);
      if (value && !event.isError && observation) (observation.structuredOutputs ??= []).push({ toolCallId: event.toolCallId, ...value });
    }
    // grep settles on child close; find's abort path settles before close. A killed
    // reporter with either tool still active cannot prove the descendant stopped.
    if (observation && !(event.toolName === "tk_find" && event.isError))
      observation.externalWork = observation.externalWork?.filter(id => id !== event.toolCallId);
    if (event.isError && observation) observation.toolErrors.push({ toolCallId: event.toolCallId, toolName: event.toolName, error: scrub(JSON.stringify(event.result)) });
    record("tool_end", { toolCallId: event.toolCallId, toolName: event.toolName, isError: !!event.isError });
  });
  pi.on("message_end", (event) => {
    if (event.message.role === "assistant" && observation) {
      observation.stopReason = event.message.stopReason;
      if (activeMainRequest === requestCount && ["stop", "toolUse"].includes(event.message.stopReason))
        for (const read of successfulReads.get(requestCount) ?? []) read.deliveredRequest ??= requestCount;
      activeMainRequest = null;
      observation.lastError = event.message.errorMessage ? scrub(event.message.errorMessage, requestSecrets) : null;
      const message=event.message;
      observeUsage(store,()=>{const fact=usageCapture?.end(message.usage,message.stopReason === "aborted" ? "cancelled" : ["stop","toolUse"].includes(message.stopReason) ? "success" : "failure");
        if(fact && observation){observation.usageIds??=[];observation.usageIds.push(fact.id);}});
      record("assistant_terminal", { stopReason: event.message.stopReason, error: observation.lastError ?? "" });
    }
  });
  pi.on("agent_settled", () => { if (observation) observation.settled = true; record("child_settled", { activeTools: [...active] }); requestSecrets = []; });
  pi.on("session_shutdown", () => { if (monitor) clearInterval(monitor); transport?.dispose(); record("child_shutdown", {}); store?.close(); store = null; });
}
