import { resolveRecoveryTarget, localRetryDelay } from "../policies/recovery.ts";
import { recoveryEligibility } from "./eligibility.ts";
import { ownerMatches } from "../contracts/ownership.ts";
import { networkFailureBudget } from "./network-budget.ts";
import { recoveryTiming } from "./timing.ts";
import { configurationPolicy, type Config } from "../config.ts";
import { ContractError, digest, newId, systemClock, type Clock } from "../contracts/primitives.ts";
import { Store, type Owner } from "../store/database.ts";
import { classify, isTemporaryQuota, successfulRecoveryTerminal, scrub, type FailureSignal, type Classification } from "./classifier.ts";
import { recordServerFloor, failureDomain, routeIncidents, routeNotBefore, recoveryResources, closeRouteIncidents, ensureExecutionTransportLease, admitTransportRequest, settleExecutionTransportLeases, type IncidentDomain } from "./incidents.ts";
import type { ProcessIdentity, ProcessMonitor } from "../adapters/process-identity.ts";

export interface InteractiveSnapshot {
  sessionId: string; leafId: string; provider: string; model: string;
  idle: boolean; pendingMessages: boolean; terminationKnown: boolean;
  certified: boolean; blockedReasons: string[];
  runtimeFingerprint?: string; transportIdentity?: string;
}
export type RequestGuard = (invoke?: () => void, requestId?: string) => void;
export interface InteractiveAdapter {
  snapshot(): InteractiveSnapshot;
  continue(intent: { id: string; scopeId: string; epoch: number; leafId: string }, signal: AbortSignal): Promise<{ nativeId: string }>;
  continuationIdentity?(intent: { id: string; scopeId: string; epoch: number; leafId: string }): { nativeId: string } | null;
  abort(): void;
  yieldControl?(): void;
  canary?(signal: AbortSignal, guard: RequestGuard): Promise<{ nativeId: string; failure: FailureSignal | null; terminated: boolean }>;
}
export interface RecoveryRecord {
  scopeId: string; sessionId: string; leafId: string; routeId: string; quotaGroup: string;
  policyDigest: string; ownerEpoch: number;
  status: "IDLE" | "WAITING_QUOTA" | "RUNNING" | "PAUSED" | "BLOCKED" | "DONE";
  notBefore: number; incidentId: string | null; intentId: string | null; incidentDomain?: IncidentDomain;
  attempts: number; networkAttempts: number; localFailures?: number; localRetryAt?: number; serverFloor?: number; reason: string;
  canaryReady?: boolean; canaryAttempts?: number; deadlineAt?: number | null;
  history: Array<Classification & { at: number; leafId: string }>;
  lastDispatchError?: { code: string | null; sqliteCode: number | null; message: string };
}

/** Owns one interactive scope. Child/workflow schedulers use the same Store admission primitives. */
export class RecoveryController {
  readonly scopeId: string;
  private owner: Owner;
  private record: RecoveryRecord;
  private cancelTimer: (() => void) | null = null;
  private cancelTimeout: (() => void) | null = null;
  private abortController: AbortController | null = null;
  private ticking = false;
  private disposed = false;
  private lastWall: number;
  private lastMono: number;
  private store: Store;
  private config: Config;
  private adapter: InteractiveAdapter;
  private clock: Clock;
  private random: () => number;
  private onChange: (record: RecoveryRecord) => void;
  private processMonitor?: ProcessMonitor;

