// 执行只提交已有 AgentManager 与 supervisor；本类保留进程工具的视图和日志。
import { randomUUID } from "node:crypto";
import type { KillResult, ManagerEvent, WriteResult } from "../types";
import { LIVE_STATUSES } from "../types";
import type { ManagedProcessRecord } from "./internal-types";
import { formatProcess } from "./internal-types";
import type { ProcessLogStore } from "./process-log-store";
import type { ProcessOutput } from "./process-output";
import type { ProcessRegistry } from "./process-registry";

type Ticket = { operation_id: string; lease_id: string; manager_run_id?: string; timeout_seconds: number; kind: string; tool_name: string; write: boolean };
interface ProcessRuntimeControllerDeps {
  registry: ProcessRegistry;
  logs: ProcessLogStore;
  output: ProcessOutput;
  emit: (event: ManagerEvent) => void;
  getConfiguredShellPath: () => string | undefined;
}

export class ProcessRuntimeController {
  private readonly tickets = new Map<string, Ticket>();
  private readonly cursors = new Map<string, number>();
  private readonly canceled = new Set<string>();
  private readonly pulls = new Map<string, Promise<void>>();
  private readonly jobs = new Map<string, Promise<void>>();
  private watcher: ReturnType<typeof setInterval> | null = null;
  private polling = false;
  private shuttingDown = false;
  private completionSequence = 0;
  private readonly deps: ProcessRuntimeControllerDeps;
  constructor(deps: ProcessRuntimeControllerDeps) { this.deps = deps; }
  private context(): any {
    const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
    if (!runtime?.ordinaryOperations || runtime.owner?.role !== "manager") throw new Error("PROCESS_SUPERVISOR_REQUIRED");
    return runtime;
  }
  async start(name: string, command: string, cwd: string): Promise<ManagedProcessRecord> {
    if (this.shuttingDown) throw new Error("PROCESS_SHUTTING_DOWN");
    const runtime = this.context();
    if (runtime.managedRequestScope?.getStore() || !runtime.manifest.plugins.includes("pi-processes")) throw new Error("MANAGED_EXTERNAL_PROCESS_DENIED");
    const id = this.deps.registry.nextId();
    const ticket: Ticket = await runtime.supervisor.call("ordinary_command_prepare", { operation_id: "process-" + randomUUID(),
      role_id: "main", tool_name: "process", cwd, input: { command } });
    let paths;
    try { paths = this.deps.logs.createLogs(id); }
    catch (error) { await runtime.ordinaryOperations.abort(ticket); throw error; }
    const record: ManagedProcessRecord = { id, name, pid: -1, command, cwd, startTime: Date.now(), endTime: null, status: "queued",
      exitCode: null, success: null, ...paths, endReason: null, signal: null, errorMessage: null, stdin: null, stdinClosed: false,
      lastSignalSent: null, completionSequence: null, stdoutPendingLine: Buffer.alloc(0), stderrPendingLine: Buffer.alloc(0),
      stdoutLineOverflowed: false, stderrLineOverflowed: false, appendedLines: [], droppedLineCount: 0 };
    this.deps.registry.add(record); this.tickets.set(id, ticket); this.cursors.set(id, 0);
    this.deps.emit({ type: "processes_changed" });
    this.ensureWatcher();
    const job: Promise<void> = runtime.ordinaryOperations.write(ticket, null, null, undefined, { onStarted: (proof: any) => {
      if (proof.lease_id !== ticket.lease_id || !Number.isInteger(proof.process_identity?.pid) || proof.process_identity.pid <= 0) throw new Error("PROCESS_START_UNKNOWN");
      record.pid = proof.process_identity.pid; record.status = "running";
      this.deps.emit({ type: "process_started", info: formatProcess(record) });
    } }).then(async (result: any) => {
      await this.pull(record, true);
      record.exitCode = result.exitCode; record.success = result.exitCode === 0 && !this.canceled.has(id);
      record.endReason = this.canceled.has(id) ? "signal" : "exit";
      this.ended(record, this.canceled.has(id) ? "killed" : "exited");
    }).catch(async () => {
      record.errorMessage = "PROCESS_EXECUTION_FAILED";
      try {
        const proof = await runtime.supervisor.call("reconcile", { lease_id: ticket.lease_id });
        if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
          await this.pull(record, true).catch(() => {});
          record.success = false; record.endReason = this.canceled.has(id) ? "signal" : "spawn_error";
          this.ended(record, this.canceled.has(id) ? "killed" : "exited");
        } else record.status = "terminate_timeout";
      } catch { record.status = "terminate_timeout"; }
    });
    this.jobs.set(id, job);
    return record;
  }
  private ensureWatcher(): void {
    if (this.watcher) return;
    this.watcher = setInterval(() => { void this.poll(); }, 200);
    this.watcher.unref?.();
  }
  private pull(record: ManagedProcessRecord, final = false): Promise<void> {
    const previous = this.pulls.get(record.id) ?? Promise.resolve();
    const next = previous.catch(() => {}).then(() => this.pullNow(record, final));
    this.pulls.set(record.id, next);
    return next.finally(() => { if (this.pulls.get(record.id) === next) this.pulls.delete(record.id); });
  }
  private async pullNow(record: ManagedProcessRecord, final: boolean): Promise<void> {
    const ticket = this.tickets.get(record.id); if (!ticket) return;
    let more = true;
    for (let pages = 0; more && pages < (final ? 256 : 16); pages++) {
      const result = await this.context().supervisor.call("ordinary_command_output", { operation_id: ticket.operation_id, cursor: this.cursors.get(record.id) ?? 0 });
      if (result.dropped) {
        const marker = Buffer.from("[supervisor output window truncated]\n");
        this.deps.logs.appendStderr(record.stderrFile, marker); this.deps.output.onStderrChunk(record, marker);
      }
      for (const event of result.events) {
        const data = Buffer.from(event.data_b64, "base64");
        if (event.stream === "stdout") { this.deps.logs.appendStdout(record.stdoutFile, data); this.deps.output.onStdoutChunk(record, data); }
        else if (event.stream === "stderr") { this.deps.logs.appendStderr(record.stderrFile, data); this.deps.output.onStderrChunk(record, data); }
        else throw new Error("PROCESS_OUTPUT_IDENTITY");
      }
      this.cursors.set(record.id, result.next_cursor); more = result.has_more;
    }
  }
  private async poll(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      for (const record of this.deps.registry.values()) {
        if (!LIVE_STATUSES.has(record.status)) continue;
        try { await this.pull(record); } catch { record.errorMessage = "PROCESS_OUTPUT_UNAVAILABLE"; }
        if (record.status === "terminate_timeout") {
          const ticket = this.tickets.get(record.id); if (!ticket) continue;
          try {
            const proof = await this.context().supervisor.call("reconcile", { lease_id: ticket.lease_id });
            if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
              const manager = (globalThis as any)[Symbol.for("agentcfg.pi.managed.v1")]?.manager;
              if (ticket.manager_run_id && manager?.isControlled(ticket.manager_run_id)) {
                manager.settleControlled(ticket.manager_run_id, { terminal_status: "failed", response_text: "", termination_confirmed: true, external_work_empty: true });
                manager.consumeControlled(ticket.manager_run_id); manager.removeConsumedControlled(ticket.manager_run_id);
              }
              record.success = false; record.endReason = "lost"; this.ended(record, this.canceled.has(record.id) ? "killed" : "exited");
            }
          } catch { /* 未确认终止保持活动视图与底层租约。 */ }
        }
      }
    } finally { this.polling = false; }
  }
  private ended(record: ManagedProcessRecord, status: "exited" | "killed"): void {
    if (!LIVE_STATUSES.has(record.status)) return;
    record.status = status; record.endTime = Date.now(); record.stdinClosed = true; record.completionSequence = ++this.completionSequence;
    this.deps.output.flush(record); this.deps.emit({ type: "process_ended", info: formatProcess(record) });
    const ticket = this.tickets.get(record.id);
    if (ticket) void this.context().supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }).catch(() => {});
    if (!this.deps.registry.hasAliveishProcesses()) this.stopWatcher();
  }
  async kill(id: string, opts?: { signal?: NodeJS.Signals; timeoutMs?: number }): Promise<KillResult> {
    const record = this.deps.registry.getRecord(id), ticket = this.tickets.get(id);
    if (!record || !ticket) throw new Error("PROCESS_NOT_FOUND");
    if (!LIVE_STATUSES.has(record.status)) return { ok: true, info: formatProcess(record) };
    if (opts?.signal && !["SIGTERM", "SIGKILL"].includes(opts.signal)) return { ok: false, info: formatProcess(record), reason: "error" };
    const runtime = this.context(), observed = await runtime.supervisor.call("inspect", { lease_id: ticket.lease_id });
    if (!observed.protected && observed.termination_evidence?.verified) {
      await this.jobs.get(id);
      return { ok: true, info: formatProcess(record) };
    }
    this.canceled.add(id); record.status = "terminating";
    await runtime.supervisor.call(observed.state === "allocating" ? "abort_allocation" : "cancel", {
      lease_id: ticket.lease_id, ...(observed.state === "allocating" ? {} : { force: opts?.signal === "SIGKILL" }) });
    const manager = (globalThis as any)[Symbol.for("agentcfg.pi.managed.v1")]?.manager;
    if (ticket.manager_run_id) manager?.abort(ticket.manager_run_id);
    const until = Date.now() + Math.min(10000, Math.max(0, opts?.timeoutMs ?? 3000));
    do {
      const proof = await runtime.supervisor.call("reconcile", { lease_id: ticket.lease_id });
      if (proof.lease_id === ticket.lease_id && !proof.protected && proof.termination_evidence?.verified) {
        record.success = false; record.endReason = "signal"; await this.pull(record).catch(() => {}); this.ended(record, "killed");
        return { ok: true, info: formatProcess(record) };
      }
      await new Promise(resolve => setTimeout(resolve, 50));
    } while (Date.now() < until);
    record.status = "terminate_timeout"; record.endReason = "kill_timeout"; this.ensureWatcher();
    return { ok: false, info: formatProcess(record), reason: "timeout" };
  }
  async writeToStdin(id: string, data: string, opts?: { end?: boolean }): Promise<WriteResult> {
    const record = this.deps.registry.getRecord(id), ticket = this.tickets.get(id);
    if (!record || !ticket) return { ok: false, reason: "not_found" };
    if (!LIVE_STATUSES.has(record.status)) return { ok: false, reason: "process_exited" };
    try {
      const result = await this.context().supervisor.call("ordinary_command_stdin", { operation_id: ticket.operation_id, data, end: opts?.end ?? false });
      if (result.accepted_bytes !== Buffer.byteLength(data) || result.stdin_closed !== (opts?.end ?? false)) throw new Error("PROCESS_INPUT_UNCONFIRMED");
      record.stdinClosed = result.stdin_closed; return { ok: true };
    } catch { return { ok: false, reason: "write_error" }; }
  }
  async killAll(): Promise<void> { await Promise.allSettled([...this.deps.registry.values()].filter(row => LIVE_STATUSES.has(row.status)).map(row => this.kill(row.id, { signal: "SIGKILL" }))); }
  killAllLive(): Promise<void> { return this.killAll(); }
  beginShutdown(): void { this.shuttingDown = true; }
  stopWatcher(): void { if (this.watcher) clearInterval(this.watcher); this.watcher = null; }
  stopFinishedReaper(): void {}
  clearFinished(): number {
    let count = 0;
    for (const row of [...this.deps.registry.values()]) {
      if (LIVE_STATUSES.has(row.status)) continue;
      this.deps.logs.removeLogs(row); this.deps.output.clear(row.id); this.deps.registry.delete(row.id);
      this.tickets.delete(row.id); this.cursors.delete(row.id); this.canceled.delete(row.id); count++;
      this.jobs.delete(row.id); this.pulls.delete(row.id);
    }
    if (count) this.deps.emit({ type: "processes_changed" });
    return count;
  }
  [Symbol.dispose](): void { this.beginShutdown(); void this.killAll(); }
}
