// backend 负责 supervisor/worker，队列和并发只由已存在的 AgentManager 负责。
import { canonical, closed, clone, reject, text } from "./managed-types.ts";

export class ManagerExecutor {
  constructor({ manager, backend, store, pi, context }) {
    this.manager = manager; this.backend = backend; this.store = store; this.pi = pi; this.context = context; this.admissions = new Map();
  }
  async dispatch(descriptor, { manager_run_id }) {
    const allocation = await this.backend.allocate(clone(descriptor), { manager_run_id });
    closed(allocation, ["lease_id", "attempt_id"]);
    if (!text(allocation.lease_id) || allocation.attempt_id !== descriptor.attempt_id) reject("DISPATCH_IDENTITY", 4);
    await this.store.transaction(state => {
      state.executions ??= {};
      if (state.executions[manager_run_id]) reject("DISPATCH_CONFLICT", 4);
      state.executions[manager_run_id] = { lease_id: allocation.lease_id, descriptor: clone(descriptor), state: "queued" };
    });
    let release;
    const admitted = new Promise(resolve => { release = resolve; });
    this.admissions.set(manager_run_id, release);
    let canceled = false;
    const executor = { kind: "managed-process", manager_run_id,
      execute: async () => {
        await admitted;
        if (canceled) return this.backend.cancel(allocation.lease_id);
        // 不在队列等待期间启动进程。开始时复核准入，未知结果不释放占位。
        await this.backend.recheck(clone(descriptor), allocation.lease_id);
        await this.store.transaction(state => { state.executions[manager_run_id].state = "starting"; });
        const result = await this.backend.execute(clone(descriptor), { manager_run_id, lease_id: allocation.lease_id });
        await this.store.transaction(state => { state.executions[manager_run_id].state = "observed"; });
        return result;
      },
      cancel: () => { canceled = true; release(); return this.backend.cancel(allocation.lease_id); },
      detach: () => this.backend.detach?.(allocation.lease_id),
    };
    try {
      const id = this.manager.spawnWithExecutor(this.pi, this.context(), descriptor.role_id, "TASK_KEEPER_ATTEMPT:" + descriptor.attempt_id,
        executor, { description: descriptor.role_id, cwd: descriptor.cwd, isBackground: true });
      if (id !== manager_run_id) reject("DISPATCH_IDENTITY", 4);
      return { ...allocation, state: this.manager.getRecord(id).status === "queued" ? "queued" : "running" };
    } catch (error) {
      // 分配后即使本地排队失败，也只通过监督者撤销，不删除持久分配。
      await this.backend.cancel(allocation.lease_id);
      throw error;
    }
  }
  acknowledge(runId) {
    const release = this.admissions.get(runId);
    if (!release) reject("DISPATCH_IDENTITY", 4);
    this.admissions.delete(runId);
    release();
  }
  async cancel(leaseId) {
    let runId;
    await this.store.transaction(state => {
      runId = Object.entries(state.executions ?? {}).find(([, value]) => value.lease_id === leaseId)?.[0];
    });
    if (!runId || !this.manager.isControlled(runId)) reject("TERMINATION_UNKNOWN", 4);
    this.manager.abort(runId);
  }
  async reconcile(leaseId, owner) {
    const proof = await this.backend.reconcile(leaseId, owner);
    if (!proof.protected && proof.termination_evidence?.verified === true) {
      let runId;
      await this.store.transaction(state => {
        runId = Object.entries(state.executions ?? {}).find(([, value]) => value.lease_id === leaseId)?.[0];
      });
      // 物理已终止可释放排队槽位，但无完整结果仍不能产生成功收据。
      if (runId && this.manager.isControlled(runId)) this.manager.settleControlled(runId,
        { response_text: "", terminal_status: "failed", termination_confirmed: true, external_work_empty: true });
    }
    return proof;
  }
  verify_result(leaseId, artifactDigest) { return this.backend.verify_result(leaseId, artifactDigest); }
  async gc(runId) {
    this.manager.consumeControlled(runId);
    // 只移除受管镜像；不影响其他未消费结果和权威证据。
    this.manager.removeConsumedControlled(runId);
  }
}
