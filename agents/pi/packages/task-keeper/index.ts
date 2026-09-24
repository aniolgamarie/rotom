import {usageAccountPlan} from "./src/usage/pricing.ts";
import { repricingView } from "./src/usage/pricing.ts";
import { instant } from "./src/policies/configuration.ts";
import { modelBindingDigest } from "./src/adapters/capabilities.ts";
import { submission } from "./src/policies/submission.ts";
import { modelComparison } from "./src/usage/comparison.ts";
import { UsageCapture, observeUsage } from "./src/usage/capture.ts";
import { UsageLedger } from "./src/usage/ledger.ts";
import { writerCapacity } from "./src/contracts/writers.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isHumanTerminalInput } from "./src/adapters/terminal-input.ts";
import { kernelTaskParameters } from "./src/contracts/commands.ts";
import { digest, newId, ContractError } from "./src/contracts/primitives.ts";
import { TaskService } from "./src/orchestration/service.ts";
import { StatusPublisher, recoveryStatusText, jobStatusText } from "./src/evidence/status.ts";
import { compileContextEvidence } from "./src/evidence/context.ts";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { configurationBindingGaps, configurationPolicyDigest, readConfigForDirectory, type Config } from "./src/config.ts";
import { Store } from "./src/store/database.ts";
import { PiInteractiveAdapter, inspectRuntimeProfile } from "./src/adapters/pi-interactive.ts";
import { linuxProcessMonitor } from "./src/adapters/process-identity.ts";
import { installHttpTransport } from "./src/adapters/http-transport.ts";
import { activeManagedParentGuard } from "./src/adapters/subagents.ts";
import { RecoveryController } from "./src/reliability/recovery.ts";
import { routeIncidents, routeNotBefore } from "./src/reliability/incidents.ts";
import { scrub, terminalError, classify, retryAfter, type FailureSignal, type Classification } from "./src/reliability/classifier.ts";

const expand = (path: string) => resolve(path.startsWith("~/") ? join(homedir(), path.slice(2)) : path);

