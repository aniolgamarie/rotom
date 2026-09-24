// 复用普通命令的唯一 manager/监督生命周期；ready 只触发核验，不代表工具成功。
import { createHash, randomUUID } from "node:crypto";
import { SupervisedStdioTransport } from "./supervised-stdio.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { closed, reject } from "./managed-types.ts";

export const readseekToolNames = new Set(["edit", "grep", "search", "refs", "rename", "def", "digest", "view", "write"].map(name => "readSeek_" + name));
class ReadseekTransport extends SupervisedStdioTransport {
  constructor(runtime, admission) { super(runtime, "readseek", { errorPrefix: "READSEEK" }); this.admission = admission; }
  binding() {
    requireOrdinaryHelper(this.runtime, "pi-readseek", this.ticket?.manager_run_id ?? null);
    if (!this.runtime.manifest.options.readseek?.node_tool_ref) reject("READSEEK_NODE_UNBOUND", 2);
    return {};
  }
  async prepare() {
    this.binding();
    this.ticket = await this.runtime.supervisor.call("ordinary_readseek_stage", { operation_id: this.admission.operation_id });
    this.binding();
    return this.ticket;
  }
}

export class ReadseekController {
  constructor(runtime, { installed = false, transportFactory = (runtime, ticket) => new ReadseekTransport(runtime, ticket) } = {}) {
    this.runtime = runtime; this.installed = installed; this.transportFactory = transportFactory;
  }
  availability() {
    try { requireOrdinaryHelper(this.runtime, "pi-readseek"); }
    catch (error) {
      if (["CAPABILITY_MISSING", "CAPABILITY_NOT_SELECTED", "UNBOUND_MODEL", "UNMETERED_PARENT_HELPER"].includes(error.message)) {
        return { available: false, reason: error.message };
      }
      throw error;
    }
    return this.installed && this.runtime.manifest.options.readseek?.node_tool_ref
      ? { available: true } : { available: false, reason: "READSEEK_EXECUTOR_UNAVAILABLE" };
  }
  async prepare(event, ctx, roleId) {
    requireOrdinaryHelper(this.runtime, "pi-readseek");
    if (roleId !== "main" || !readseekToolNames.has(event.toolName)) reject("ROLE_CEILING", 4);
    if (!this.availability().available) reject("READSEEK_EXECUTOR_UNAVAILABLE", 5);
    const session = ctx?.sessionManager?.getSessionId();
    if (typeof session !== "string" || !session) reject("READSEEK_SESSION_REQUIRED", 4);
    return this.runtime.supervisor.call("ordinary_readseek_prepare", { operation_id: "readseek-" + randomUUID(),
      session_id: session, cwd: ctx.cwd, tool_name: event.toolName, input: event.input });
  }
  async abort(ticket) {
    await this.runtime.ordinaryOperations.abort({ ...ticket, kind: "command" });
    await this.runtime.supervisor.call("ordinary_readseek_discard", { operation_id: ticket.operation_id });
  }
  async execute(name, id, params, signal, _update, ctx) {
    requireOrdinaryHelper(this.runtime, "pi-readseek");
    if (!readseekToolNames.has(name)) reject("READSEEK_TOOL_UNBOUND", 4);
    const ticket = this.runtime.permissionAccess.take(id, name, params, ctx);
    if (ticket.kind !== "readseek") reject("READSEEK_ADMISSION_INVALID", 4);
    const transport = this.transportFactory(this.runtime, ticket);
    let ready, failed, seen = false, accepted = false, error = null;
    const completion = new Promise((resolve, reject) => { ready = resolve; failed = reject; });
    // start 也可能先于等待 completion 报错，避免产生未处理 rejection。
    void completion.catch(() => {});
    const fail = failure => { error ??= failure; failed(error); };
    transport.onmessage = message => {
      if (seen) { fail(new Error("READSEEK_DUPLICATE_RESULT")); return; }
      seen = true;
      void (async () => {
        closed(message, ["jsonrpc", "type", "operation_id", "sha256", "bytes"]);
        if (message.jsonrpc !== "2.0" || message.type !== "ready" || message.operation_id !== ticket.operation_id
            || typeof message.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(message.sha256)
            || !Number.isSafeInteger(message.bytes) || message.bytes < 1 || message.bytes > 32 * 1024 * 1024) reject("READSEEK_ARTIFACT_INVALID", 4);
        signal?.throwIfAborted();
        const reply = await this.runtime.supervisor.call("ordinary_readseek_accept", {
          operation_id: ticket.operation_id, sha256: message.sha256, bytes: message.bytes });
        if (reply.accepted !== true || reply.operation_id !== ticket.operation_id) reject("READSEEK_ACCEPTANCE_UNKNOWN", 4);
        signal?.throwIfAborted();
        if (error) throw error;
        accepted = true;
        await transport.send({ jsonrpc: "2.0", type: "accepted", operation_id: ticket.operation_id });
        ready();
      })().catch(fail);
    };
    transport.onerror = () => fail(new Error("READSEEK_PROCESS_FAILED"));
    transport.onclose = () => { if (!accepted) fail(new Error("READSEEK_RESULT_MISSING")); };
    const abort = () => {
      fail(new Error("READSEEK_CANCELED"));
      void transport.close().catch(fail);
    };
    signal?.addEventListener("abort", abort, { once: true });
    try {
      signal?.throwIfAborted();
      await transport.start();
      await completion;
      await transport.job;
      signal?.throwIfAborted();
      if (error) throw error;
      const summary = await this.runtime.supervisor.call("ordinary_readseek_finalize", { operation_id: ticket.operation_id });
      if (summary.operation_id !== ticket.operation_id || summary.termination_confirmed !== true
          || !Number.isSafeInteger(summary.bytes) || summary.bytes < 1 || summary.bytes > 32 * 1024 * 1024
          || typeof summary.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(summary.sha256)) reject("READSEEK_RESULT_UNVERIFIED", 4);
      const chunks = []; let offset = 0;
      while (offset < summary.bytes) {
        signal?.throwIfAborted();
        const reply = await this.runtime.supervisor.call("ordinary_readseek_result", { operation_id: ticket.operation_id, offset, limit: 65536 });
        if (reply.offset !== offset || reply.bytes !== summary.bytes || reply.sha256 !== summary.sha256 || typeof reply.data_b64 !== "string") reject("READSEEK_RESULT_CHANGED", 4);
        const bytes = Buffer.from(reply.data_b64, "base64");
        if (bytes.toString("base64") !== reply.data_b64 || !bytes.length || bytes.length > Math.min(65536, summary.bytes - offset)) reject("READSEEK_RESULT_CHANGED", 4);
        chunks.push(bytes); offset += bytes.length;
      }
      const bytes = Buffer.concat(chunks);
      if (createHash("sha256").update(bytes).digest("hex") !== summary.sha256) reject("READSEEK_RESULT_CHANGED", 4);
      return JSON.parse(new TextDecoder("utf8", { fatal: true }).decode(bytes));
    } finally {
      signal?.removeEventListener("abort", abort);
      // 关闭未知必须上抛并保留 manager/租约；不得当作已经释放。
      await transport.close();
      await this.abort(ticket);
    }
  }
}
