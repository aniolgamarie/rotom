// 外部委托使用已有管理者的同一队列；持久幂等与物理停止分别核验。
import { randomUUID } from "node:crypto";
import { canonical, clone, closed, digest, reject, sha, text } from "./managed-types.ts";

export function assertDelegateReceipt(result, request, physical) {
  closed(result, ["receipt", "receipt_digest", "verification"]);
  const value = result.receipt;
  if (value) closed(value, [...Object.keys(request), "terminal_status", "backend_resume_token", "event_sequence_complete",
    "final_artifact_id", "final_artifact_digest", "process_terminated", "resources_reclaimed", "usage", "feedback_dispositions", "observed_model"]);
  if (!value || value.schema_version !== 2 || digest(value) !== result.receipt_digest
      || Object.keys(request).some(key => key !== "candidate_digest" && canonical(value[key]) !== canonical(request[key]))
      || value.observed_model !== null && canonical(value.observed_model) !== canonical(request.requested_model)) reject("DELEGATE_RECEIPT_IDENTITY", 4);
  if (!["completed", "failed", "canceled", "timeout"].includes(value.terminal_status) || !value.process_terminated || !value.resources_reclaimed
      || physical.lease_id !== request.lease_id || physical.protected || physical.termination_evidence?.verified !== true
      || value.terminal_status === "completed" && (result.verification !== "verified-execution"
        || !sha(value.final_artifact_digest) || !text(value.final_artifact_id) || !value.event_sequence_complete
        || request.execution_mode === "delegate-readonly" && value.candidate_digest !== request.candidate_digest)
      || value.terminal_status !== "completed" && result.verification !== "unverified") reject("DELEGATE_EXECUTION_UNVERIFIED", 4);
  return clone(result);
}