  constructor(store: Store, config: Config, adapter: InteractiveAdapter,
    clock: Clock = systemClock, random: () => number = Math.random,
    onChange: (record: RecoveryRecord) => void = () => {}, processMonitor?: ProcessMonitor) {
    this.store = store; this.config = config; this.adapter = adapter;
    this.clock = clock; this.random = random; this.onChange = onChange;
    this.processMonitor = processMonitor;
    const snapshot = adapter.snapshot(), initialTarget=resolveRecoveryTarget(config, snapshot);
    this.scopeId = `interactive-${digest(snapshot.sessionId)}`;
    let previous = store.get<RecoveryRecord>("recovery", this.scopeId);
    const oldOwner = store.owner(this.scopeId);
    const oldProcess = store.get<{ token: string; epoch: number; identity: ProcessIdentity }>("owner-process", this.scopeId);
    if(oldOwner && !previous)throw new ContractError("RECOVERY_STATE_MISSING");
    let safeRestart = false;
    const stoppedOwner=!!oldOwner?.active&&!!oldProcess&&oldProcess.token===oldOwner.token&&oldProcess.epoch===oldOwner.epoch&&processMonitor?.stopped(oldProcess.identity)===true;
    if(stoppedOwner){
      store.revokeOwner(oldOwner!);
      if(previous?.intentId){
        const terminal=store.get<{completed:boolean;terminated:boolean;record:RecoveryRecord}>("recovery-terminal-facts",previous.intentId);
        if(terminal?.completed&&terminal.terminated&&terminal.record.leafId===snapshot.leafId&&terminal.record.policyDigest===digest([configurationPolicy(config),snapshot.runtimeFingerprint??null])&&snapshot.certified&&snapshot.terminationKnown&&!snapshot.pendingMessages){
          store.settle(previous.intentId,"terminated");settleExecutionTransportLeases(store,previous.intentId);previous=terminal.record;
          closeRouteIncidents(store,resolveRecoveryTarget(config,snapshot).route,undefined,clock.now());
        }
      }
      safeRestart=previous?.status==="WAITING_QUOTA"&&!previous.intentId&&previous.leafId===snapshot.leafId&&previous.policyDigest===digest([configurationPolicy(config),snapshot.runtimeFingerprint??null])&&snapshot.certified&&snapshot.terminationKnown&&!snapshot.pendingMessages;
    }
    this.owner = store.claimOwner(this.scopeId, newId("owner"));
    this.recordOwnerProcess();
    this.record = previous ?? {
      scopeId: this.scopeId, sessionId: snapshot.sessionId, leafId: snapshot.leafId,
      routeId: initialTarget.routeId, quotaGroup: "unbound", policyDigest: digest([configurationPolicy(config), snapshot.runtimeFingerprint ?? null]),
      ownerEpoch: this.owner.epoch, status: "IDLE", notBefore: 0, incidentId: null, intentId: null,
      attempts: 0, networkAttempts: 0, reason: "idle", history: [],
    };
    this.record.ownerEpoch = this.owner.epoch;
    this.lastWall = clock.now(); this.lastMono = clock.monotonic();
    if (previous) {
      // Reattaching never clears an unknown intent or silently grants automation.
      this.record.status = previous.status === "DONE" ? "DONE" : safeRestart ? "WAITING_QUOTA" : "PAUSED";
      this.record.reason = previous.status === "DONE" ? previous.reason : safeRestart ? "restored_wait_reconciled" : previous.intentId ? "resume_requires_intent_reconciliation" : "restored_wait_requires_resume";
    }
    this.save();
    if (safeRestart) this.arm();
  }
  target() { return resolveRecoveryTarget(this.config, this.adapter.snapshot()); }
  state(): RecoveryRecord { return structuredClone(this.record); }
  /** Captured before credential resolution; checked synchronously at the actual HTTP boundary. */
  requestGuard(intentId: string, epoch: number, allowContextTransformation = false): RequestGuard {
    const before = this.adapter.snapshot();
    const identity = (snapshot: InteractiveSnapshot) => digest([snapshot.sessionId, snapshot.leafId, snapshot.provider, snapshot.model, snapshot.runtimeFingerprint ?? null]);
    const check = () => {
      const snapshot = this.adapter.snapshot();
      const allowedTransformation = allowContextTransformation && snapshot.blockedReasons.length === 1
        && snapshot.blockedReasons[0] === "context_transformation_in_progress";
      if (!this.current() || this.record.status !== "RUNNING" || this.record.intentId !== intentId || this.owner.epoch !== epoch
        || identity(snapshot) !== identity(before) || (!snapshot.certified && !allowedTransformation) || !snapshot.terminationKnown || snapshot.pendingMessages
        || (snapshot.blockedReasons.length > 0 && !allowedTransformation)
        || (this.record.deadlineAt != null && this.clock.now() >= this.record.deadlineAt)
        || this.record.policyDigest !== digest([configurationPolicy(this.config), snapshot.runtimeFingerprint ?? null])) throw new ContractError("AUTOMATIC_REQUEST_CONTROL_REVOKED");
      const route = this.target().route;
      if (routeNotBefore(this.store, route) > this.clock.now()) throw new ContractError("SHARED_ROUTE_NOT_BEFORE");
      return route;
    };
    return (invoke, requestId) => {
      const route = check();
      if (invoke) {
        if (!requestId) throw new ContractError("REQUEST_ID_REQUIRED");
        admitTransportRequest(this.store, this.owner, intentId, this.scopeId, intentId, route, requestId, check);
        invoke();
      } else ensureExecutionTransportLease(this.store, this.owner, intentId, this.scopeId, intentId, route);
    };
  }
  authorizeControlledTool(intentId: string, epoch: number): void {
    const snapshot = this.adapter.snapshot(), route = this.target().route;
    if (!this.current() || this.record.status !== "RUNNING" || this.record.intentId !== intentId || this.owner.epoch !== epoch
      || snapshot.sessionId !== this.record.sessionId || !route || snapshot.provider !== route.provider || snapshot.model !== route.model
      || !snapshot.certified || snapshot.blockedReasons.length || snapshot.pendingMessages
      || this.record.policyDigest !== digest([configurationPolicy(this.config), snapshot.runtimeFingerprint ?? null])
      || (this.record.deadlineAt != null && this.clock.now() >= this.record.deadlineAt)) throw new ContractError("AUTOMATIC_TOOL_CONTROL_REVOKED");
  }
  private recordOwnerProcess(): void {
    const identity = this.processMonitor?.current();
    if (identity) this.store.put("owner-process", this.scopeId, { token: this.owner.token, epoch: this.owner.epoch, identity });
  }
  private save(): void {
    const currentOwner = this.store.transaction(() => {
      const owner = this.store.owner(this.scopeId);
      const ownRevocation = owner && !owner.active && owner.token === this.owner.token && owner.epoch === this.owner.epoch + 1;
      if (owner && !ownRevocation && (owner.epoch !== this.owner.epoch || owner.token !== this.owner.token)) {
        this.store.put("late-recovery-records", digest([this.scopeId, this.owner.epoch, this.record]), {
          scopeId: this.scopeId, ownerEpoch: this.owner.epoch, record: this.state(),
        });
        return false;
      }
      this.store.put("recovery", this.scopeId, this.record); return true;
    });
    if (!currentOwner) return;
    // UI failures are not execution facts and must not interrupt durable state updates.
    try { this.onChange(this.state()); } catch { /* State remains inspectable. */ }
  }
  private current(): boolean {
    if (this.disposed) return false;
    const owner = this.store.owner(this.scopeId);
    return ownerMatches(this.owner, owner);
  }
  private eligible(snapshot = this.adapter.snapshot()): string | null {
    return recoveryEligibility(this.config, this.record, snapshot);
  }

