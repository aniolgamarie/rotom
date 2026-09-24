import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { readFileSync, realpathSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import type { Config } from "../config.ts";
import { ContractError, digest, newId, identifier } from "../contracts/primitives.ts";
import { terminalError } from "../reliability/classifier.ts";
import { installHttpTransport } from "./http-transport.ts";
import { runtimeIdentity } from "./runtime-identity.ts";
import { taskKeeperRuntimeIdentity } from "./task-keeper-identity.ts";
import { modelBindingDigest } from "./capabilities.ts";
import type { InteractiveAdapter, InteractiveSnapshot, RequestGuard } from "../reliability/recovery.ts";

const CONTROL_TYPE = "task-keeper:continuation:v1";
const SAFE_TOOLS = new Set(["read", "write", "edit", "grep", "find", "ls"]);

export function inspectRuntimeProfile(argv = process.argv): { supported: boolean; reasons: string[]; version: string | null } {
  const reasons: string[] = [];
  if (!runtimeIdentity(argv).supported) reasons.push("runtime_identity_not_in_contract_matrix");
  let version: string | null = null;
  try {
    const candidate = JSON.parse(readFileSync(new URL("./runtime-candidate.json", import.meta.url), "utf8"));
    const cli = realpathSync(argv[1]);
    const pkg = JSON.parse(readFileSync(join(dirname(cli), "../../package.json"), "utf8"));
    version = pkg.version;
    if (pkg.name !== "@earendil-works/pi-coding-agent" || version !== candidate.version
      || createHash("sha256").update(readFileSync(cli)).digest("hex") !== candidate.cliSha256) reasons.push("runtime_not_in_contract_test_matrix");
    if (!(argv.includes("--no-extensions") || argv.includes("-ne"))) reasons.push("ambient_extension_path_not_certified");
    const extensions: string[] = [];
    for (let i = 2; i < argv.length; i++) {
      if (["-e", "--extension"].includes(argv[i])) extensions.push(realpathSync(resolve(argv[++i])));
    }
    const entry = realpathSync(fileURLToPath(new URL("../../index.ts", import.meta.url)));
    let extensionSetVerified = extensions.length === 1 && extensions[0] === entry;
    if (extensions.length === 2 && new Set(extensions).size === 2 && extensions.includes(entry)) {
      const subagentsEntry = realpathSync(createRequire(import.meta.url).resolve("pi-subagents")), subagentsRoot = dirname(subagentsEntry);
      const lock = JSON.parse(readFileSync(new URL("./subagents-lock.json", import.meta.url), "utf8")) as { version: string; files: Record<string, string> };
      const installed = JSON.parse(readFileSync(join(subagentsRoot, "package.json"), "utf8"));
      extensionSetVerified = extensions[0] === subagentsEntry && extensions[1] === entry && installed.version === lock.version
        && Object.entries(lock.files).every(([file, hash]) => createHash("sha256").update(readFileSync(join(subagentsRoot, file))).digest("hex") === hash);
    }
    if (!extensionSetVerified) reasons.push("extension_set_not_in_contract_test_matrix");
  } catch { reasons.push("runtime_identity_unavailable"); }
  return { supported: reasons.length === 0, reasons, version };
}

export class PiInteractiveAdapter implements InteractiveAdapter {
  private pi: ExtensionAPI;
  private config: Config;
  private context: ExtensionContext;
  private activeTools = new Set<string>();
  private toolNames = new Map<string, string>();
  private uncertainTools = new Set<string>();
  private waiters = new Set<() => void>();
  private automatic = false;
  private usageObserver: null | {begin(target:{sessionId:string;provider:string;model:string;modelVersion:string}):void;attempt(id:string):void;response(id:string,status:number):void;notSent(id:string):void;metering(id:string,zero:boolean):void;active():boolean;end(usage:unknown,outcome:"success"|"failure"|"cancelled"|"unknown"):void}=null;
  setUsageObserver(observer:NonNullable<PiInteractiveAdapter["usageObserver"]>):void {this.usageObserver=observer;}
  private transforming = false;
  private modelCalls = 0;
  private runtimeBlockers = new Set<string>();
  private toolTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private transportHealthy: () => boolean = () => false;
  private configHealthy: () => boolean = () => true;
  readonly runtime = inspectRuntimeProfile();

  constructor(pi: ExtensionAPI, config: Config, context: ExtensionContext) {
    this.pi = pi; this.config = config; this.context = context;
  }
  update(context: ExtensionContext): void { this.context = context; }
  private ownsKernelTool(): boolean {
    if (!this.config.features.managedWorkflows) return false;
    const tool = this.pi.getAllTools().find(tool => tool.name === "kernel_task");
    try { return !!tool && tool.sourceInfo.source !== "builtin"
      && realpathSync(tool.sourceInfo.path) === realpathSync(fileURLToPath(new URL("../../index.ts", import.meta.url))); }
    catch { return false; }
  }
  contextChanging(changing: boolean): void { this.transforming = changing; }
  setTransportHealth(check: () => boolean): void { this.transportHealthy = check; }
  setConfigHealth(check: () => boolean): void { this.configHealthy = check; }
  toolStarted(id: string, name: string): void {
    this.activeTools.add(id);
    this.toolNames.set(id, name);
    const info = this.pi.getAllTools().find((tool) => tool.name === name);
    if (!(name === "kernel_task" && this.ownsKernelTool()) && (!SAFE_TOOLS.has(name) || info?.sourceInfo.source !== "builtin")) this.uncertainTools.add(id);
    const profile = this.config.recovery.profileRef ? this.config.executionProfiles[this.config.recovery.profileRef] : null;
    if (this.automatic && profile) {
      const timer = setTimeout(() => {
        if (!this.activeTools.has(id)) return;
        this.runtimeBlockers.add("tool_timeout"); this.context.abort();
      }, profile.toolTimeoutMs);
      timer.unref(); this.toolTimers.set(id, timer);
    }
  }
  toolEnded(id: string, failed = false): void {
    // Native find rejects on abort before fd's close event. Its error is not a
    // physical termination acknowledgement; keep this execution unreconciled.
    if (failed && this.toolNames.get(id) === "find") this.uncertainTools.add(id);
    this.activeTools.delete(id);
    this.toolNames.delete(id);
    const timer = this.toolTimers.get(id); if (timer) clearTimeout(timer);
    this.toolTimers.delete(id);
  }
  beforeRequest(): void {
    if (!this.automatic) return;
    this.modelCalls++;
    const profile = this.config.recovery.profileRef ? this.config.executionProfiles[this.config.recovery.profileRef] : null;
    if (!profile || this.modelCalls > profile.maxModelTurns) {
      this.runtimeBlockers.add("model_turn_limit"); this.context.abort();
    }
  }
  settled(): void { this.automatic = false; }
  yieldControl(): void {
    this.automatic = false;
    for (const timer of this.toolTimers.values()) clearTimeout(timer);
    this.toolTimers.clear();
  }
  persistedMessage(): void {
    // message_end handlers run before SessionManager persistence; scan after the handler completes.
    setImmediate(() => { for (const notify of [...this.waiters]) notify(); });
  }
  snapshot(): InteractiveSnapshot {
    const ctx = this.context;
    const profile = this.config.recovery.profileRef ? this.config.executionProfiles[this.config.recovery.profileRef] : null;
    const reasons = [...inspectRuntimeProfile().reasons, ...this.runtimeBlockers];
    try { taskKeeperRuntimeIdentity(); } catch { reasons.push("task_keeper_source_changed_requires_reload"); }
    if (this.transforming) reasons.push("context_transformation_in_progress");
    if (!this.configHealthy()) reasons.push("configuration_changed_requires_reload");
    if (!this.transportHealthy()) reasons.push("http_observer_not_active");
    if (!["rpc", "tui"].includes(ctx.mode)) reasons.push("mode_not_in_contract_test_matrix");
    if (!ctx.sessionManager.getSessionFile()) reasons.push("durable_session_required");
    if (ctx.model?.api !== "openai-completions") reasons.push("provider_protocol_not_in_contract_test_matrix");
    if (!profile || profile.tools.some((tool) => !SAFE_TOOLS.has(tool) && !(tool === "kernel_task" && this.ownsKernelTool()))) reasons.push("tool_profile_not_certified");
    if (profile?.tools.includes("kernel_task") && profile.tools.some(tool => ["write", "edit"].includes(tool))) reasons.push("mixed_parent_mutation_profile_not_certified");
    if (profile?.thinking !== undefined && profile.thinking !== this.pi.getThinkingLevel()) reasons.push("thinking_profile_mismatch");
    const available = new Set(["settled", "continuationIdentity", "termination", "events"]);
    if (profile?.tools.every((tool) => ["read", "grep", "find", "ls"].includes(tool))) available.add("readonly");
    for (const required of profile?.requiredCapabilities ?? []) if (!available.has(required)) reasons.push(`capability_not_certified:${required}`);
    if (profile && this.pi.getActiveTools().some((tool) => !profile.tools.includes(tool))) reasons.push("active_tool_set_not_certified");
    const route = this.config.recovery.primaryRoute ? this.config.routes[this.config.recovery.primaryRoute] : null;
    if (route && this.config.network[route.network]?.type !== "direct") reasons.push("network_profile_not_certified");
    if (this.uncertainTools.size) reasons.push("external_tool_lifecycle_unknown");
    return { sessionId: ctx.sessionManager.getSessionId(), leafId: ctx.sessionManager.getLeafId() ?? "root",
      provider: ctx.model?.provider ?? "unknown", model: ctx.model?.id ?? "unknown", idle: ctx.isIdle(),
      pendingMessages: ctx.hasPendingMessages(), terminationKnown: this.activeTools.size === 0 && this.uncertainTools.size === 0,
      certified: reasons.length === 0, blockedReasons: reasons,
      transportIdentity: digest([ctx.model?.api ?? null, ctx.model?.baseUrl ?? null]),
      runtimeFingerprint: digest({ binding: ctx.model ? modelBindingDigest(ctx.model) : null, api: ctx.model?.api ?? null, baseUrl: ctx.model?.baseUrl ?? null,
        provider: ctx.model?.provider ?? null, model: ctx.model?.id ?? null, thinking: this.pi.getThinkingLevel(),
        contextWindow: ctx.model?.contextWindow ?? null, maxTokens: ctx.model?.maxTokens ?? null,
        tools: this.pi.getAllTools().filter((tool) => this.pi.getActiveTools().includes(tool.name))
          .map((tool) => ({ name: tool.name, source: tool.sourceInfo.source, path: tool.sourceInfo.path ?? null })).sort((a, b) => a.name.localeCompare(b.name)) }) };
  }
  async canary(signal: AbortSignal, guard: RequestGuard) {
    const model = this.context.model;
    if (!model || !this.snapshot().certified || signal.aborted) throw new ContractError("CANARY_NOT_SAFE");
    const observed: { response: { status: number; headers: Record<string, string> } | null; secrets: string[]; attempts: number } = { response: null, secrets: [], attempts: 0 };
    const nativeId = newId("canary");
    this.usageObserver?.begin({sessionId:this.context.sessionManager.getSessionId(),provider:model.provider,model:model.id,modelVersion:modelBindingDigest(model)});
    let usageSettled=false;
    const transport = installHttpTransport(() => ({ baseUrl: model.baseUrl, model: model.id, token: 1 }), {
      before: (attempt) => { guard(); if (!this.configHealthy()) throw new ContractError("CONFIGURATION_CHANGED"); observed.response = null; observed.secrets = attempt.secrets; observed.attempts++; this.usageObserver?.attempt(attempt.id); }, recheck: () => guard(), invokeWithin: (attempt, invoke) => guard(invoke, attempt.id),
      response: (_attempt, response) => { observed.response = response;this.usageObserver?.response(_attempt.id,response.status); },
      error:(attempt,invoked)=>{if(!invoked)this.usageObserver?.notSent(attempt.id);},
      meteringEnabled:()=>this.usageObserver?.active()??false,metering:(attempt,zero)=>this.usageObserver?.metering(attempt.id,zero),
    }, true, false);
    try {
      const result = await this.context.modelRegistry.complete(model, { messages: [{ role: "user", content: "Respond with OK. This is a connectivity probe, not a task execution.", timestamp: Date.now() }], tools: [] },
        { signal, maxTokens: 16, fetch: transport.fetch });
      if (observed.attempts === 0) throw new ContractError("CANARY_TRANSPORT_NOT_OBSERVED");
      this.usageObserver?.end(result.usage,result.stopReason === "stop"?"success":signal.aborted?"cancelled":"failure");usageSettled=true;
      return { nativeId, terminated: !signal.aborted,
        failure: result.stopReason === "stop" ? null : terminalError(result.errorMessage ?? result.stopReason, observed.response, observed.secrets) };
    } finally { if(!usageSettled)this.usageObserver?.end(undefined,signal.aborted?"cancelled":"unknown");transport.dispose(); observed.secrets = []; }
  }
  continuationIdentity(intent: { id: string; scopeId: string; epoch: number; leafId: string }): { nativeId: string } | null {
    const entries = this.context.sessionManager.getEntries().filter(entry => entry.type === "custom_message" && entry.customType === CONTROL_TYPE
      && (entry.details as {id?: string} | undefined)?.id === intent.id);
    if (!entries.length) return null;
    if (entries.length !== 1) throw new ContractError("DUPLICATE_NATIVE_CONTINUATION");
    const entry = entries[0];
    if (entry.type !== "custom_message") throw new ContractError("CONTINUATION_IDENTITY_MISMATCH");
    const details = entry.details as Partial<typeof intent>;
    if (details.scopeId !== intent.scopeId || details.epoch !== intent.epoch || details.leafId !== intent.leafId) throw new ContractError("CONTINUATION_IDENTITY_MISMATCH");
    identifier(entry.id, "native continuation");
    return {nativeId: entry.id};
  }
  async continue(intent: { id: string; scopeId: string; epoch: number; leafId: string }, signal: AbortSignal): Promise<{ nativeId: string }> {
    const snapshot = this.snapshot();
    if (signal.aborted || !snapshot.certified || !snapshot.idle || snapshot.pendingMessages || snapshot.leafId !== intent.leafId) {
      throw new ContractError("NATIVE_CONTINUATION_NOT_SAFE");
    }
    const result = new Promise<{ nativeId: string }>((resolveAck, reject) => {
      const cleanup = () => { this.waiters.delete(scan); signal.removeEventListener("abort", abort); };
      const abort = () => { cleanup(); reject(new ContractError("CONTINUATION_ACK_CANCELLED")); };
      const scan = () => {
        const entries = this.context.sessionManager.getEntries();
        const matches = entries.filter((entry) => entry.type === "custom_message" && entry.customType === CONTROL_TYPE
          && (entry.details as { id?: string } | undefined)?.id === intent.id);
        if (matches.length > 1) { cleanup(); reject(new ContractError("DUPLICATE_NATIVE_CONTINUATION")); return; }
        if (matches.length === 1) { cleanup(); resolveAck({ nativeId: matches[0].id }); }
      };
      this.waiters.add(scan); signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) { abort(); return; }
      this.automatic = true; this.modelCalls = 0;
      this.pi.sendMessage({ customType: CONTROL_TYPE, display: true, details: intent,
        content: "Continue the existing task from its current state after a temporary service limit. Preserve prior tool results and edits; do not replay completed actions. Keep unresolved failures and required verification visible." }, { triggerTurn: true });
      setImmediate(scan);
    });
    return result;
  }
  abort(): void { this.context.abort(); }
  dispose(): void {
    for (const timer of this.toolTimers.values()) clearTimeout(timer);
    this.toolTimers.clear(); this.automatic = false;
  }
}