export class ExternalBridge {
  constructor({ runtime, manager, store, pi, getContext, pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), now = () => Date.now() }) {
    this.runtime = runtime; this.manager = manager; this.store = store; this.pi = pi; this.getContext = getContext;
    this.pause = pause; this.now = now; this.supervisor = runtime.supervisor;
    this.owner = { instance_id: runtime.owner.instance_id, manager_activation_id: runtime.owner.manager_activation_id, owner_nonce: runtime.owner.owner_nonce };
    this.closed = false;
  }
  async authorize(owner = this.owner) {
    if (this.closed || canonical(owner) !== canonical(this.owner)) reject("OWNER_MISMATCH", 4);
    if (this.runtime.managedRequestScope?.getStore()) reject("UNMETERED_EXTERNAL_DELEGATE", 5);
    const current = await this.supervisor.call("handshake", {});
    if (current.role !== "manager" || Object.keys(this.owner).some(key => current[key] !== this.owner[key])
        || current.runtime_identity !== this.runtime.installed.runtime_identity) reject("OWNER_MISMATCH", 4);
  }
  async submit_delegate(envelope) {
    await this.authorize();
    closed(envelope, ["request_id", "idempotency_key", "instance_id", "policy_digest", "request_digest", "backend_request"]);
    const input = envelope.backend_request;
    closed(input, ["backend", "mode", "preset", "task", "cwd", "model", "timeout_seconds"], ["context_artifact", "feedback_required"]);
    if (!text(envelope.request_id) || !text(envelope.idempotency_key) || envelope.instance_id !== this.owner.instance_id
        || envelope.policy_digest !== digest(this.runtime.manifest.permission_policy) || envelope.request_digest !== digest(input)
        || !["review", "investigate"].includes(input.mode)) reject("DELEGATE_REQUEST_INVALID", 2);
    const key = digest(envelope.idempotency_key); let record, fresh = false;
    await this.store.transaction(state => {
      state.delegates ??= {};
      record = state.delegates[key];
      if (record) {
        if (record.request_digest !== envelope.request_digest) reject("DISPATCH_CONFLICT", 4);
      } else {
        record = { dispatch_id: "delegate-" + randomUUID(), request_digest: envelope.request_digest, request: null,
          state: "starting", result: null, owner: clone(this.owner) };
        state.delegates[key] = record; fresh = true;
      }
      record = clone(record);
    });
    if (fresh) {
      try {
        const request = await this.supervisor.call("delegate_prepare", { idempotency_key: envelope.idempotency_key, ...clone(input) });
        if (request.instance_id !== this.owner.instance_id || request.owner_nonce !== this.owner.owner_nonce
            || request.runtime_identity !== this.runtime.installed.runtime_identity || request.execution_mode !== "delegate-readonly"
            || ["backend", "mode", "preset", "cwd", "timeout_seconds"].some(key => request[key] !== input[key])
            || canonical(request.requested_model) !== canonical(input.model) || request.policy_digest !== envelope.policy_digest
            || request.execution_boundary !== (input.backend === "codex" ? "native-sandbox" : "agentcfg-tools")
            || !sha(request.execution_policy_digest) || !text(request.run_id) || !text(request.lease_id)) reject("DELEGATE_REQUEST_IDENTITY", 4);
        record.request = request;
        await this.store.transaction(state => { state.delegates[key].request = clone(request); state.delegates[key].state = "queued"; });
        let canceled = false;
        const cancel = async () => {
          canceled = true;
          await this.supervisor.call("delegate_cancel", { run_id: request.run_id });
          const proof = await this.supervisor.call("reconcile", { lease_id: request.lease_id });
          if (!proof.protected && proof.termination_evidence?.verified) {
            await this.store.transaction(state => { state.delegates[key].state = "canceled"; });
            return { terminal_status: "canceled", response_text: "", termination_confirmed: true, external_work_empty: true };
          }
          return undefined;
        };
        const executor = { kind: "external", manager_run_id: record.dispatch_id, cancel,
          execute: async () => {
            if (canceled) return cancel();
            try {
              await this.supervisor.call("delegate_start", { run_id: request.run_id });
              const until = this.now() + request.timeout_seconds * 1000 + 10000;
              while (this.now() < until) {
                const status = await this.supervisor.call("delegate_status", { run_id: request.run_id });
                await this.store.transaction(state => { state.delegates[key].state = status.state; });
                if (["completed", "failed", "canceled", "timeout"].includes(status.state)) {
                  // 结果刷新可能推进最终回收；不能用刷新之前的物理状态判定这份收据。
                  const candidate = status.state === "completed" ? await this.supervisor.call("delegate_result", { run_id: request.run_id }) : null;
                  const physical = await this.supervisor.call("reconcile", { lease_id: request.lease_id });
                  if (physical.protected || physical.termination_evidence?.verified !== true) reject("TERMINATION_UNKNOWN", 4);
                  const result = candidate ? assertDelegateReceipt(candidate, request, physical) : null;
                  await this.store.transaction(state => { state.delegates[key].result = result; });
                  return { terminal_status: status.state, response_text: result ? "Delegate execution verified; inspect its receipt and artifact." : "",
                    termination_confirmed: true, external_work_empty: true };
                }
                await this.pause(250);
              }
              return { terminal_status: "timeout", response_text: "", termination_confirmed: false, external_work_empty: false };
            } catch (error) {
              const physical = await this.supervisor.call("reconcile", { lease_id: request.lease_id });
              await this.store.transaction(state => { state.delegates[key].state = !physical.protected && physical.termination_evidence?.verified ? "failed" : "unknown"; });
              if (!physical.protected && physical.termination_evidence?.verified) return { terminal_status: "failed", response_text: "", termination_confirmed: true, external_work_empty: true };
              throw error;
            }
          } };
        this.manager.spawnWithExecutor(this.pi, this.getContext(), "model-delegate", "DELEGATE_RUN:" + request.run_id, executor,
          { description: input.preset, cwd: input.cwd, isBackground: true });
        record.state = this.manager.getRecord(record.dispatch_id).status === "queued" ? "queued" : "running";
      } catch {
        await this.store.transaction(state => { state.delegates[key].state = "start_unknown"; });
        record.state = "start_unknown";
      }
    }
    return { dispatch_id: record.dispatch_id, run_id: record.request?.run_id ?? null, lease_id: record.request?.lease_id ?? null, state: record.state };
  }
  async find(owner, runId) {
    await this.authorize(owner); let result;
    await this.store.transaction(state => { result = Object.values(state.delegates ?? {}).find(row => row.request?.run_id === runId);
      if (!result) reject("DELEGATE_RUN_NOT_FOUND", 4); result = clone(result); });
    return result;
  }
  async get_delegate_result(owner, runId) {
    const record = await this.find(owner, runId);
    const result = await this.supervisor.call("delegate_result", { run_id: runId });
    // 结果刷新可能刚完成回收；物理证明必须在结果之后采样，不能使用之前的活动快照。
    const physical = await this.supervisor.call("reconcile", { lease_id: record.request.lease_id });
    const verified = assertDelegateReceipt(result, record.request, physical);
    const mirror = this.manager.getRecord(record.dispatch_id);
    if (mirror && this.manager.isControlled(record.dispatch_id)) {
      await mirror.promise;
      this.manager.consumeControlled(record.dispatch_id);
      this.manager.removeConsumedControlled(record.dispatch_id);
    }
    return verified;
  }
  async cancel_delegate(owner, runId) {
    const record = await this.find(owner, runId);
    this.manager.abort(record.dispatch_id);
    return { accepted: true, termination_confirmed: false };
  }
  async submit_batch(owner, batchId, items) {
    await this.authorize(owner);
    if (!text(batchId) || !/^[a-zA-Z0-9_-]{1,100}$/.test(batchId) || !Array.isArray(items) || !items.length || items.length > 32) reject("DELEGATE_BATCH_INVALID", 2);
    const batchKey = digest(batchId);
    let row, fresh = false;
    await this.store.transaction(state => {
      state.delegate_batches ??= {};
      row = state.delegate_batches[batchKey];
      if (row) { if (row.items_digest !== digest(items)) reject("DELEGATE_BATCH_CONFLICT", 4); }
      else { row = { batch_id: batchId, parent_owner: clone(owner), dispatch_ids: [], result_refs: [], state: "starting", items_digest: digest(items) };
        state.delegate_batches[batchKey] = row; fresh = true; }
      row = clone(row);
    });
    if (fresh) for (const item of items) {
      try {
        const result = await this.submit_delegate(item);
        await this.store.transaction(state => { const saved = state.delegate_batches[batchKey]; saved.dispatch_ids.push(result.dispatch_id);
          saved.state = result.state === "start_unknown" ? "partial" : saved.state === "partial" ? "partial" : "running"; row = clone(saved); });
      } catch {
        await this.store.transaction(state => { state.delegate_batches[batchKey].state = "partial"; row = clone(state.delegate_batches[batchKey]); });
        break;
      }
    }
    const { items_digest, ...batch } = row; return batch;
  }
  async get_batch(owner, batchId) {
    await this.authorize(owner); let batch, runs;
    await this.store.transaction(state => {
      batch = state.delegate_batches?.[digest(batchId)];
      if (!batch) reject("DELEGATE_BATCH_NOT_FOUND", 4);
      batch = clone(batch);
      runs = Object.values(state.delegates ?? {}).filter(row => batch.dispatch_ids.includes(row.dispatch_id)).map(clone);
    });
    const terminal = row => ["completed", "failed", "canceled", "timeout"].includes(row.state);
    const result_refs = [];
    let failed = batch.state === "partial" || runs.length !== batch.dispatch_ids.length;
    for (const row of runs) if (row.state === "completed") {
      try { const result = await this.get_delegate_result(owner, row.request.run_id); result_refs.push(result.receipt.receipt_id ?? result.receipt.final_artifact_id); }
      catch { failed = true; }
    }
    const state = failed || runs.some(row => ["failed", "unknown", "start_unknown", "timeout"].includes(row.state)) ? "partial"
      : runs.length && runs.every(row => row.state === "canceled") ? "canceled"
      : runs.length && runs.every(row => row.state === "completed") ? "completed"
      : runs.length && runs.every(terminal) ? "partial" : batch.state === "starting" ? "starting" : "running";
    return { batch_id: batchId, parent_owner: clone(owner), dispatch_ids: batch.dispatch_ids, result_refs, state };
  }
  async cancel_batch(owner, batchId) {
    const batch = await this.get_batch(owner, batchId); let runs;
    await this.store.transaction(state => { runs = Object.values(state.delegates ?? {}).filter(row => batch.dispatch_ids.includes(row.dispatch_id)).map(clone); });
    for (const run of runs) if (run.request) await this.cancel_delegate(owner, run.request.run_id);
    return this.get_batch(owner, batchId);
  }
  async close() { this.closed = true; await this.store.close?.(); }
}