  /** Call only at the host's certified settled boundary, with the final stream outcome. */
  settled(signal: FailureSignal | null): void {
    if (this.disposed) return;
    const snapshot = this.adapter.snapshot();
    if (!snapshot.idle) return;
    if (snapshot.sessionId !== this.record.sessionId) {
      if (this.record.intentId) this.store.settle(this.record.intentId, "unknown");
      this.block("session_identity_changed_requires_reconciliation"); return;
    }
    // Host settlement is not a termination receipt for the separate canary request.
    if (this.record.intentId && this.store.intent(this.record.intentId)?.kind === "canary") return;
    if (signal && ["WAITING_QUOTA", "BLOCKED"].includes(this.record.status)
      && this.record.history.at(-1)?.leafId === snapshot.leafId) return;
    const isFailure = !!signal && signal.controlRevoked !== true && !successfulRecoveryTerminal(signal);
    const boundRoute = this.target().route;
    const observedFailure = isFailure ? classify(signal!, this.target().policy.rules, this.clock.now()) : null;
    if (isFailure) {
      this.record.canaryReady = false;
      if (this.record.deadlineAt == null && this.target().maxWaitMs != null) this.record.deadlineAt = this.clock.now() + this.target().maxWaitMs!;
    }
    if (observedFailure && this.record.history.at(-1)?.leafId !== snapshot.leafId) {
      this.record.history.push({ ...observedFailure, at: this.clock.now(), leafId: snapshot.leafId });
    }
    this.cancelTimeout?.(); this.cancelTimeout = null;
    if (this.record.intentId) {
      const intent = this.store.intent(this.record.intentId);
      if (snapshot.terminationKnown && intent && !intent.nativeId && this.adapter.continuationIdentity) {
        let identity: {nativeId: string} | null = null;
        try {
          if (typeof intent.payload.leafId === "string") identity = this.adapter.continuationIdentity({ id: intent.id, scopeId: intent.scopeId, epoch: intent.epoch, leafId: intent.payload.leafId });
        } catch { /* An unavailable or conflicting native identity cannot be guessed. */ }
        if (!identity) {
          this.store.settle(intent.id, "unknown"); this.block("continuation_identity_unavailable"); this.abortController?.abort(); return;
        }
        this.store.acknowledge(intent.id, identity.nativeId);
      }
      const completed=successfulRecoveryTerminal(signal)&&this.current()&&this.record.status!=="PAUSED"&&!snapshot.pendingMessages&&recoveryEligibility(this.config,{...this.record,leafId:snapshot.leafId},snapshot)===null;
      const terminalRecord:RecoveryRecord={...this.record,intentId:null,leafId:snapshot.leafId,status:"DONE",reason:"stream_completed"};
      if(snapshot.terminationKnown)this.store.put("recovery-terminal-facts",this.record.intentId,{completed,terminated:true,record:terminalRecord});
      this.store.settle(this.record.intentId, snapshot.terminationKnown ? "terminated" : "unknown",()=>{
        if(completed&&ownerMatches(this.owner,this.store.owner(this.scopeId)))this.store.put("recovery",this.scopeId,terminalRecord);
      });
      if (!snapshot.terminationKnown) { this.block("termination_unknown"); return; }
      settleExecutionTransportLeases(this.store, this.record.intentId);
      this.record.intentId = null;
      // The native execution is proven stopped. End a lost ACK listener too,
      // so its awaiting tick cannot hold later incidents indefinitely.
      this.abortController?.abort();
      if (snapshot.sessionId === this.record.sessionId) this.record.leafId = snapshot.leafId;
    }
    // Late completion may settle evidence, never restore revoked automatic control.
    if (!this.current() || ["PAUSED"].includes(this.record.status)) { this.save(); return; }
    if (signal?.controlRevoked) { this.block("automatic_control_revoked"); return; }
    this.record.leafId = snapshot.leafId;
    if (snapshot.pendingMessages) { this.pause("pending_messages"); return; }
    const denied = this.eligible(snapshot);
    if (denied) { this.block(denied); return; }
    if (successfulRecoveryTerminal(signal)) {
      this.record.status = "DONE"; this.record.reason = "stream_completed";
      this.cancelTimer?.(); this.cancelTimer = null;
      if (boundRoute) closeRouteIncidents(this.store, boundRoute, undefined, this.clock.now());
      this.save(); return;
    }
    const route = this.target().route;
    const failure = observedFailure!;
    if (signal!.responseObserved === false && signal!.status !== undefined) { this.block("http_response_observation_missing"); return; }
    if (failure.category === "window_quota" && failure.retryAt === null && this.target().policy.unknownReset === "pause") { this.block("quota_reset_unknown"); return; }
    if (!isTemporaryQuota(failure.category) && failure.category !== "network_overload") { this.block(failure.category); return; }
    if (failure.category === "network_overload" && signal!.admission !== "transport-wait") {
      const budget = networkFailureBudget(this.record.networkAttempts, this.target().policy.maxNetworkAttempts);
      this.record.networkAttempts = budget.attempts;
      if (budget.exhausted) { this.block("network_attempts_exhausted"); return; }
    }
    this.record.quotaGroup = route.quotaGroup;
    const domain = failureDomain(route, failure);
    const delay = localRetryDelay(this.target(), this.record.localFailures ?? 0, this.random());
    if (delay === null) { this.block("local_retry_sequence_exhausted"); return; }
    recordServerFloor(this.store, this.owner, route, failure, incident => {
      this.record.localFailures = (this.record.localFailures ?? 0) + 1;
      this.record.localRetryAt = this.clock.now() + delay; this.record.serverFloor = incident.notBefore;
      this.record.incidentId = incident.id; this.record.incidentDomain = domain;
      this.record.notBefore = Math.max(this.record.localRetryAt ?? 0, incident.notBefore, routeNotBefore(this.store, route));
      this.record.status = "WAITING_QUOTA"; this.record.reason = failure.category;
      this.store.put("recovery", this.scopeId, this.record);
    });
    this.save(); this.arm();
  }

