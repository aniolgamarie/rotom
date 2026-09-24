import { assertWriterAllowed } from "../contracts/writers.ts";
import { createHash } from "node:crypto";
import { readQuotaTelemetry } from "./telemetry.ts";
import { runtimeIdentity } from "./runtime-identity.ts";
import { taskKeeperRuntimeIdentity } from "./task-keeper-identity.ts";
import { fetchDelegatesTo } from "./http-transport.ts";
import { routeRequirements } from "./route-requirements.ts";
import { modelBindingDigest } from "./capabilities.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, mkdirSync, realpathSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { configurationPolicyDigest, type Config } from "../config.ts";
import { Store, type Owner } from "../store/database.ts";
import { ContractError, newId, canonical, digest } from "../contracts/primitives.ts";
import { processIdentity, originalProcessStopped } from "./process-identity.ts";
import { childPhysicallyStopped, type ChildDescriptor, type ChildObservation } from "./child-contract.ts";
import { projectReference } from "../workspace/worktree.ts";
import { scrub } from "../reliability/classifier.ts";
import { settleExecutionTransportLeases } from "../reliability/incidents.ts";

const REQUEST = "prompt-template:subagent:request", RESPONSE = "prompt-template:subagent:response";
const CANCEL = "prompt-template:subagent:cancel";
// Pi's TypeScript loader can expose a partially evaluated module to a concurrent
// dynamic importer. Share the in-flight import before invoking the loader itself.
const runtimeModules = new Map<string, Promise<any>>();
function runtimeModule(name: string): Promise<any> {
  let pending = runtimeModules.get(name);
  if (!pending) {
    pending = Promise.resolve().then(() => import(name)); runtimeModules.set(name, pending);
    void pending.catch(() => { if (runtimeModules.get(name) === pending) runtimeModules.delete(name); });
  }
  return pending;
}
function parentHelperGateCovered(scope: { recoveryOwnerGateHealthy(): boolean }): boolean {
  return scope.recoveryOwnerGateHealthy() || fetchDelegatesTo(
    (globalThis as typeof globalThis & { [key: symbol]: unknown })[Symbol.for("pi-subagents.recovery-owner.fetch.v2")]);
}
/** A blocked managed helper must reach its inner guard before touching main-session observations. */
export function activeManagedParentGuard(method: string): typeof fetch | null {
  if (method !== "POST") return null;
  const registry = globalThis as typeof globalThis & { [key: symbol]: any };
  return registry[Symbol.for("pi-subagents.recovery-owner.v2")]?.getStore()
    ? registry[Symbol.for("pi-subagents.recovery-owner.fetch.v2")] ?? null : null;
}
export interface DelegationResult {
  descriptorId: string; nativeRunId: string | null; status: "ended" | "failed" | "unknown";
  nativeStatus?: string | null; nativeExitCode?: number | null;
  modelIdentity?: { requested: { provider: string; model: string }; runtimeObservationSource: "client_configuration";
    responseModel: null; serverWeights: "unverified" };
  terminationConfirmed: boolean; content: unknown; error: string | null; observations: ChildObservation[]; parentHelperDenials?: string[];
  notSent?: boolean;
}

