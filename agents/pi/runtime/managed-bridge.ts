// 单管理者桥接的协议层；executor 和事务存储由经过监督的 AgentManager 注入。
import { createHmac, randomUUID } from "node:crypto";
import { assertDescriptor, assertEvent, assertOwner, canonical, clone, closed, digest, list, reject, sha, text } from "./managed-types.ts";
import { assertReceiptAssociation } from "./managed-results.ts";

const capabilities = ["managed-process", "fresh-context", "guarded-tools", "request-metering", "durable-results", "physical-termination", "workspace-leases"];

export class ManagedBridge {
  constructor({ owner, runtime, store, executor, resolve, listeners, now = () => Date.now() }) {
    closed(runtime, ["identity", "slice_identity", "capabilities"]);
    if (!sha(runtime.identity) || !sha(runtime.slice_identity) || !list(runtime.capabilities)) reject();
    this.owner = clone(assertOwner(owner));
    this.runtime = clone(runtime);
    this.store = store;
    this.executor = executor;
    this.resolve = resolve;
    this.listeners = listeners;
    this.now = now;
  }
  ownerCheck(owner) {
    assertOwner(owner);
    if (canonical(owner) !== canonical(this.owner)) reject("OWNER_MISMATCH", 4);
    if (this.listeners() !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
  }
  handshake(request) {
    closed(request, ["protocol_version", "instance_id", "request_id"]);
    if (request.protocol_version !== 1 || request.instance_id !== this.owner.instance_id || !text(request.request_id)) reject();
    this.ownerCheck(this.owner);
    if (capabilities.some(name => !this.runtime.capabilities.includes(name))) reject("CAPABILITY_MISSING", 5);
    return { ...clone(this.owner), runtime_identity: this.runtime.identity, capabilities: [...this.runtime.capabilities] };
  }
  async preflight(descriptor) {
    assertDescriptor(descriptor);
    this.ownerCheck(Object.fromEntries(Object.keys(this.owner).map(key => [key, descriptor[key]])));
    if (descriptor.runtime_digest !== this.runtime.identity || Date.parse(descriptor.deadline) <= this.now()) reject("ADMISSION_STALE", 4);
    if (capabilities.some(name => !this.runtime.capabilities.includes(name))) reject("CAPABILITY_MISSING", 5);
    const resolved = await this.resolve(clone(descriptor), { purpose: "admission" });
    if (!resolved || resolved.transport_authenticated !== true || resolved.role_digest !== descriptor.role_digest
        || resolved.policy_digest !== descriptor.policy_digest || resolved.model_digest !== descriptor.model_digest
        || resolved.workspace_identity_digest !== descriptor.workspace_identity_digest || resolved.grant_generation !== descriptor.grant_generation
        || resolved.provider_id !== descriptor.provider_id || resolved.model_id !== descriptor.model_id
        || canonical(resolved.allowed_tools) !== canonical(descriptor.allowed_tools)) reject("CAPABILITY_MISSING", 5);
    const admission = { descriptor_digest: digest(descriptor), resolved_digest: digest(resolved),
      runtime_identity: this.runtime.identity, slice_identity: this.runtime.slice_identity, deadline: descriptor.deadline, ...this.owner };
    const token = createHmac("sha256", this.owner.owner_nonce).update(canonical(admission)).digest("hex");
    await this.store.transaction(state => {
      state.admissions ??= {};
      state.admissions[token] = admission;
    });
    return { admission_token: token, descriptor_digest: admission.descriptor_digest, resolved_digest: admission.resolved_digest };
  }
  async dispatch(request) {
    closed(request, ["descriptor", "admission_token", "idempotency_key"]);
    const { descriptor, admission_token, idempotency_key } = request;
    assertDescriptor(descriptor);
    this.ownerCheck(Object.fromEntries(Object.keys(this.owner).map(key => [key, descriptor[key]])));
    if (!text(idempotency_key)) reject();
    if (capabilities.some(name => !this.runtime.capabilities.includes(name))) reject("CAPABILITY_MISSING", 5);
    const descriptorDigest = digest(descriptor);
    const key = digest({ owner: this.owner, idempotency_key });
    let result, start = false;
    await this.store.transaction(async state => {
      state.runs ??= {};
      const previous = state.runs[key];
      if (previous) {
        if (previous.descriptor_digest !== descriptorDigest) reject("DISPATCH_CONFLICT", 4);
        result = clone(previous);
        return;
      }
      if (Object.values(state.runs).some(run => run.attempt_id === descriptor.attempt_id)) reject("DISPATCH_CONFLICT", 4);
      const admission = state.admissions?.[admission_token];
      if (!admission || admission.descriptor_digest !== descriptorDigest || Date.parse(admission.deadline) <= this.now()) reject("ADMISSION_STALE", 4);
      if (createHmac("sha256", this.owner.owner_nonce).update(canonical(admission)).digest("hex") !== admission_token) reject("ADMISSION_STALE", 4);
      const current = await this.resolve(clone(descriptor), { purpose: "admission" });
      if (digest(current) !== admission.resolved_digest || this.runtime.identity !== admission.runtime_identity || this.runtime.slice_identity !== admission.slice_identity) reject("ADMISSION_STALE", 4);
      result = { attempt_id: descriptor.attempt_id, manager_run_id: randomUUID(), lease_id: null, descriptor_digest: descriptorDigest,
        state: "starting", descriptor: clone(descriptor), owner: clone(this.owner), sequences: {}, events: {}, sequence_complete: true, receipt: null, consumed: false };
      state.runs[key] = result;
      start = true;
    });
    if (start) {
      try {
        const started = await this.executor.dispatch(clone(descriptor), { manager_run_id: result.manager_run_id });
        closed(started, ["attempt_id", "lease_id"], ["state"]);
        if (started.state !== undefined && !["queued", "running"].includes(started.state)) reject("DISPATCH_IDENTITY", 4);
        if (started.attempt_id !== descriptor.attempt_id || !text(started.lease_id)) reject("DISPATCH_IDENTITY", 4);
        await this.store.transaction(state => {
          Object.assign(state.runs[key], { lease_id: started.lease_id, state: started.state ?? "running" });
          result = clone(state.runs[key]);
        });
        await this.executor.acknowledge?.(result.manager_run_id);
      } catch {
        await this.store.transaction(state => {
          state.runs[key].state = "start_unknown";
          result = clone(state.runs[key]);
        });
      }
    }
    return { attempt_id: result.attempt_id, manager_run_id: result.manager_run_id, lease_id: result.lease_id,
      state: result.state === "starting" ? "start_unknown" : result.state };
  }
  async find(owner, runId, operation) {
    this.ownerCheck(owner);
    let result;
    await this.store.transaction(async state => {
      const run = Object.values(state.runs ?? {}).find(value => value.manager_run_id === runId);
      if (!run || canonical(run.owner) !== canonical(owner)) reject("RUN_NOT_FOUND", 4);
      result = await operation(run);
    });
    return result;
  }
  async inspect(owner, runId) {
    return this.find(owner, runId, run => ({ attempt_id: run.attempt_id, state: run.state, lease_id: run.lease_id,
      sequence_complete: run.sequence_complete, consumed: run.consumed }));
  }
  async reconcile(owner, leaseId) {
    this.ownerCheck(owner);
    if (!text(leaseId)) reject();
    // supervisor 从自己的持久记录读取旧 owner；此入口不接收旧 nonce 或停止参数。
    return this.executor.reconcile(leaseId, { instance_id: this.owner.instance_id });
  }
  async event(owner, event) {
    assertEvent(event);
    return this.find(owner, event.manager_run_id, run => {
      if (["task_id", "step_id", "attempt_id"].some(key => event[key] !== run.descriptor[key])
          || !run.descriptor.write_roots.length && event.candidate_digest !== run.descriptor.snapshot_digest) reject("EVENT_IDENTITY", 4);
      const hash = digest(event);
      if (run.events[event.event_id]) {
        if (run.events[event.event_id] !== hash) reject("EVENT_IDENTITY", 4);
        return { duplicate: true };
      }
      if (run.receipt !== null) reject("EVENT_AFTER_FINAL", 4);
      if (event.sequence <= (run.sequences[event.producer_id] ?? 0)) reject("EVENT_ORDER", 4);
      if (event.sequence !== (run.sequences[event.producer_id] ?? 0) + 1) run.sequence_complete = false;
      run.sequences[event.producer_id] = event.sequence;
      run.events[event.event_id] = hash;
      run.last_events ??= {};
      run.last_events[event.producer_id] = clone(event);
      if (event.phase === "started" && ["starting", "queued"].includes(run.state)) run.state = "running";
      return { duplicate: false, sequence_complete: run.sequence_complete };
    });
  }
  async cancelAttempt(owner, attemptId, reason) {
    this.ownerCheck(owner);
    let runId;
    await this.store.transaction(state => {
      const run = Object.values(state.runs ?? {}).find(value => value.attempt_id === attemptId && canonical(value.owner) === canonical(owner));
      if (!run) reject("RUN_NOT_FOUND", 4);
      runId = run.manager_run_id;
    });
    return this.cancel(owner, runId, reason);
  }
  async cancel(owner, runId, reason) {
    if (!text(reason)) reject();
    const intent = await this.find(owner, runId, run => {
      if (run.receipt !== null) return { finished: true };
      if (!run.lease_id) reject("TERMINATION_UNKNOWN", 4);
      run.state = "cancel_requested";
      return { finished: false, lease_id: run.lease_id };
    });
    if (intent.finished) return { accepted: true, termination_confirmed: true };
    // 不跨 IPC 持有事务锁；取消可能触发回报事件，不能让回报等待取消自身。
    try { await this.executor.cancel(intent.lease_id, reason); }
    catch { reject("TERMINATION_UNKNOWN", 4); }
    return { accepted: true, termination_confirmed: false };
  }
  async publishResult(owner, runId, receipt) {
    return this.find(owner, runId, async run => {
      if (run.receipt !== null) {
        if (digest(run.receipt) !== digest(receipt)) reject("EVIDENCE_IDENTITY", 4);
        return { receipt_id: run.receipt.receipt_id, receipt_digest: digest(run.receipt) };
      }
      const proof = await this.executor.verify_result(run.lease_id, receipt.final_artifact_digest);
      assertReceiptAssociation(receipt, run, proof);
      const current = await this.resolve(clone(run.descriptor), { purpose: "result" });
      if (current.snapshot_digest !== receipt.candidate_digest) reject("SNAPSHOT_STALE", 4);
      run.receipt = clone(receipt);
      run.state = receipt.terminal_status;
      return { receipt_id: receipt.receipt_id, receipt_digest: digest(receipt) };
    });
  }
  async get_result(owner, attemptId) {
    this.ownerCheck(owner);
    let result;
    await this.store.transaction(async state => {
      const run = Object.values(state.runs ?? {}).find(item => item.attempt_id === attemptId && canonical(item.owner) === canonical(owner));
      if (!run?.receipt || run.garbage_collected) reject("EVIDENCE_MISSING", 5);
      const current = await this.resolve(clone(run.descriptor), { purpose: "result" });
      if (current.snapshot_digest !== run.receipt.candidate_digest) reject("SNAPSHOT_STALE", 4);
      const proof = await this.executor.verify_result(run.lease_id, run.receipt.final_artifact_digest);
      assertReceiptAssociation(run.receipt, run, proof);
      result = { receipt: clone(run.receipt), receipt_digest: digest(run.receipt) };
    });
    return result;
  }
  async consume(owner, receiptId, receiptDigest) {
    this.ownerCheck(owner);
    await this.store.transaction(state => {
      const run = Object.values(state.runs ?? {}).find(item => item.receipt?.receipt_id === receiptId && canonical(item.owner) === canonical(owner));
      if (!run || digest(run.receipt) !== receiptDigest) reject("EVIDENCE_IDENTITY", 4);
      run.consumed = true;
    });
    return { consumed: true };
  }
  async gc(owner, runId) {
    return this.find(owner, runId, async run => {
      if (!run.consumed) reject("EVIDENCE_NOT_CONSUMED", 4);
      if (!run.garbage_collected) {
        await this.executor.gc(run.manager_run_id);
        run.garbage_collected = true;
        run.events = {};
        run.last_events = {};
      }
      // 保留幂等墓碑，GC 不得使旧请求再次执行；权威证据由 Task Keeper 保留。
      return { collected: true };
    });
  }
}