  private arm(): void {
    this.cancelTimer?.(); this.cancelTimer = null;
    if (!this.current() || this.record.status !== "WAITING_QUOTA") return;
    const delay = Math.min(2_147_483_647, Math.max(1, Math.ceil(Math.min(this.record.notBefore, this.record.deadlineAt ?? Number.MAX_SAFE_INTEGER) - this.clock.now())));
    this.cancelTimer = this.clock.schedule(delay, () => {
      this.cancelTimer = null;
      void this.tick().catch(error => this.dispatchFailed(error));
    });
  }
  private dispatchFailed(error: unknown): void {
    if (this.disposed) return;
    const native = error as {code?:unknown;errcode?:unknown};
    const busy = (value: unknown) => {
      const item=value as {code?:unknown;errcode?:unknown};
      return item?.code === "ERR_SQLITE_ERROR" && Number.isInteger(item.errcode) && [5,6].includes(Number(item.errcode) & 0xff);
    };
    this.record.lastDispatchError = {code:typeof native?.code === "string" ? native.code : null,
      sqliteCode:Number.isInteger(native?.errcode) ? Number(native.errcode) : null,message:scrub(error instanceof Error ? error.message : String(error))};
    const expired=this.record.deadlineAt!=null && this.clock.now()>=this.record.deadlineAt;
    if(!expired && busy(error) && this.record.status === "WAITING_QUOTA" && this.record.intentId === null && !this.store.db.isTransaction){
      // No committed execution or external effect exists. Yield the contended
      // store instead of reacquiring its write lock merely to record the wait.
      const delay=Math.min(2147483647,Math.max(1,this.target().intervals[0]));
      this.record.notBefore=Math.max(this.record.notBefore,this.clock.now()+delay);this.record.reason="state_store_contended";
      this.cancelTimer?.();this.cancelTimer=this.clock.schedule(delay,()=>{this.cancelTimer=null;void this.tick().catch(next=>this.dispatchFailed(next));});
      try{this.onChange(this.state());}catch{/* Presentation cannot grant execution authority. */}
      return;
    }
    try{this.block(expired?"recovery_deadline_exhausted":"recovery_dispatch_failed");}
    catch(persistenceError){
      if(!busy(persistenceError))throw persistenceError;
      // The in-memory state is already BLOCKED and timers are cancelled. Do not
      // retry a committed/unknown execution to repair an unavailable status write.
      try{this.onChange(this.state());}catch{/* The durable intent remains the reconciliation authority. */}
    }
  }
  async tick(): Promise<void> {
    if (this.ticking || !this.current() || this.record.status !== "WAITING_QUOTA") return;
    const wall = this.clock.now(), mono = this.clock.monotonic(), route = this.target().route;
    const timing = recoveryTiming({ now: wall, monotonic: mono, previousWall: this.lastWall, previousMonotonic: this.lastMono,
      notBefore: this.record.notBefore, sharedNotBefore: route ? routeNotBefore(this.store, route) : 0, deadlineAt: this.record.deadlineAt });
    if (timing.action === "deadline") { this.block("recovery_deadline_exhausted"); return; }
    this.record.notBefore = timing.notBefore; this.lastWall = wall; this.lastMono = mono;
    if (timing.action === "wait") { this.save(); this.arm(); return; }
    const denied = this.eligible();
    if (denied) { this.block(denied); return; }
    const id = newId("continuation"), dispatchOwner = { ...this.owner };
    const canary = this.config.recovery.lightCanaryEnabled && !this.record.canaryReady;
    const prepared:RecoveryRecord={...this.record,intentId:id,status:"RUNNING",reason:canary?"light_canary":"recovery_request",attempts:this.record.attempts+(canary?0:1),...(canary?{canaryAttempts:(this.record.canaryAttempts??0)+1}:{})};
    try {
      this.store.transaction(()=>{this.store.prepare(this.owner, id, canary ? "canary" : "continue", { sessionId: this.record.sessionId, leafId: this.record.leafId, incidentId: this.record.incidentId },
        recoveryResources(this.store, route), () => {
          if (routeNotBefore(this.store, route) > this.clock.now()) throw new ContractError("NOT_BEFORE");
          const deniedNow = this.eligible();
          if (deniedNow) throw new ContractError("ADMISSION_CHANGED", deniedNow);
        });this.store.put("recovery",this.scopeId,prepared);});
    } catch (error) {
      if (error instanceof ContractError && ["RESOURCE_DENIED", "NOT_BEFORE"].includes(error.code)) {
        this.record.notBefore = Math.max(this.record.notBefore, wall + this.target().intervals[0]);
        this.save(); this.arm(); return;
      }
      throw error;
    }
    this.ticking = true;
    this.record=prepared;
    this.save();
    this.abortController = new AbortController();
    const signal = this.abortController.signal;
    const profileTimeout = this.config.recovery.profileRef ? this.config.executionProfiles[this.config.recovery.profileRef]?.timeoutMs : undefined;
    this.cancelTimeout = this.clock.schedule(Math.min(this.target().requestTimeoutMs, profileTimeout ?? this.target().requestTimeoutMs), () => {
      if (this.record.intentId !== id || this.disposed) return;
      // Revoke before abort callbacks can deliver late terminal facts. A timeout
      // ends automatic authority even when termination is subsequently proven.
      this.store.settle(id, "unknown");
      if (this.current()) this.store.revokeOwner(this.owner);
      this.block("request_timeout_termination_unknown");
      this.abortController?.abort(); if (!canary) this.adapter.abort();
    });
    try {
      this.store.markSent(this.owner, id);
      if (canary) {
        if (!this.adapter.canary) throw new ContractError("CANARY_ADAPTER_UNAVAILABLE");
        const result = await this.adapter.canary(signal, (invoke, requestId) => {
          const check = () => {
            const snapshot = this.adapter.snapshot();
            const sharedNotBefore = routeNotBefore(this.store, this.target().route);
            if (!this.current() || this.owner.epoch !== dispatchOwner.epoch || this.owner.token !== dispatchOwner.token
              || this.record.intentId !== id || this.record.status !== "RUNNING" || this.eligible(snapshot)
              || this.clock.now() < Math.max(this.record.notBefore, sharedNotBefore)
              || (this.record.deadlineAt != null && this.clock.now() >= this.record.deadlineAt)) throw new ContractError("CANARY_CONTROL_REVOKED");
          };
          check();
          const route = this.target().route;
          if (invoke) {
            if (!requestId) throw new ContractError("REQUEST_ID_REQUIRED");
            admitTransportRequest(this.store, this.owner, id, this.scopeId, id, route, requestId, check);
            invoke();
          } else ensureExecutionTransportLease(this.store, this.owner, id, this.scopeId, id, route);
        });
        if (this.disposed) return;
        this.store.acknowledge(id, result.nativeId);
        this.store.settle(id, result.terminated ? "terminated" : "unknown");
        if (result.terminated) settleExecutionTransportLeases(this.store, id);
        if (this.record.intentId !== id) return;
        this.cancelTimeout?.(); this.cancelTimeout = null;
        if (!result.terminated) { this.block("canary_termination_unknown"); return; }
        this.record.intentId = null;
        if (!this.current() || ["PAUSED"].includes(this.record.status)) { this.save(); return; }
        const deniedAfter = this.eligible();
        if (deniedAfter) { this.block(deniedAfter); return; }
        if (result.failure) {
          const failure = classify(result.failure, this.target().policy.rules, this.clock.now());
          this.record.history.push({ ...failure, at: this.clock.now(), leafId: `canary:${id}` });
          if (!isTemporaryQuota(failure.category) && failure.category !== "network_overload") { this.block(failure.category); return; }
          if (failure.category === "window_quota" && failure.retryAt === null && this.target().policy.unknownReset === "pause") { this.block("quota_reset_unknown"); return; }
          if (failure.category === "network_overload") {
            const budget = networkFailureBudget(this.record.networkAttempts, this.target().policy.maxNetworkAttempts);
            this.record.networkAttempts = budget.attempts;
            if (budget.exhausted) { this.block("network_attempts_exhausted"); return; }
          }
          const domain = failureDomain(this.target().route, failure);
          const delay = localRetryDelay(this.target(), this.record.localFailures ?? 0, this.random());
          if (delay === null) { this.block("local_retry_sequence_exhausted"); return; }
          const incident = recordServerFloor(this.store, this.owner, this.target().route, failure);
          this.record.localFailures = (this.record.localFailures ?? 0) + 1;
          this.record.localRetryAt = this.clock.now() + delay; this.record.serverFloor = incident.notBefore;
          this.record.incidentId = incident.id; this.record.incidentDomain = domain;
          this.record.notBefore = Math.max(this.record.localRetryAt ?? 0, incident.notBefore, routeNotBefore(this.store, this.target().route));
          this.record.reason = "canary_failed";
        } else {
          this.record.canaryReady = true; this.record.reason = "canary_passed_real_request_pending";
        }
        this.record.status = "WAITING_QUOTA"; this.save(); this.arm(); return;
      }
      const ack = await this.adapter.continue({ id, scopeId: this.scopeId, epoch: this.owner.epoch, leafId: this.record.leafId }, signal);
      if (this.disposed) return; // The native durable entry is reconciled by the next session owner.
      // An acknowledgement is a fact even after cancellation, not new dispatch authority.
      this.store.acknowledge(id, ack.nativeId);
    } catch {
      if (this.disposed) return;
      if (this.store.intent(id)?.status !== "settled") this.store.settle(id, "unknown");
      if (this.current() && this.record.status === "RUNNING" && this.record.intentId === id) this.block("continuation_ack_unknown");
    } finally { this.ticking = false; }
  }

