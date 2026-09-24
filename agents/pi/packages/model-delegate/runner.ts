import { randomUUID } from "node:crypto";
import { ExternalClient } from "@agentcfg/pi-runtime/external-rpc";
import { digest, reject } from "@agentcfg/pi-runtime/managed-types";
import { resolveToolRequest } from "./contract.ts";

export class DelegateRunner {
  private runtime: any;
  private client: ExternalClient;
  constructor(pi: any, runtime: any) { this.runtime = runtime; this.client = new ExternalClient(pi.events); }
  private assertCurrent() {
    if ((globalThis as { [key: symbol]: unknown })[Symbol.for("agentcfg.pi.runtime.v1")] !== this.runtime) reject("DELEGATE_STALE_RUNTIME", 4);
  }
  async execute(callId: string, params: any, signal?: AbortSignal, update?: (value: any) => void) {
    this.assertCurrent();
    const runtime = this.runtime;
    if (signal?.aborted) reject("DELEGATE_CANCELED", 4);
    const resolved = resolveToolRequest(params, runtime);
    const { execution_mode, ...selected } = resolved;
    const backend = { ...selected, feedback_required: Boolean(resolved.context_artifact) };
    const owner = { instance_id: runtime.owner.instance_id, manager_activation_id: runtime.owner.manager_activation_id, owner_nonce: runtime.owner.owner_nonce };
    const run = await this.client.call("submit_delegate", { request_id: randomUUID(), idempotency_key: digest({ owner, call_id: callId }),
      instance_id: owner.instance_id, policy_digest: digest(runtime.manifest.permission_policy), request_digest: digest(backend), backend_request: backend });
    this.assertCurrent();
    if (!run.run_id || !run.lease_id) return { state: "start_unknown", dispatch_id: run.dispatch_id, verification: "unverified" };
    const cancel = () => { void this.client.call("cancel_delegate", { owner, run_id: run.run_id }).catch(() => {}); };
    signal?.addEventListener("abort", cancel, { once: true });
    const end = Date.now() + resolved.timeout_seconds * 1000 + 10000;
    let lastCursor: string | null = null;
    let terminalRefresh = false;
    try {
      if (signal?.aborted) cancel();
      while (Date.now() < end) {
        this.assertCurrent();
        try {
          const result = await this.client.call("get_delegate_result", { owner, run_id: run.run_id });
          this.assertCurrent();
          const receipt = result.receipt;
          const summary: any = { schema_version: 2, run_id: run.run_id, state: receipt.terminal_status, verification: result.verification,
            artifact_ref: receipt.final_artifact_id, artifact_digest: receipt.final_artifact_digest,
            process_terminated: receipt.process_terminated, resources_reclaimed: receipt.resources_reclaimed,
            task_acceptance: "unverified", feedback_dispositions: receipt.feedback_dispositions };
          if (result.verification === "verified-execution") {
            const chunk = await runtime.supervisor.call("delegate_artifact", { run_id: run.run_id, offset: 0, limit: 1024 });
            this.assertCurrent();
            summary.result_excerpt = chunk.content;
            summary.next_offset = chunk.next_offset;
            summary.total_bytes = chunk.total_bytes;
          }
          if (Buffer.byteLength(JSON.stringify(summary), "utf8") > 4096) delete summary.result_excerpt;
          return summary;
        } catch (error) {
          this.assertCurrent();
          if (![4, 5].includes((error as any)?.exitCode)) throw error;
          // 只读轮询不重发 submit/start；错误不当作成功或已停止。
          const state = await runtime.supervisor.call("inspect", { lease_id: run.lease_id });
          if (!state.protected && state.termination_evidence?.verified) {
            // 子进程可能恰在 pending 响应与本次观察之间退出；只读重取一次最终收据。
            if (!terminalRefresh) { terminalRefresh = true; continue; }
            return { schema_version: 2, run_id: run.run_id,
              state: "failed", verification: "unverified", process_terminated: true, resources_reclaimed: true, error_code: "DELEGATE_RESULT_REJECTED" };
          }
        }
        try {
          const progress: { next_cursor: string; events: unknown[] } = await runtime.supervisor.call("delegate_poll", { run_id: run.run_id, after: lastCursor });
          lastCursor = progress.next_cursor;
          if (progress.events.length) update?.(progress);
        } catch { /* 排队尚无原生run时，只保留正在等待的控制状态。 */ }
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      return { schema_version: 2, run_id: run.run_id, lease_id: run.lease_id, state: "unknown", verification: "unverified", process_terminated: false };
    } finally { signal?.removeEventListener("abort", cancel); }
  }
}
