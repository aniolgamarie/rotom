// Task Keeper 新协议客户端；不加载旧 pi-subagents 包、不发现全局配置。
import { randomUUID } from "node:crypto";
import { ManagedClient } from "@agentcfg/pi-runtime/managed-rpc";
import { assertOwner, canonical, clone, closed, digest, reject, sha, text } from "@agentcfg/pi-runtime/managed-types";
import { assertExecutionEvidence } from "../contracts/evidence.ts";
import { ManagedExecution, type ManagedStepInput } from "../orchestration/managed-execution.ts";
import type { Config } from "../config.ts";
import { AttemptJournal } from "../contracts/agentcfg.ts";
import type { Store, Owner } from "../store/database.ts";
import type { ChildObservation } from "./child-contract.ts";

export interface DelegationResult {
  descriptorId: string; nativeRunId: string | null; status: "ended" | "failed" | "unknown";
  nativeStatus?: string | null; nativeExitCode?: number | null;
  modelIdentity?: { requested: { provider: string; model: string }; runtimeObservationSource: "client_configuration";
    responseModel: null; serverWeights: "unverified" };
  terminationConfirmed: boolean; content: unknown; error: string | null; observations: ChildObservation[];
  parentHelperDenials?: string[]; notSent?: boolean;
}

const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1");
const required = ["managed-process", "fresh-context", "guarded-tools", "request-metering", "durable-results", "physical-termination", "workspace-leases"];

export function activeManagedParentGuard(_method: string): typeof fetch | null {
  const scope = (globalThis as any)[runtimeKey]?.managedRequestScope?.getStore();
  if (!scope) return null;
  return async () => {
    scope.recordDenial?.("UNBUDGETED_PARENT_HELPER_DENIED");
    reject("UNBUDGETED_PARENT_HELPER_DENIED", 5);
  };
}