  private block(reason: string): void {
    this.record.status = "BLOCKED"; this.record.reason = reason;
    this.cancelTimer?.(); this.cancelTimer = null; this.save();
  }
  pause(reason = "user_pause"): void {
    this.cancelTimeout?.(); this.cancelTimeout = null;
    if (this.record.reason === "light_canary") this.abortController?.abort();
    this.adapter.yieldControl?.();
    if (this.current()) this.store.revokeOwner(this.owner);
    this.cancelTimer?.(); this.cancelTimer = null;
    if (this.record.status !== "DONE") { this.record.status = "PAUSED"; this.record.reason = reason; } this.save();
  }
  resume(): void {
    if (this.disposed || this.record.status === "DONE") throw new ContractError("TERMINAL_OR_DISPOSED");
    if (this.record.intentId) throw new ContractError("INTENT_RECONCILIATION_REQUIRED");
    const last = this.record.history.at(-1);
    if (!this.record.incidentId || !last || (!isTemporaryQuota(last.category)
      && !(last.category === "network_overload" && this.record.networkAttempts <= this.target().policy.maxNetworkAttempts))) {
      throw new ContractError("NO_RECOVERABLE_INCIDENT");
    }
    const denied = this.eligible();
    if (denied) throw new ContractError("RESUME_BLOCKED", denied);
    if (this.current()) this.store.revokeOwner(this.owner);
    this.owner = this.store.claimOwner(this.scopeId, newId("owner")); this.record.ownerEpoch = this.owner.epoch;
    this.recordOwnerProcess();
    this.record.status = "WAITING_QUOTA"; this.record.reason = "explicit_resume"; this.save(); this.arm();
  }
  stop(): void {
    this.pause("user_stop"); this.abortController?.abort(); this.adapter.abort();
  }
  beginUserTurn(): void {
    if (this.disposed) return;
    if (this.record.intentId) { this.pause("prior_execution_unsettled"); return; }
    const snapshot = this.adapter.snapshot(), policyDigest = digest([configurationPolicy(this.config), snapshot.runtimeFingerprint ?? null]);
    const changed = policyDigest !== this.record.policyDigest;
    if (changed || this.record.status === "DONE") { this.record.networkAttempts = 0; this.record.localFailures = 0; this.record.localRetryAt = 0; }
    if (changed) this.store.put("policy-authorizations", newId("user-turn"), { scopeId: this.scopeId, source: "user-input",
      previous: this.record.policyDigest, next: policyDigest, at: this.clock.now() });
    this.record.policyDigest = policyDigest;
    this.record.routeId = this.target().routeId;
    const poolId = this.target().route?.quotaGroup ?? "unbound";
    const route = this.target().route;
    const incident = route ? routeIncidents(this.store, route)[0] : null;
    if (poolId !== this.record.quotaGroup) this.record.notBefore = incident?.notBefore ?? 0;
    this.record.quotaGroup = poolId;
    if (incident) { this.record.incidentId = incident.id; this.record.incidentDomain = incident.domain; }
    if (this.current()) this.store.revokeOwner(this.owner);
    this.owner = this.store.claimOwner(this.scopeId, newId("owner"));
    this.recordOwnerProcess();
    this.record.ownerEpoch = this.owner.epoch;
    this.record.status = "IDLE"; this.record.reason = "new_user_turn"; this.record.deadlineAt = null; this.record.canaryReady = false;
    this.record.leafId = snapshot.leafId;
    this.save();
  }
  dispose(): void {
    if (this.disposed) return;
    this.pause("session_detached");
    this.cancelTimeout?.(); this.cancelTimeout = null;
    this.disposed = true;
    this.abortController?.abort(); // Stop the acknowledgement listener, not the host's user-owned tool.
  }
}