export class SubagentsAdapter {
  private pi: ExtensionAPI;
  private store: Store;
  private config: Config;
  private owner: Owner;
  constructor(pi: ExtensionAPI, store: Store, config: Config, owner: Owner) {
    this.pi = pi; this.store = store; this.config = config; this.owner = owner;
  }
  async preflight(agent: string, task: string, cwd: string, model: string, thinking: string, ctx: ExtensionContext, resultSchema?: Record<string, unknown>) {
    taskKeeperRuntimeIdentity();
    if (!runtimeIdentity().supported) throw new ContractError("PARENT_RUNTIME_NOT_CERTIFIED");
    if (!["rpc", "tui"].includes(ctx.mode)) throw new ContractError("PARENT_MODE_NOT_CERTIFIED");
    const require = createRequire(import.meta.url);
    const root = dirname(require.resolve("pi-subagents"));
    const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
    const lock = JSON.parse(readFileSync(new URL("./subagents-lock.json", import.meta.url), "utf8")) as { files: Record<string, string> };
    for (const [file, hash] of Object.entries(lock.files)) if (createHash("sha256").update(readFileSync(join(root, file))).digest("hex") !== hash) throw new ContractError("SUBAGENTS_SOURCE_LOCK_MISMATCH", file);
    if (pkg.version !== "0.63.0") throw new ContractError("SUBAGENTS_VERSION_NOT_CERTIFIED");
    const runtime = readFileSync(join(root, "src/runs/shared/subagent-prompt-runtime.ts"), "utf8");
    if (!runtime.includes("task-keeper-required-tools-abort-v1")) throw new ContractError("SUBAGENTS_REQUIRED_TOOLS_PATCH_REQUIRED");
    const moduleName = "pi-subagents/preflight";
    const api = await runtimeModule(moduleName);
    this.store.assertOwner(this.owner);
    const registrationModule = "pi-subagents/agents";
    const registrations = await runtimeModule(registrationModule);
    this.store.assertOwner(this.owner);
    const readiness = registrations.registerAgentViaEvents({ pi: this.pi, name: newId("task-keeper-readiness"),
      definition: { description: "Task Keeper adapter readiness probe", systemPrompt: "No execution.", tools: [], inheritSkills: false } });
    readiness.dispose();
    const probeId = newId("probe"), replies: Array<{ entry: string; version: string }> = [];
    const unsubscribeProbe = this.pi.events.on("subagent:recovery-owner-ready", (value: unknown) => {
      const reply = value as { id?: string; entry: string; version: string }; if (reply?.id === probeId) replies.push(reply);
    });
    try { this.pi.events.emit("subagent:recovery-owner-probe", { id: probeId }); } finally { unsubscribeProbe(); }
    if (replies.length !== 1 || replies[0].version !== "task-keeper-recovery-owner-v2"
      || realpathSync(fileURLToPath(replies[0].entry)) !== realpathSync(join(root, "index.ts"))) throw new ContractError("ACTIVE_SUBAGENTS_RUNTIME_NOT_CERTIFIED");
    const result = await api.resolveSubagentLaunchContract({ agent, task, cwd, context: "fresh", model, thinking,
      skill: false, artifacts: true, outputSchema: resultSchema, parentModel: ctx.model, availableModels: ctx.modelRegistry.getAvailable(), parentSessionFile: ctx.sessionManager.getSessionFile() });
    this.store.assertOwner(this.owner);
    if (!result?.ok) throw new ContractError("SUBAGENTS_PREFLIGHT_FAILED", result?.message ?? "unknown preflight failure");
    const contract = result.contract;
    const expectedFile = realpathSync(fileURLToPath(new URL(`../../agents/${agent}.md`, import.meta.url)));
    const expectedReporter = realpathSync(fileURLToPath(new URL("./child-reporter.ts", import.meta.url)));
    if (realpathSync(contract.agent.filePath) !== expectedFile || contract.context !== "fresh"
      || !contract.tools.disableAmbientExtensions || contract.modelCandidates.length !== 1
      || contract.tools.configuredExtensions.length !== 1 || realpathSync(contract.tools.configuredExtensions[0]) !== expectedReporter
      || contract.tools.effectiveAllowlist.some((tool: string) => !["tk_read", "tk_write", "tk_edit", "tk_find", "tk_grep", "tk_ls", "structured_output"].includes(tool))) {
      throw new ContractError("SUBAGENTS_LAUNCH_CONTRACT_MISMATCH");
    }
    return contract;
  }