export class SubagentsAdapter {
  private store: Store;
  private owner: Owner;
  private client: ManagedClient;
  private runtime: any;
  private config: Config;
  readonly journal: AttemptJournal;
  constructor(pi: any, store: Store, config: Config, owner: Owner,
    runtime = (globalThis as any)[runtimeKey], options: { timeout?: number } = {}) {
    this.store = store; this.owner = owner; this.runtime = runtime; this.config = config;
    this.client = new ManagedClient(pi.events, options);
    this.journal = new AttemptJournal(store, owner);
  }
  execute(input: ManagedStepInput, _ctx: unknown, signal?: AbortSignal, onDispatch?: () => void): Promise<DelegationResult> {
    return new ManagedExecution(this, this.store, this.owner, this.config, this.runtime).execute(input, signal, onDispatch);
  }
  async preflightReview(input: { role: string; cwd: string; model: string; thinking: string }) {
    await this.handshake();
    const role = this.runtime.roleManifest.roles.find((value: any) => value.id === input.role && value.managed);
    if (!role || role.model.provider + "/" + role.model.model !== input.model) reject("UNBOUND_MODEL", 2);
    return { role_id: role.id, model: role.model, thinking: input.thinking };
  }
  withManagedScope<T>(taskId: string, operation: () => Promise<T>): Promise<T> {
    const task = this.store.get<any>("agentcfg-tasks-v1", taskId);
    if (!task || !this.runtime?.managedRequestScope) reject("CAPABILITY_MISSING", 5);
    return this.runtime.managedRequestScope.run({ task_id: taskId, budget_scope_id: task.budget_scope_id,
      recordDenial: (code: string) => {
        this.store.assertOwner(this.owner);
        this.store.put("parent-helper-denials", "denial-" + randomUUID(), { jobId: taskId, scopeId: this.owner.scopeId, reason: code, at: Date.now() });
      } }, operation);
  }
  async handshake() {
    this.store.assertOwner(this.owner);
    if (!this.runtime || this.runtime.owner?.role !== "manager") reject("CAPABILITY_MISSING", 5);
    const reply: any = await this.client.call("handshake", { protocol_version: 1, instance_id: this.runtime.owner.instance_id, request_id: randomUUID() });
    closed(reply, ["instance_id", "manager_activation_id", "owner_nonce", "runtime_identity", "capabilities"]);
    const owner = { instance_id: reply.instance_id, manager_activation_id: reply.manager_activation_id, owner_nonce: reply.owner_nonce };
    assertOwner(owner);
    if (owner.instance_id !== this.runtime.owner.instance_id || owner.manager_activation_id !== this.runtime.owner.manager_activation_id
        || owner.owner_nonce !== this.runtime.owner.owner_nonce || reply.runtime_identity !== this.runtime.installed.runtime_identity) reject("MANAGER_IDENTITY_CONFLICT", 4);
    if (!Array.isArray(reply.capabilities) || required.some(name => !reply.capabilities.includes(name))) reject("CAPABILITY_MISSING", 5);
    this.store.assertOwner(this.owner);
    return { owner, runtime_identity: reply.runtime_identity };
  }
  async preflight(attemptId: string) {
    const { descriptor } = this.journal.read(attemptId);
    const handshake = await this.handshake();
    if (canonical(handshake.owner) !== canonical({ instance_id: descriptor.instance_id, manager_activation_id: descriptor.manager_activation_id,
      owner_nonce: descriptor.owner_nonce }) || descriptor.runtime_digest !== handshake.runtime_identity) reject("MANAGER_IDENTITY_CONFLICT", 4);
    const admission: any = await this.client.call("preflight", { descriptor });
    closed(admission, ["admission_token", "descriptor_digest", "resolved_digest"]);
    if (!sha(admission.admission_token) || admission.descriptor_digest !== digest(descriptor) || !sha(admission.resolved_digest)) reject("ADMISSION_STALE", 4);
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      this.store.put("agentcfg-admissions-v1", attemptId, admission);
    });
    return clone(admission);
  }
  async dispatch(attemptId: string) {
    await this.handshake();
    let request: any, send = false;
    this.store.transaction(() => {
      const { attempt, descriptor } = this.journal.read(attemptId);
      const admission = this.store.get<any>("agentcfg-admissions-v1", attemptId);
      if (!admission || admission.descriptor_digest !== attempt.descriptor_digest) reject("ADMISSION_STALE", 4);
      request = { descriptor, admission_token: admission.admission_token, idempotency_key: attempt.idempotency_key };
      if (attempt.state === "prepared") {
        this.store.put("agentcfg-attempts-v1", attemptId, { ...attempt, state: "starting" });
        send = true;
      }
    });
    if (!send) return this.journal.read(attemptId).attempt;
    try {
      const response = await this.client.call("dispatch", request);
      this.journal.acknowledge(attemptId, response);
    } catch (error) {
      this.store.transaction(() => {
        const { attempt } = this.journal.read(attemptId);
        this.store.put("agentcfg-attempts-v1", attemptId, { ...attempt, state: "start_unknown" });
      });
      // 不能凭传输错误认定没有派发；后续调用只返回持久状态。
      if ((error as any)?.exitCode !== 4) throw error;
    }
    return this.journal.read(attemptId).attempt;
  }
  async inspect(attemptId: string) {
    const { owner } = await this.handshake();
    const { attempt } = this.journal.read(attemptId);
    if (!attempt.manager_run_id) {
      // dispatch 确认丢失时只查结果，不重发；完整收据可补回同一 attempt 的关联。
      try { await this.get_result(attemptId); return clone(this.journal.read(attemptId).attempt); }
      catch (error) { if ((error as any)?.code !== "EVIDENCE_MISSING") throw error; }
      return clone(attempt);
    }
    return this.client.call("inspect", { owner, manager_run_id: attempt.manager_run_id });
  }
  async cancel(attemptId: string, reason: string) {
    if (!text(reason)) reject();
    const { owner } = await this.handshake();
    this.journal.read(attemptId);
    return this.client.call("cancel", { owner, attempt_id: attemptId, reason });
  }
  async get_result(attemptId: string) {
    const { owner } = await this.handshake();
    const { attempt, descriptor } = this.journal.read(attemptId);
    const result: any = await this.client.call("get_result", { owner, attempt_id: attemptId });
    closed(result, ["receipt", "receipt_digest"]);
    if (digest(result.receipt) !== result.receipt_digest || result.receipt.attempt_id !== attemptId
        || attempt.manager_run_id !== null && result.receipt.manager_run_id !== attempt.manager_run_id
        || result.receipt.request_digest !== attempt.descriptor_digest) reject("EVIDENCE_IDENTITY", 4);
    if (!this.runtime.managedBackend) reject("CAPABILITY_MISSING", 5);
    const associated = { ...attempt, manager_run_id: result.receipt.manager_run_id, lease_id: attempt.lease_id ?? descriptor.allocation_id };
    const proof = await this.runtime.managedBackend.verify_result(associated.lease_id, result.receipt.final_artifact_digest);
    assertExecutionEvidence(result.receipt, descriptor, associated, proof);
    // 权威副本先落 Task Keeper 库，再允许另一个明确调用 consume。
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const previous = this.store.get("agentcfg-receipts-v1", result.receipt.receipt_id);
      if (previous && canonical(previous) !== canonical(result)) reject("EVIDENCE_IDENTITY", 4);
      this.store.put("agentcfg-receipts-v1", result.receipt.receipt_id, result);
      this.store.put("agentcfg-attempts-v1", attemptId, { ...associated, state: result.receipt.terminal_status, result_receipt_id: result.receipt.receipt_id });
    });
    return clone(result);
  }
  async consume(receiptId: string) {
    const { owner } = await this.handshake();
    const result = this.store.get<any>("agentcfg-receipts-v1", receiptId);
    if (!result || result.receipt_digest !== digest(result.receipt)) reject("EVIDENCE_MISSING", 5);
    return this.client.call("consume", { owner, receipt_id: receiptId, receipt_digest: result.receipt_digest });
  }
  async reconcile(leaseId: string) {
    const { owner } = await this.handshake();
    return this.client.call("reconcile", { owner, lease_id: leaseId });
  }
}
