// 用户脚本在监督者的无网络私人进程内计算；所有服务调用仍由父侧封闭分派。
import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";
import { BoundStdioTransport } from "./mcp-stdio.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

class ScriptTransport extends BoundStdioTransport {
  constructor(runtime, seconds, options) { super(runtime, "mcp-script", options); this.seconds = seconds; }
  binding() {
    requireOrdinaryHelper(this.runtime, "pi-mcp", this.ticket?.manager_run_id ?? null);
    const selected = this.runtime.manifest.options.mcp?.scripting;
    if (selected?.enabled !== true || !selected.tool_ref || this.seconds > (selected.max_seconds ?? 30)) reject("MCP_SCRIPT_NOT_SELECTED", 2);
    return selected;
  }
  async prepare() {
    this.binding();
    return this.runtime.supervisor.call("ordinary_mcp_script_prepare", { operation_id: "mcp-script-" + randomUUID(), timeout_seconds: this.seconds });
  }
}

export class SupervisedScriptWorker extends EventEmitter {
  constructor(code, timeoutMs, { runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], transportOptions } = {}) {
    super();
    if (typeof code !== "string" || !code.trim() || Buffer.byteLength(code) > 1024 * 1024
        || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1) reject("MCP_SCRIPT_INPUT", 2);
    this.transport = new ScriptTransport(runtime, Math.ceil(timeoutMs / 1000), transportOptions);
    this.transport.binding();
    this.finished = false; this.stopping = false; this.ids = new Set(); this.messages = 0;
    this.transport.onmessage = value => {
      if (this.finished || this.stopping) return;
      if (++this.messages > 4096 || !["call", "search", "describe", "emit", "done", "error"].includes(value.type)) {
        this.emit("error", new Error("MCP_SCRIPT_PROTOCOL")); return;
      }
      if (["call", "search", "describe"].includes(value.type)) {
        if (!Number.isSafeInteger(value.id) || value.id < 1 || this.ids.has(value.id)) {
          this.emit("error", new Error("MCP_SCRIPT_PROTOCOL")); return;
        }
        this.ids.add(value.id);
      }
      if (["done", "error"].includes(value.type)) this.finished = true;
      this.emit("message", value);
    };
    this.transport.onerror = () => { if (!this.stopping) this.emit("error", new Error("MCP_SCRIPT_PROCESS_FAILED")); };
    this.transport.onclose = () => { if (!this.exited) { this.exited = true; this.emit("exit", this.finished ? 0 : 1); } };
    // 调用方先同步安装监听器，下一微任务再准入并发送代码。
    this.startup = Promise.resolve().then(async () => {
      if (this.stopping) return;
      await this.transport.start();
      if (!this.stopping) await this.transport.send({ jsonrpc: "2.0", type: "init", code });
    }).catch(() => { if (!this.stopping) this.emit("error", new Error("MCP_SCRIPT_PROCESS_FAILED")); });
  }
  postMessage(message) {
    if (this.stopping || this.finished) return;
    if (message?.type !== "result" || !this.ids.has(message.id)) reject("MCP_SCRIPT_REPLY_INVALID", 4);
    void this.transport.send({ ...message, jsonrpc: "2.0" }).catch(() => {
      if (!this.stopping) this.emit("error", new Error("MCP_SCRIPT_PROCESS_FAILED"));
    });
  }
  terminate() {
    return this.termination ??= this.stopWorker();
  }
  async stopWorker() {
    this.stopping = true;
    await this.transport.close();
    await this.startup;
    // close 可能先于异步 prepare 返回；此时必须再核实后来取得的租约已经终止。
    if (this.transport.ticket) await this.transport.stop();
    return 0;
  }
}