  async execute(...args: Parameters<SubagentsAdapter["executeOwned"]>): Promise<DelegationResult> {
    const scope = await runtimeModule("pi-subagents/recovery-owner");
    if (scope.recoveryOwnerVersion !== "task-keeper-recovery-owner-v2") throw new ContractError("RECOVERY_OWNER_INTERFACE_REQUIRED");
    if (!parentHelperGateCovered(scope)) throw new ContractError("PARENT_HELPER_GATE_CHANGED");
    const [input, ctx, signal, onDispatch] = args;
    const denials: string[] = [];
    return scope.withRecoveryOwner(async () => {
      try {
        const result = await this.executeOwned(input, ctx, signal, () => {
          if (!parentHelperGateCovered(scope)) throw new ContractError("PARENT_HELPER_GATE_CHANGED");
          if (onDispatch?.constructor.name === "AsyncFunction") throw new ContractError("ASYNC_DISPATCH_GUARD_NOT_SUPPORTED");
          const value: unknown = onDispatch?.();
          if (value && typeof (value as { then?: unknown }).then === "function") {
            void Promise.resolve(value).catch(() => {}); throw new ContractError("ASYNC_DISPATCH_GUARD_NOT_SUPPORTED");
          }
        });
        return { ...result, parentHelperDenials: denials };
      } catch (error) { if (denials.length) throw new ContractError("UNBUDGETED_PARENT_HELPER_DENIED"); throw error; }
    }, () => {
      const id = newId("helper-denied"); denials.push(id);
      this.store.put("parent-helper-denials", id, { jobId: input.jobId, stepId: input.stepId, scopeId: this.owner.scopeId, reason: "unbudgeted_parent_helper", at: Date.now() });
    });
  }
  private async executeOwned(input: { jobId: string; stepId: string; role: "scout" | "worker" | "reviewer"; task: string; cwd: string;
    evidenceIds?: string[]; parentIntentId?: string; routeId?: string; profileRef?: string; incidentId?: string; minimumRemaining?: number; resultSchema?: Record<string, unknown> },
    ctx: ExtensionContext, signal?: AbortSignal, onDispatch?: () => void): Promise<DelegationResult> {
    this.store.assertOwner(this.owner);
    if (!this.config.enabled || !this.config.features.managedWorkflows) throw new ContractError("MANAGED_WORKFLOWS_DISABLED");
    if (signal?.aborted) throw new ContractError("DELEGATION_CANCELLED_BEFORE_START");
    if (input.role === "worker") assertWriterAllowed(this.config.limits.writersPerJob);
    const configuredRole = this.config.roles[input.role];
    const job = this.store.get<{modelSelection?:{selected:string|null};opinion?:{route:string};workflow:string}>("managed-jobs",input.jobId);
    const initialChoice = job && ((input.stepId === (job.workflow === "fix" ? "implement" : "inspect") && job.modelSelection?.selected === input.routeId)
      || (input.stepId === "second-opinion" && job.opinion?.route === input.routeId));
    if (input.routeId && input.routeId !== configuredRole?.route && !initialChoice && !this.config.features.crossProviderFailover) throw new ContractError("ROUTE_OVERRIDE_DISABLED");
    const role = configuredRole ? { route: input.routeId ?? configuredRole.route, profileRef: input.profileRef ?? configuredRole.profileRef } : undefined;
    const route = role && this.config.routes[role.route], profile = role && this.config.executionProfiles[role.profileRef];
    if (!role || !route || !profile?.thinking || !this.config.allowedRoutes.includes(role.route)) throw new ContractError("ROLE_BINDING_REQUIRED");
    if (this.config.network[route.network].type !== "direct") throw new ContractError("NETWORK_BINDING_NOT_CERTIFIED");
    if (!readQuotaTelemetry(this.config, route).eligible) throw new ContractError("QUOTA_TELEMETRY_NOT_ELIGIBLE");
    const capabilities = new Set(["events", "termination", "workspace"]);
    if (input.role !== "worker") capabilities.add("readonly");
    if (route.protected) capabilities.add("requestGate");
    if (profile.requiredCapabilities.some((capability) => !capabilities.has(capability))) throw new ContractError("CHILD_CAPABILITY_NOT_AVAILABLE");
    if (input.incidentId && !route.protected) throw new ContractError("BACKUP_REQUIRES_PROTECTED_ROUTE");
    const origin = this.store.get<{ sourceCwd: string }>("managed-jobs", input.jobId)?.sourceCwd ?? ctx.cwd;
    const approved = this.config.projectRouteApprovals[projectReference(origin)] ?? this.config.projectRouteApprovals["*"] ?? [];
    if (!approved.includes(role.route)) throw new ContractError("PROJECT_ROUTE_NOT_APPROVED");
    const parentProcess = processIdentity(); if (!parentProcess) throw new ContractError("PARENT_PROCESS_IDENTITY_UNKNOWN");
    const model = ctx.modelRegistry.find(route.provider, route.model); if (!model) throw new ContractError("MODEL_NOT_IN_REGISTRY");
    const requirements = routeRequirements(model, profile, input.role, route.protected);
    if (!requirements.eligible) throw new ContractError("ROUTE_REQUIREMENTS_UNSATISFIED", requirements.reasons.join(","));
    const readOnly = input.role !== "worker";
    const expectedTools = readOnly ? ["read", "grep", "find", "ls"] : ["read", "grep", "find", "ls", "write", "edit"];
    if (expectedTools.some((tool) => !profile.tools.includes(tool)) || profile.tools.some((tool) => !expectedTools.includes(tool))) throw new ContractError("ROLE_TOOL_PROFILE_MISMATCH");
    const id = newId("descriptor"), nonce = newId("grant");
    const descriptor: ChildDescriptor = { analyticsTaskId:this.store.get<{analyticsTaskId?:string}>("managed-jobs",input.jobId)?.analyticsTaskId??input.jobId, id, nonce, owner: this.owner, parentProcess, jobId: input.jobId, stepId: input.stepId,
      cwd: realpathSync(input.cwd), storePath: this.store.path, provider: route.provider, model: route.model, thinking: profile.thinking,
      modelDigest: modelBindingDigest(model), runtimeDigest: taskKeeperRuntimeIdentity(),
      routeId: role.route, sourceCwd: origin, policyDigest: configurationPolicyDigest(this.config),
      readOnly, timeoutMs: profile.timeoutMs, maxModelTurns: profile.maxModelTurns, expiresAt: Math.min(Date.now() + profile.timeoutMs, this.store.get<{schedule?:{deadline:number|null}}>("managed-jobs",input.jobId)?.schedule?.deadline ?? Infinity),
      maxChildren: this.config.limits.activeChildrenPerHost, maxReaders: this.config.limits.parallelReaders, protected: route.protected,
      budgetLimits: route.protected ? [{ id: `work-${this.owner.scopeId}`, ceiling: this.config.budget.protectedAttemptsPerWorkScope, minimumRemaining: input.minimumRemaining ?? 0 },
        ...(input.incidentId ? [{ id: `incident-${input.incidentId}`, ceiling: this.config.budget.backupAttemptsPerIncident }] : [])] : [],
      allowedArtifacts: (input.evidenceIds ?? []).map((id) => {
        const artifact = this.store.get<{ jobId: string; snapshot: string }>("artifacts", id);
        if (!artifact || artifact.jobId !== input.jobId) throw new ContractError("EVIDENCE_SCOPE_MISMATCH");
        return { id, snapshot: artifact.snapshot };
      }) };
    const directory = join(this.store.root, "child-contexts"); mkdirSync(directory, { recursive: true, mode: 0o700 });
    writeFileSync(join(directory, `${id}.json`), canonical(descriptor), { flag: "wx", mode: 0o600 });
    const grant = (active: boolean, stop = false) => this.store.put("child-grants", id, { nonce, active, stop, jobId: input.jobId, stepId: input.stepId,
      parentIntentId: input.parentIntentId ?? null, routeId: role.route, provider: route.provider, model: route.model });
    grant(true);
    const agent = input.role === "worker" ? "task-keeper-writer" : input.role === "reviewer" ? "task-keeper-reviewer" : "task-keeper-reader";
    const task = `TASK_KEEPER_DESCRIPTOR:${id}\n${input.task}`;
    try { await this.preflight(agent, task, descriptor.cwd, `${route.provider}/${route.model}`, profile.thinking, ctx, input.resultSchema); }
    catch (error) { grant(false); throw error; }
    this.store.assertOwner(this.owner);
    const request = { requestId: id, ownerRunId: input.jobId, nodeId: input.stepId, agent, task, cwd: descriptor.cwd, context: "fresh",
      model: `${route.provider}/${route.model}`, thinking: profile.thinking, timeoutMs: profile.timeoutMs,
      skill: false, artifacts: true, result: input.resultSchema ? { kind: "structured", schema: input.resultSchema } : { kind: "text" } };
    let dispatched = false;
    const response = await new Promise<Record<string, unknown>>((resolveResult) => {
      let finished = false;
      let cancelTimer: ReturnType<typeof setTimeout> | null = null;
      const cancel = () => {
        grant(false, true);
        try { this.pi.events.emit(CANCEL, { requestId: id, ownerRunId: input.jobId, nodeId: input.stepId }); } catch { /* The persistent grant also revokes the child. */ }
        cancelTimer ??= setTimeout(() => finish({ status: "cancelled", error: "cancelled; reconcile process evidence" }), 1500);
      };
      const finish = (value: Record<string, unknown>) => {
        if (finished) return; finished = true; unsubscribe(); clearTimeout(timer); if (cancelTimer) clearTimeout(cancelTimer);
        signal?.removeEventListener("abort", cancel); resolveResult(value);
      };
      const unsubscribe = this.pi.events.on(RESPONSE, (value: unknown) => {
        const response = value as Record<string, unknown>;
        if (response?.requestId === id && response.ownerRunId === input.jobId && response.nodeId === input.stepId) finish(response);
      });
      const timer = setTimeout(() => { cancel(); finish({ status: "unknown", error: "delegation terminal response unavailable" }); }, profile.timeoutMs + 3000);
      signal?.addEventListener("abort", cancel, { once: true });
      if (signal?.aborted) { grant(false, true); finish({ status: "cancelled", error: "cancelled_before_dispatch" }); return; }
      try {
        onDispatch?.();
        if (signal?.aborted) { grant(false, true); finish({ status: "cancelled", error: "cancelled_before_dispatch" }); return; }
        dispatched = true;
        this.pi.events.emit(REQUEST, Object.freeze({ ...request, result: Object.freeze(request.result) }));
      } catch (error) { grant(false, true); finish({ status: "unknown", error: error instanceof Error ? scrub(error.message) : "dispatch interrupted before acknowledgement" }); }
    });
    grant(false);
    const observations = this.store.list<ChildObservation>("child-observations").map((entry) => entry.value).filter((value) => value.descriptorId === id);
    const failurePath = join(this.store.root, "child-errors", `${id}.json`);
    const reportedFailure = existsSync(failurePath) ? JSON.parse(readFileSync(failurePath, "utf8")) : null;
    const failedStartupStopped = reportedFailure?.nonce === nonce && reportedFailure.process && originalProcessStopped(reportedFailure.process) === true;
    const terminated = !dispatched || (observations.length > 0 ? observations.every(childPhysicallyStopped) : !!failedStartupStopped);
    if (terminated) for (const observation of observations) this.store.settle(observation.leaseId, "terminated");
    if (terminated) settleExecutionTransportLeases(this.store, id);
    const healthy = typeof response.runId === "string" && response.runId.length > 0
      && observations.length === 1 && observations[0].ready && observations[0].settled && (!route.protected || observations[0].requestGate)
      && (observations[0].stopReason === "stop" || (!!input.resultSchema && observations[0].stopReason === "toolUse"))
      && !observations[0].contextOperations?.some(operation => operation.status === "running")
      && observations[0].activeTools.length === 0 && observations[0].provider === route.provider && observations[0].model === route.model
      && observations[0].modelDigest === descriptor.modelDigest
      && observations[0].runtimeDigest === descriptor.runtimeDigest
      && observations[0].thinking === profile.thinking && this.store.sequenceGaps(this.owner.scopeId).length === 0 && this.store.issues(this.owner.scopeId).length === 0;
    const reporterError = reportedFailure?.error ?? null;
    return { descriptorId: id, nativeRunId: typeof response.runId === "string" ? response.runId : null,
      nativeStatus: typeof response.status === "string" ? response.status : null, nativeExitCode: typeof response.exitCode === "number" ? response.exitCode : null,
      // The pinned SDK records its configured model on AssistantMessage. It does
      // not expose the SSE model field here, and neither field proves weights.
      modelIdentity: { requested: { provider: route.provider, model: route.model }, runtimeObservationSource: "client_configuration", responseModel: null, serverWeights: "unverified" },
      status: !terminated ? "unknown" : healthy && response.status === "completed" && response.exitCode === 0 && !signal?.aborted ? "ended" : "failed",
      terminationConfirmed: terminated, notSent: !dispatched, content: response.result ?? null,
      error: reporterError ?? observations.at(-1)?.lastError ?? (typeof response.error === "string" ? scrub(response.error)
        : response.status !== "completed" ? `native_delegation_${typeof response.status === "string" ? response.status : "unknown"}`
        : healthy ? null : "child evidence incomplete"), observations };
  }
}