// One parent entry; the managed child adapter is not required to load interactive recovery.
export default function taskKeeper(pi: ExtensionAPI): void {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") throw new ContractError("CAPABILITY_MISSING");
  const configPath = join(runtime.instanceRoot, "pi-home/agentcfg-manifest.json");
  let config: Config | null = null, store: Store | null = null, adapter: PiInteractiveAdapter | null = null;
  let managed: TaskService | null = null;
  let usageCapture: UsageCapture | null = null, treeUsage:UsageCapture|null=null;
  let recovery: RecoveryController | null = null, context: ExtensionContext | null = null;
  let lastResponse: { status: number; headers: Record<string, string>; errorBody?: string } | null = null;
  let finalSignal: FailureSignal | null | undefined;
  let userTurnPending = false;
  let startupError: string | null = null;
  let requestToken = 0;
  let userGeneration = 0;
  let modelAuthorityGeneration = -1, responseAuthorityGeneration = -1;
  const toolAuthorities = new Map<string, number>();
  const revokeModelTools = () => { userGeneration++; modelAuthorityGeneration = -1; userTurnPending = false; toolAuthorities.clear(); };
  let serverFloor: { generation: number; until: number; route: string } | null = null;
  let deniedCooldown: { token: number; until: number; network?: boolean; source?: "shared" } | null = null;
  let deniedControl: { token: number; reason: string } | null = null;
  let automaticTurn: { intentId: string; epoch: number } | null = null;
  let automaticRequestGuard: ((invoke?: () => void, requestId?: string) => void) | null = null;
  let compactionRequestGuard: ((invoke?: () => void, requestId?: string) => void) | null = null;
  let contextOperation: { id: string; sessionId: string; reason: string; status: string; error?: string } | null = null;
  let requestSecrets: string[] = [];
  let removeTerminalInput: (() => void) | null = null;
  let contextGateError: { code: string; message: string } | null = null;
  let contextByteBudget: number | null = null;
  let contextPacket: { bytes: number; digest: string } | null = null;
  let statusPublisher: StatusPublisher | null = null;
  let transport: ReturnType<typeof installHttpTransport> | null = null;

  const update = (ctx: ExtensionContext) => { context = ctx; adapter?.update(ctx); managed?.update(ctx); };
  const present = (ctx: ExtensionContext, value: unknown, error = false) => {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    if (ctx.hasUI === false) {
      pi.sendMessage({ customType: "task-keeper:status", content: text, display: true, details: value }, { triggerTurn: false });
      return;
    }
    ctx.ui.notify(text, error ? "error" : "info");
  };
  const nativeFailures = () => store?.list<Classification & { sessionId: string; at: number }>("native-errors")
    .filter((entry) => entry.value.sessionId === context?.sessionManager.getSessionId()) ?? [];
  const nativeFailureSummary = () => {
    const failures = nativeFailures();
    const http = store?.list<{ sessionId: string; status: number }>("http-failures").filter((entry) => entry.value.sessionId === context?.sessionManager.getSessionId()) ?? [];
    const denied = store?.list<{ sessionId: string }>("request-denials").filter((entry) => entry.value.sessionId === context?.sessionManager.getSessionId()) ?? [];
    return { total: failures.length, httpFailureAttempts: http.length, deniedBeforeSend: denied.length,
      httpStatuses: [...new Set(http.map((entry) => entry.value.status))], groups: [...new Set(failures.map((entry) => entry.value.category))].map((category) => {
      const group = failures.filter((entry) => entry.value.category === category).sort((a, b) => a.value.at - b.value.at || a.id.localeCompare(b.id)), last = group.at(-1)!;
      return { category, count: group.length, firstId: group[0].id, recordIndex: { namespace: "native-errors", sessionId: last.value.sessionId, category }, lastId: last.id, code: last.value.code, message: last.value.message.slice(0, 500) };
    }) };
  };
  const resolvedRecovery = () => {try{return recovery?.target()??null;}catch(error){return {error:error instanceof ContractError?error.code:"CURRENT_TARGET_UNAVAILABLE"};}};
  const status = () => ({ enabled: config?.enabled ?? false, configPath, startupError,
    bindingGaps: config ? configurationBindingGaps(config) : null,
    effectivePolicy: config ? { scheduling: config.scheduling, allowedRoutes: config.allowedRoutes, features: config.features, limits: { ...config.limits, writersPerJob: writerCapacity(config.limits.writersPerJob) }, budget: config.budget,
      replanning: { enabled: config.features.semanticReplanning === true, configuredLimit: config.limits.semanticReplansPerTask, effectiveLimit: config.features.semanticReplanning ? config.limits.semanticReplansPerTask : 0, template: "diagnose-before-repair" },
      writerPolicy: { configuredLimit: config.limits.writersPerJob, effectiveLimit: writerCapacity(config.limits.writersPerJob), mode: "single-writer" },
      requiredChecks: config.workflow.requiredChecks, evidence: { packetByteBudget: contextByteBudget ?? config.evidence.packetByteBudget },
      allowPartial: config.workflow.allowPartial, risk: config.workflow.risk } : null,
    storageRoot: store?.root ?? null,
    coordination: store ? { stateRoot: store.root, database: store.path, scope: "task-database", workspaceAuthority: "agentcfg-supervisor-shared-worktree-leases", crossParentFairness: false } : null,
    contextEvidence: { blocked: contextGateError, packet: contextPacket, byteBudget: contextByteBudget ?? config?.evidence.packetByteBudget ?? null },
    support: { runtime: "Pi 0.84.4 / Node 24", mainRecovery: "RPC/TUI; self or pinned subagents then self; built-in file tools; OpenAI chat completions",
      managed: "fresh worker; @tintinweb/pi-subagents 0.19.0-agentcfg.1; agentcfg supervisor; guarded tools",
      networks: ["direct", "explicit-proxy"], telemetry: ["user-owned normalized file"], liveServices: "No live service measurements; loopback evidence is limited to the listed runtime/protocol contracts",
      advisor: "off; not implemented", strictMainSessionBudget: "not certified" },
    adapter: adapter?.snapshot() ?? { certified: false, runtime: inspectRuntimeProfile() },
    recovery: recovery?.state() ?? null, resolvedRecovery:resolvedRecovery(),
    usage: {enabled:config?.usage.enabled??false,gaps:store?.list("usage-capture-errors").length??0},
    secondOpinion:config?{enabled:config.secondOpinion.enabled,model:config.secondOpinion.model,maxExchanges:config.secondOpinion.maxExchanges}:null,
    timePolicy:config?.timePolicy??null,automaticModelSelection:config?.modelPolicy.automaticSelection??false,
    contextOperations: store?.list<{sessionId:string}>("context-operations").filter(entry => entry.value.sessionId === context?.sessionManager.getSessionId()) ?? [],
    lateRecoveryRecords: recovery ? store?.list<{scopeId:string;ownerEpoch:number;record:{status:string;reason:string;intentId:string|null}}>("late-recovery-records")
      .filter(entry => entry.value.scopeId === recovery!.scopeId).map(entry => ({ id: entry.id, ownerEpoch: entry.value.ownerEpoch,
        status: entry.value.record.status, reason: entry.value.record.reason, intentId: entry.value.record.intentId })) : [],
    nativeFailures: nativeFailureSummary(),
    persistedRecovery: recovery ? undefined : store?.list("recovery"),
    managedWorkflows: managed ? { jobs: managed.overview(), supported: ["inspect", "fix"] } : { enabled: false }, strictRequestGate: "managed-child-only; see doctor matrix" });

  pi.on("session_start", async (_event, ctx) => {
    update(ctx);
    statusPublisher?.dispose(); statusPublisher = null;
    revokeModelTools(); responseAuthorityGeneration = -1;
    requestToken++; serverFloor = null; deniedCooldown = null;
    removeTerminalInput?.(); removeTerminalInput = null;
    await managed?.dispose(); managed = null;
    recovery?.dispose(); recovery = null;
    adapter?.dispose();
    transport?.dispose(); transport = null;
    automaticTurn = null; automaticRequestGuard = null; compactionRequestGuard = null; contextOperation = null; contextGateError = null; contextPacket = null; contextByteBudget = null;
    observeUsage(store,()=>usageCapture?.end(undefined,"unknown"));observeUsage(store,()=>treeUsage?.end(undefined,"unknown")); usageCapture = null;treeUsage=null;
    store?.close(); store = null; adapter = null; config = null;
    try {
      config = readConfigForDirectory(configPath, ctx.cwd); startupError = null;
      if (!config.enabled) return;
      const path = expand(config.storage.path); store = new Store(dirname(path), basename(path));
      usageCapture = new UsageCapture(store);treeUsage=new UsageCapture(store);
      const painter = new StatusPublisher((key, text) => ctx.ui.setStatus(key, text)); statusPublisher = painter;
      const presentationConfig = config, presentationStore = store;
      if (config.features.managedWorkflows) managed = new TaskService(pi, store, config, ctx, (jobs) => {
        try {
          const rows = jobs.map(job => {
            const stage = job.recovery?.stage;
            const routeId = stage ? presentationConfig.recovery.chain.find(item => item.id === stage.stageId)?.route ?? job.recovery!.primaryRoute : undefined;
            const route = routeId ? presentationConfig.routes[routeId] : undefined;
            return { id: job.id, status: job.status, reason: job.reason, snapshot: job.snapshot, scheduleNotBefore:job.schedule?.admittedAt===null?job.schedule.notBefore:null,
              ...(route ? { routeNotBefore: routeNotBefore(presentationStore, route) } : {}), stageDeadline: stage?.deadline ?? null };
          });
          painter.publish("task-keeper:jobs", digest(rows), now => rows.map(row => jobStatusText(row, now)).join(" · "), rows.some(row => row.status === "WAITING_QUOTA" || (row.status === "QUEUED" && row.scheduleNotBefore!==null)));
        } catch { painter.publish("task-keeper:jobs", "unavailable", () => "UNKNOWN · job status unavailable"); }
      }, (cwd) => readConfigForDirectory(configPath, cwd), { fork: _event.reason === "fork", parentFile: _event.reason === "fork" ? _event.previousSessionFile : undefined });
      if (!config.features.interactiveRecovery && !managed && !config.usage.enabled) return;
      if (config.features.interactiveRecovery) {
        adapter = new PiInteractiveAdapter(pi, config, ctx);
        const canaryStore=store,canaryUsage=new UsageCapture(canaryStore);
        adapter.setUsageObserver({begin:target=>observeUsage(canaryStore,()=>{const usage=readConfigForDirectory(configPath,ctx.cwd).usage;canaryUsage.begin({...target,role:"canary",accountPlanRef:usageAccountPlan(usage,target.provider,target.model),quotes:usage.priceBooks},usage.enabled);}),
          attempt:id=>observeUsage(canaryStore,()=>canaryUsage.attempt(id)),notSent:id=>observeUsage(canaryStore,()=>canaryUsage.notSent(id)),metering:(id,zero)=>observeUsage(canaryStore,()=>canaryUsage.metering(id,zero)),active:()=>canaryUsage.hasActive(),response:(id,status)=>observeUsage(canaryStore,()=>canaryUsage.response(id,status)),end:(usage,outcome)=>observeUsage(canaryStore,()=>canaryUsage.end(usage,outcome))});
        const activeConfigDigest = configurationPolicyDigest(config);
        adapter.setConfigHealth(() => { try { return configurationPolicyDigest(readConfigForDirectory(configPath, ctx.cwd)) === activeConfigDigest; } catch { return false; } });
      }
      const checkAutomaticRequest = (attempt?: { id: string }, invoke?: () => void) => {
        try {
          if (contextGateError) throw new ContractError(contextGateError.code, contextGateError.message);
          if (contextPacket) {
            const current = readConfigForDirectory(configPath, context!.cwd);
            contextByteBudget = current.evidence.packetByteBudget;
            if (configurationPolicyDigest(current) !== configurationPolicyDigest(config!)) throw new ContractError("CONFIGURATION_CHANGED_RELOAD_REQUIRED");
            if (contextPacket.bytes > contextByteBudget) {
              contextGateError = { code: "PACKET_TOO_LARGE", message: `PACKET_TOO_LARGE: ${contextPacket.bytes} UTF-8 bytes exceed evidence.packetByteBudget=${contextByteBudget}` };
              throw new ContractError(contextGateError.code, contextGateError.message);
            }
          }
          const guard = compactionRequestGuard ?? automaticRequestGuard;
          if (guard) guard(invoke, attempt?.id); else invoke?.();
        }
        catch (error) {
          if (error instanceof ContractError && error.code === "AUTOMATIC_REQUEST_CONTROL_REVOKED") deniedControl = { token: requestToken, reason: error.code };
          if (attempt) try { store?.put("request-denials", attempt.id, { sessionId: context!.sessionManager.getSessionId(), source: "admission",
            reason: error instanceof ContractError ? error.code : "automatic_request_denied", at: Date.now() }); } catch { /* Still refuse the request. */ }
          if (error instanceof ContractError && ["SHARED_ROUTE_NOT_BEFORE", "SHARED_DOMAIN_BUSY"].includes(error.code) && config && store) {
            const route = recovery!.target().route, shared = routeIncidents(store, route)[0];
            deniedCooldown = { token: requestToken, until: Math.max(routeNotBefore(store, route), Date.now() + recovery!.target().intervals[0]),
              source: "shared", network: error.code === "SHARED_DOMAIN_BUSY" || shared?.domain?.kind === "transport" };
          }
          throw error;
        }
      };
      transport = installHttpTransport(() => context?.model?.api === "openai-completions"
        ? { baseUrl: context.model.baseUrl, model: context.model.id, token: requestToken } : null, {
        error:(attempt,invoked)=>{if(!invoked)observeUsage(store,()=>(treeUsage?.hasActive()?treeUsage:usageCapture)?.notSent(attempt.id));},
        meteringEnabled:()=>Boolean(treeUsage?.hasActive()||usageCapture?.hasActive()),
        metering:(attempt,zero)=>observeUsage(store,()=>(treeUsage?.hasActive()?treeUsage:usageCapture)?.metering(attempt.id,zero)),
        priorGuard: activeManagedParentGuard,
        before: (attempt) => {
          if (attempt.token !== requestToken) return;
          observeUsage(store,()=>(treeUsage?.hasActive()?treeUsage:usageCapture)?.attempt(attempt.id));
          lastResponse = null; requestSecrets = attempt.secrets;
          if (serverFloor?.generation === userGeneration && serverFloor.route === attempt.url && Date.now() < serverFloor.until) {
            deniedCooldown = { token: requestToken, until: serverFloor.until };
            store?.put("request-denials", attempt.id, { sessionId: context!.sessionManager.getSessionId(), source: "admission", reason: "server_retry_after", notBefore: serverFloor.until });
            throw new Error("Task Keeper: server Retry-After has not elapsed; this attempt was not sent");
          }
          deniedCooldown = null;
          checkAutomaticRequest(attempt);
        },
        recheck: checkAutomaticRequest,
        invokeWithin: (attempt, invoke) => checkAutomaticRequest(attempt, invoke),
        response: (attempt, response) => {
          if (attempt.token !== requestToken) return;
          observeUsage(store,()=>(treeUsage?.hasActive()?treeUsage:usageCapture)?.response(attempt.id,response.status));
          lastResponse = response;
          if (response.status >= 400) store?.put("http-failures", attempt.id, { sessionId: context!.sessionManager.getSessionId(), status: response.status, headers: response.headers, ...(response.errorBody ? { errorBody: response.errorBody } : {}), at: Date.now() });
          const until = [429, 503].includes(response.status) ? retryAfter(response.headers["retry-after"], Date.now(), response.headers.date) : null;
          if (until !== null) serverFloor = { generation: userGeneration, route: attempt.url, until: Math.max(until, serverFloor?.route === attempt.url ? serverFloor.until : 0) };
        },
      }, () => automaticTurn !== null || contextGateError !== null);
      if (!adapter) return;
      adapter.setTransportHealth(() => transport?.intact() ?? false);
      recovery = new RecoveryController(store, config, adapter, undefined, undefined, (record) => {
        painter.publish("task-keeper", digest([record.scopeId, record.ownerEpoch, record.status, record.reason, record.notBefore, record.intentId]),
          now => recoveryStatusText(record, now), record.status === "WAITING_QUOTA");
      }, linuxProcessMonitor);
      if (recovery.state().reason === "restored_wait_reconciled") modelAuthorityGeneration = userGeneration;
      if (ctx.mode === "tui") removeTerminalInput = ctx.ui.onTerminalInput((data) => {
        if (isHumanTerminalInput(data)) { revokeModelTools(); recovery?.pause("user_terminal_input"); }
        return undefined;
      });
    } catch (error) {
      startupError = scrub(error instanceof Error ? error.message : "Task Keeper initialization failed");
      present(ctx, { taskKeeper: "disabled", reason: startupError }, true);
    }
  });

  pi.on("input", (event, ctx) => {
    update(ctx);
    if (event.source === "interactive" || event.source === "rpc") {
      userGeneration++; deniedCooldown = null;
      recovery?.pause("user_input"); userTurnPending = true;
    }
  });
  pi.on("before_agent_start", (_event, ctx) => {
    update(ctx);
    if (userTurnPending) { modelAuthorityGeneration = userGeneration; recovery?.beginUserTurn(); userTurnPending = false; }
  });
  pi.on("agent_start", (_event, ctx) => {
    update(ctx); lastResponse = null; finalSignal = undefined; requestSecrets = []; deniedCooldown = null;
    const record = recovery?.state(); automaticTurn = record?.status === "RUNNING" && record.intentId ? { intentId: record.intentId, epoch: record.ownerEpoch } : null;
    automaticRequestGuard = null;
  });
  // Some SDK error responses never call onResponse. Never reuse an earlier tool-turn's 200/headers.
  pi.on("before_provider_request", (_event, ctx) => {
    update(ctx); lastResponse = null; requestToken++; adapter?.beforeRequest();
    observeUsage(store,()=>{if(config)config.usage=readConfigForDirectory(configPath,ctx.cwd).usage;});
    if(!treeUsage?.hasActive() && !usageCapture?.hasActive())observeUsage(store,()=>usageCapture?.begin({sessionId:ctx.sessionManager.getSessionId(),provider:ctx.model?.provider??"unknown",model:ctx.model?.id??"unknown",modelVersion:ctx.model?modelBindingDigest(ctx.model):null,role:contextOperation?"compaction":"parent",accountPlanRef:config?usageAccountPlan(config.usage,ctx.model?.provider??"",ctx.model?.id??""):null,quotes:config?.usage.priceBooks},config?.usage.enabled===true));
    deniedControl = null;
    responseAuthorityGeneration = modelAuthorityGeneration;
    automaticRequestGuard = automaticTurn && recovery ? recovery.requestGuard(automaticTurn.intentId, automaticTurn.epoch) : null;
  });
  pi.on("after_provider_response", (event, ctx) => { update(ctx); lastResponse = { ...(lastResponse?.status === event.status ? lastResponse : {}), status: event.status, headers: event.headers }; });
  pi.on("tool_call", event => {
    if (!automaticTurn) return;
    if (event.toolName === "kernel_task" && ["status", "decisions", "usage", "models"].includes(String((event.input as {action?:unknown}).action))) return;
    try {
      const authority = toolAuthorities.get(event.toolCallId);
      if (authority === undefined || authority < 0 || authority !== userGeneration || !recovery) throw new ContractError("MODEL_CONTROL_REVOKED");
      recovery.authorizeControlledTool(automaticTurn.intentId, automaticTurn.epoch);
    } catch { return { block: true, reason: "MODEL_CONTROL_REVOKED" }; }
  });
  pi.on("tool_execution_start", (event, ctx) => { update(ctx);observeUsage(store,()=>usageCapture?.tool(`${ctx.sessionManager.getSessionId()}:${event.toolCallId}`,null)); adapter?.toolStarted(event.toolCallId, event.toolName); });
  pi.on("tool_execution_end", (event, ctx) => { update(ctx);observeUsage(store,()=>usageCapture?.tool(`${ctx.sessionManager.getSessionId()}:${event.toolCallId}`,!!event.isError)); adapter?.toolEnded(event.toolCallId, !!event.isError); });
  pi.on("message_end", (event, ctx) => {
    update(ctx); adapter?.persistedMessage();
    if (event.message.role !== "assistant") return;
    const message = event.message;
    observeUsage(store,()=>usageCapture?.end(message.usage,message.stopReason === "aborted" ? "cancelled" : ["stop","toolUse"].includes(message.stopReason) ? "success" : "failure"));
    for (const part of message.content) if (message.stopReason === "toolUse" && part.type === "toolCall") {
      if (toolAuthorities.size >= 1024) toolAuthorities.delete(toolAuthorities.keys().next().value!);
      toolAuthorities.set(part.id, responseAuthorityGeneration);
    }
    if (message.stopReason === "stop") finalSignal = null;
    else if (message.stopReason === "error" || message.stopReason === "aborted" || message.stopReason === "length") {
      const text = message.errorMessage ?? message.stopReason;
      finalSignal = terminalError(text, lastResponse, requestSecrets);
      if (deniedCooldown?.token === requestToken) finalSignal = { code: deniedCooldown.source === "shared" ? "SHARED_DOMAIN_NOT_BEFORE" : "SERVER_NOT_BEFORE",
        message: deniedCooldown.source === "shared" ? "Admission refused an unsent attempt while its shared recovery domain is waiting" : "Admission refused an unsent attempt until the observed server Retry-After expires",
        admission: deniedCooldown.network ? "transport-wait" : "retry-after", resetAt: deniedCooldown.until, stream: "error", responseObserved: false };
      if (deniedControl?.token === requestToken) finalSignal = { ...finalSignal, code: deniedControl.reason, controlRevoked: true };
      const recoveryState = recovery?.state();
      if (message.stopReason === "aborted" && automaticTurn && recoveryState?.intentId === automaticTurn.intentId
        && recoveryState.ownerEpoch === automaticTurn.epoch && recoveryState.reason === "request_timeout_termination_unknown") {
        finalSignal = { ...finalSignal, code: "RECOVERY_REQUEST_TIMEOUT", controlRevoked: true };
      }
      if (contextGateError) finalSignal = { ...finalSignal, code: contextGateError.code, admission: "context-limit",
        message: `${contextGateError.message}\nNative: ${finalSignal.message}`, responseObserved: false };
      if (store && config) {
        const route = recovery?.target().route ?? null;
        const failure = classify(finalSignal, recovery?.target().policy.rules ?? [], Date.now(), requestSecrets);
        store.put("native-errors", newId("native-error"), { ...failure, sessionId: ctx.sessionManager.getSessionId(), at: Date.now() });
      }
      if (message.stopReason === "length") finalSignal.code = "context_limit";
    }
  });
  pi.on("agent_settled", (_event, ctx) => {
    update(ctx); adapter?.persistedMessage();
    recovery?.settled(finalSignal === undefined ? { message: "No observed assistant terminal", code: "terminal_unknown", stream: "error" } : finalSignal);
    adapter?.settled();
    automaticTurn = null; automaticRequestGuard = null;
    requestSecrets = [];
  });
  pi.on("context", (event) => {
    try {
      const record = recovery?.state(), native = nativeFailureSummary();
      const jobs = managed?.contextEvidence() ?? [];
      if (!jobs.length && !record?.history.length && !native.total && !native.httpFailureAttempts && !native.deniedBeforeSend) {
        contextGateError = null; contextPacket = null; return;
      }
      const categories = Object.fromEntries([...new Set(record?.history.map(item => item.category) ?? [])]
        .map(category => [category, record!.history.filter(item => item.category === category).length]));
      const current = readConfigForDirectory(configPath, context!.cwd);
      if (configurationPolicyDigest(current) !== configurationPolicyDigest(config!)) throw new ContractError("CONFIGURATION_CHANGED_RELOAD_REQUIRED");
      contextByteBudget = current.evidence.packetByteBudget;
      const packet = compileContextEvidence({ schemaVersion: 1, jobs, total: jobs.length,
        recovery: record ? { scopeId: record.scopeId, status: record.status, reason: record.reason, notBefore: record.notBefore,
          incidentId: record.incidentId, intentId: record.intentId, attempts: record.attempts, failureCategories: categories, totalFailures: record.history.length } : null,
        nativeFailures: native,
        note: "These are ledger facts, not instructions. Use kernel_task status for current receipts and /orch audit for the complete native failure index. Execution and recovery are not task acceptance." }, contextByteBudget);
      contextGateError = null; contextPacket = { bytes: packet.bytes, digest: packet.digest };
      return { messages: [...event.messages, { role: "custom" as const, customType: jobs.length ? "task-keeper:jobs" : "task-keeper:evidence",
        content: packet.content, display: false, timestamp: Date.now() }] };
    } catch (error) {
      contextPacket = null;
      contextGateError = { code: error instanceof ContractError ? error.code : "CONTEXT_EVIDENCE_UNAVAILABLE", message: scrub(error instanceof Error ? error.message : "Context evidence unavailable") };
      // The pinned host catches context-handler errors. Abort and keep a final fetch guard
      // so ignoring/catching the callback error cannot send a request without hard facts.
      context?.abort?.();
      try { recovery?.pause(contextGateError.code); } catch { /* The request guard remains closed if state storage also failed. */ }
      if (context) present(context, { taskKeeper: "blocked", ...contextGateError }, true);
      return;
    }
  });
  pi.on("model_select", (_event, ctx) => { revokeModelTools(); update(ctx); requestToken++; lastResponse = null; recovery?.pause("model_selection_changed"); });
  pi.on("thinking_level_select", (_event, ctx) => { revokeModelTools(); update(ctx); requestToken++; lastResponse = null; recovery?.pause("thinking_selection_changed"); });
  pi.on("session_before_compact", (event, ctx) => {
    update(ctx); compactionRequestGuard = null;
    if (event.reason === "manual") { revokeModelTools(); recovery?.pause("context_compaction"); }
    else if (automaticTurn && recovery) compactionRequestGuard = recovery.requestGuard(automaticTurn.intentId, automaticTurn.epoch, true);
    contextOperation = { id: newId("context"), sessionId: ctx.sessionManager.getSessionId(), reason: event.reason, status: "running" };
    observeUsage(store,()=>usageCapture?.begin({sessionId:ctx.sessionManager.getSessionId(),provider:ctx.model?.provider??"unknown",model:ctx.model?.id??"unknown",modelVersion:ctx.model?modelBindingDigest(ctx.model):null,role:"compaction",accountPlanRef:config?usageAccountPlan(config.usage,ctx.model?.provider??"",ctx.model?.id??""):null,quotes:config?.usage.priceBooks},config?.usage.enabled===true));
    store?.put("context-operations", contextOperation.id, contextOperation);
    adapter?.contextChanging(true);
  });
  pi.on("session_compact", event => {
    observeUsage(store,()=>usageCapture?.end(event.fromExtension?undefined:event.compactionEntry?.usage,"success",Date.now(),"operation-aggregate"));
    adapter?.contextChanging(false); compactionRequestGuard = null;
    if (contextOperation) store?.put("context-operations", contextOperation.id, { ...contextOperation, status: "completed" });
    contextOperation = null;
  });
  pi.on("session_compact_failed", event => {
    observeUsage(store,()=>usageCapture?.end(undefined,"failure"));
    adapter?.contextChanging(false); compactionRequestGuard = null;
    if (contextOperation && store && config) {
      const error = scrub(event.errorMessage ?? (event.aborted ? "compaction_aborted" : "compaction_failed"), requestSecrets);
      store.put("context-operations", contextOperation.id, { ...contextOperation, status: "failed", error });
      const route = recovery?.target().route ?? null;
      const failure = classify(terminalError(error, lastResponse, requestSecrets), recovery?.target().policy.rules ?? [], Date.now(), requestSecrets);
      store.put("native-errors", contextOperation.id, { ...failure, sessionId: contextOperation.sessionId, source: "compaction", at: Date.now() });
      if (recovery?.state().status !== "PAUSED") recovery?.pause("context_compaction_failed");
    }
    contextOperation = null;
  });
  pi.on("session_before_switch", () => { revokeModelTools(); recovery?.pause("session_switch"); });
  pi.on("session_before_fork", () => { revokeModelTools(); recovery?.pause("session_fork"); });
  pi.on("session_before_tree",(event,ctx)=>{
    revokeModelTools();update(ctx);recovery?.pause("branch_navigation");
    if(event.preparation.userWantsSummary&&event.preparation.entriesToSummarize.length)observeUsage(store,()=>treeUsage?.begin({sessionId:ctx.sessionManager.getSessionId(),provider:ctx.model?.provider??"unknown",model:ctx.model?.id??"unknown",modelVersion:ctx.model?modelBindingDigest(ctx.model):null,role:"branch-summary",accountPlanRef:config?usageAccountPlan(config.usage,ctx.model?.provider??"",ctx.model?.id??""):null,quotes:config?.usage.priceBooks},config?.usage.enabled===true));
  });
  pi.on("session_tree", (event, ctx) => { revokeModelTools();update(ctx);recovery?.pause("branch_changed");
    observeUsage(store,()=>treeUsage?.end(event.fromExtension?undefined:event.summaryEntry?.usage,event.summaryEntry?"success":"cancelled",Date.now(),"operation-aggregate"));
  });
  pi.on("session_shutdown", async () => { statusPublisher?.dispose(); statusPublisher = null; revokeModelTools(); recovery?.dispose(); adapter?.dispose(); transport?.dispose(); requestSecrets = []; removeTerminalInput?.(); removeTerminalInput = null;
    await managed?.dispose(); managed = null; store?.close(); store = null;
  });

  async function command(args: string, ctx: ExtensionContext) {
    update(ctx);
    let [action = "status", ...rest] = args.trim().split(/\s+/).filter(Boolean);
    if(action === "task"){action=rest.shift()??"";if(!["begin","finish","accept","reassign"].includes(action)){present(ctx,"Use /orch task begin|finish|accept|reassign",true);return;}}
    if(action === "finish" && rest[1] === "--accept"){action="accept";rest=rest.slice(0,1);}
    try {
      if (["usage","models","begin","finish","accept","reassign"].includes(action)) {
        if (!store || !config?.enabled) throw new ContractError("TASK_KEEPER_DISABLED");
        const ledger=new UsageLedger(store);
        if(action === "begin") {
          const parsed=submission(rest.join(" "));if(Object.keys(parsed.options).some(key=>key!=="comparisonGroup"))throw new ContractError("UNSUPPORTED_USAGE_BEGIN_OPTION");
          present(ctx,ledger.begin({sessionId:ctx.sessionManager.getSessionId(),title:parsed.goal,comparisonGroup:parsed.options.comparisonGroup??null,
            contractDigest:digest(["interactive",[...pi.getActiveTools()].sort(),config.executionProfiles[config.recovery.profileRef??"interactive"]??null])}));return;
        }
        if(action === "finish" || action === "accept") { present(ctx,ledger.finish(rest[0],action === "accept"?"accepted":"finished","user")); return; }
        if(action === "reassign") { if(!ledger.hasGeneration(rest[0]))throw new ContractError("USAGE_GENERATION_NOT_FOUND");ledger.link(rest[0],rest[1],"user-reassignment");present(ctx,ledger.query({taskId:rest[1]}));return; }
        if(action === "models") {if(rest.length && (rest[0]!=="--group"||rest.length!==2))throw new ContractError("MODELS_GROUP_ARGUMENT_REQUIRED");present(ctx,modelComparison(ledger,{from:Date.now()-config.usage.defaultRangeDays*86400000,...(rest[1]?{comparisonGroup:rest[1]}:{})}));return;}
        if(rest[1]){
          if(rest[1]!=="--reprice-at"||rest.length!==3)throw new ContractError("USAGE_REPRICE_ARGUMENT_REQUIRED");
          const at=instant(rest[2]),quotes=readConfigForDirectory(configPath,ctx.cwd).usage.priceBooks;
          present(ctx,{tasks:ledger.query({taskId:rest[0]}),reestimated:repricingView(ledger.facts(rest[0]),quotes,at)});return;
        }
        present(ctx,ledger.query(rest[0]?{taskId:rest[0]}:{from:Date.now()-config.usage.defaultRangeDays*86400000}));return;
      }
      if (action === "init") { present(ctx, { code: "AGENTCFG_CONFIGURATION_REQUIRED", exit_code: 2,
        message: "在 agentcfg local.toml 中绑定 task_keeper 模型、项目根和检查；通过 plan/apply 部署后重新启动 Pi。", example: "examples/pi-managed.toml" }, true); return; }
      if(action === "second-opinion")throw new ContractError("SECOND_OPINION_REQUIRES_MANAGED_TASK","Use /orch inspect|fix --second-opinion -- <goal>. Existing streamed chat is not held or rewritten.");
      if(action === "schedule") {
        if(!managed || !["inspect","fix"].includes(rest[0]))throw new ContractError("SCHEDULE_MANAGED_WORKFLOW_REQUIRED");
        const parsed=submission(rest.slice(1).join(" "));if(parsed.options.notBefore===undefined)throw new ContractError("SCHEDULE_ABSOLUTE_TIME_REQUIRED");
        present(ctx,managed.describe(managed.submit(rest[0] as "inspect"|"fix",parsed.goal,parsed.options).id));return;
      }
      if (["inspect", "fix"].includes(action)) {
        if (!managed) throw new Error("Managed workflows are disabled; bind roles and check IDs first.");
        const parsed=submission(rest.join(" "));present(ctx, managed.describe(managed.submit(action as "inspect" | "fix", parsed.goal,parsed.options).id)); return;
      }
      if (action === "refresh-bindings") {
        if (!managed || !rest[0]) throw new Error("Use /orch refresh-bindings <pausedJobId> to review the current local model catalog.");
        recovery?.pause("model_registry_refresh"); await managed.refreshBindings(rest[0]); present(ctx, managed.describe(rest[0])); return;
      }
      if (action === "approve-bindings") {
        if (!managed || !rest[0] || !rest[1]) throw new Error("Use /orch approve-bindings <jobId> <digest> after reviewing the binding change and retained candidate.");
        await managed.approveBindings(rest[0], rest[1]); present(ctx, managed.describe(rest[0])); return;
      }
      if (action === "approve-checks") {
        if (!managed || !rest[0] || !rest[1]) throw new Error("Use /orch approve-checks <jobId> <digest> after reviewing the changed acceptance inputs.");
        await managed.approveChecks(rest[0], rest[1]); present(ctx, managed.describe(rest[0])); return;
      }
      if (action === "decisions" && rest[0] && managed) { present(ctx, await managed.decisions(rest[0])); return; }
      if (action === "propose") {
        if (!managed || !rest[0]) throw new Error("Use /orch propose <jobId> <StepProposal JSON>");
        const payload = args.trim().slice(action.length).trim().slice(rest[0].length).trim();
        let proposal: unknown;
        try { proposal = JSON.parse(payload); }
        catch { managed.rejectProposal(rest[0], "INVALID_PROPOSAL_JSON"); throw new ContractError("INVALID_PROPOSAL_JSON"); }
        present(ctx, await managed.propose(rest[0], proposal)); return;
      }
      if (["status", "doctor", "audit", "evidence", "decisions"].includes(action)) {
        present(ctx, rest[0] && managed ? await managed.inspect(rest[0]) : action === "audit" ? { ...status(), nativeFailureIndex: nativeFailures() } : status()); return;
      }
      if (rest[0] && managed && ["pause", "resume", "stop"].includes(action)) {
        if (action === "resume") await managed.resume(rest[0],true); else { managed.pause(rest[0], action === "stop"); revokeModelTools(); }
        present(ctx, managed.describe(rest[0])); return;
      }
      if (!recovery) throw new Error("Task Keeper recovery is not enabled; use /orch doctor.");
      if (action === "pause") { recovery.pause(); revokeModelTools(); }
      else if (action === "resume") { recovery.resume(); modelAuthorityGeneration = userGeneration; }
      else if (action === "stop") { recovery.stop(); revokeModelTools(); }
      else throw new Error("Supported now: doctor, status, audit, evidence, decisions, init, pause, resume, stop. Use inspect/fix <goal> or status/pause/resume/stop <jobId> for managed jobs.");
      present(ctx, status());
    } catch (error) {
      const code = error instanceof ContractError ? error.code : (error as any)?.code ?? "TASK_KEEPER_COMMAND_FAILED";
      const exitCode = (error as any)?.exitCode ?? (/CAPABILITY|UNSUPPORTED_TRANSPORT|RUNTIME|EVIDENCE_MISSING/.test(code) ? 5 : /BINDING|CONFIG|MODEL|CHECK|SCHEDULE_ABSOLUTE/.test(code) ? 2 : 4);
      present(ctx, { code, exit_code: exitCode }, true);
    }
  }
  // Registration is gated at load time so a recovery-only session retains its certified built-in tool set.
  let registerManaged = false;
  try { const initial = readConfigForDirectory(configPath, process.cwd()); registerManaged = initial.enabled && initial.features.managedWorkflows; } catch { /* doctor reports configuration errors. */ }
  if (registerManaged) pi.registerTool({ name: "kernel_task", label: "Task Keeper", description: "Submit a bounded inspect/fix job or inspect/control an existing job. Completion requires an independent receipt. Jobs run in retained worktrees.",
    parameters: kernelTaskParameters(),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const authority = toolAuthorities.get(_id); toolAuthorities.delete(_id);
      if (!["status", "decisions", "usage", "models"].includes(params.action) && (authority === undefined || authority < 0 || authority !== userGeneration))
        throw new ContractError("MODEL_CONTROL_REVOKED");
      update(ctx);
      if (!managed) throw new Error("Managed workflows disabled");
      let result: unknown;
      if (params.action === "inspect" || params.action === "fix") result = managed.describe(managed.submit(params.action, params.goal ?? "",{},config?.usage.enabled&&store?new UsageLedger(store).current(ctx.sessionManager.getSessionId()).id:undefined).id);
      else if(params.action === "models")result=store?modelComparison(new UsageLedger(store),{from:Date.now()-(config?.usage.defaultRangeDays??30)*86400000}):[];
      else if(params.action === "usage"){
        if(!store)throw new ContractError("USAGE_STORE_UNAVAILABLE");
        const ids=params.jobId?[managed.get(params.jobId).analyticsTaskId??params.jobId]:managed.list().map(job=>job.analyticsTaskId??job.id);
        const ledger=new UsageLedger(store),active=ledger.activeTask(ctx.sessionManager.getSessionId());if(!params.jobId&&active)ids.push(active.id);
        result=[...new Set(ids)].flatMap(taskId=>ledger.query({taskId}));
      }
      else if (!params.jobId) { if (params.action !== "status") throw new Error("jobId is required"); result = managed.overview(); }
      else if (params.action === "decisions") result = await managed.decisions(params.jobId);
      else if (params.action === "propose") result = await managed.propose(params.jobId, params.proposal, () => authority === userGeneration);
      else { if (params.action === "resume") await managed.resume(params.jobId);
        else if (params.action === "pause" || params.action === "stop") managed.pause(params.jobId, params.action === "stop");
        result = await managed.inspect(params.jobId);
      }
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });
  pi.registerCommand("orch", { description: "Task Keeper status, audit and control", handler: command });
  pi.registerCommand("throttle", { description: "Task Keeper quota recovery status and control", handler: command });
}
