// 普通子进程共用监督 stdin/stdout、唯一 manager 和终止证明；协议绑定由子类明确提供。
import { reject } from "./managed-types.ts";

export class SupervisedStdioTransport {
  constructor(runtime, serverName, { pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), pollMilliseconds = 50, errorPrefix = "STDIO" } = {}) {
    this.errorPrefix = errorPrefix + "_";
    this.runtime = runtime; this.serverName = serverName; this.pause = pause; this.pollMilliseconds = pollMilliseconds;
    this.ticket = null; this.started = false; this.closed = false; this.ended = false; this.starting = false;
    this.cursor = 0; this.buffer = ""; this.decoder = new TextDecoder("utf8", { fatal: true }); this.serial = Promise.resolve();
    this.onclose = undefined; this.onerror = undefined; this.onmessage = undefined;
  }
  binding() { reject(this.errorPrefix + "BINDING_REQUIRED", 5); }
  async prepare() { reject(this.errorPrefix + "BINDING_REQUIRED", 5); }
  async start() {
    if (this.starting || this.closed) reject(this.errorPrefix + "TRANSPORT_ALREADY_STARTED", 4);
    this.starting = true;
    this.ticket = await this.prepare();
    if (this.closed) { await this.runtime.ordinaryOperations.abort(this.ticket); reject(this.errorPrefix + "TRANSPORT_CLOSED", 4); }
    let ready, failed;
    const readiness = new Promise((resolve, reject) => { ready = resolve; failed = reject; });
    this.job = this.runtime.ordinaryOperations.write(this.ticket, null, null, undefined, { onStarted: proof => {
      if (this.closed || proof.lease_id !== this.ticket.lease_id || !Number.isSafeInteger(proof.process_identity?.pid) || proof.process_identity.pid <= 0) reject(this.errorPrefix + "START_UNVERIFIED", 4);
      this.started = true; ready();
    } }).then(async result => {
      if (!result.terminationConfirmed || result.truncated || result.exitCode !== 0) reject(this.errorPrefix + "SERVICE_FAILED", 5);
      this.ended = true;
      if (!this.started) failed(new Error(this.errorPrefix + "SERVICE_NOT_STARTED"));
    }).catch(() => {
      this.ended = true; failed(new Error(this.errorPrefix + "SERVICE_FAILED"));
      this.onerror?.(new Error(this.errorPrefix + "SERVICE_FAILED"));
    });
    try {
      await readiness;
      this.polling = this.poll().catch(async () => {
        this.onerror?.(new Error(this.errorPrefix + "OUTPUT_INVALID"));
        await this.close().catch(() => {});
      });
    } catch (error) {
      await this.close().catch(() => {});
      throw error;
    }
  }
  async poll() {
    while (!this.closed) {
      const output = await this.runtime.supervisor.call("ordinary_command_output", { operation_id: this.ticket.operation_id, cursor: this.cursor });
      if (output.dropped || !Number.isSafeInteger(output.next_cursor) || output.next_cursor < this.cursor || !Array.isArray(output.events)) reject(this.errorPrefix + "OUTPUT_LOST", 5);
      for (const event of output.events) {
        if (!["stdout", "stderr"].includes(event.stream)) reject(this.errorPrefix + "OUTPUT_INVALID", 5);
        if (event.stream !== "stdout") continue;
        const bytes = Buffer.from(event.data_b64, "base64");
        if (bytes.toString("base64") !== event.data_b64) reject(this.errorPrefix + "OUTPUT_INVALID", 5);
        this.buffer += this.decoder.decode(bytes, { stream: true });
        if (Buffer.byteLength(this.buffer) > 1024 * 1024) reject(this.errorPrefix + "MESSAGE_OVERSIZE", 5);
        let end;
        while ((end = this.buffer.indexOf("\n")) >= 0) {
          const line = this.buffer.slice(0, end); this.buffer = this.buffer.slice(end + 1);
          if (!line.trim()) continue;
          const message = JSON.parse(line);
          if (!message || typeof message !== "object" || Array.isArray(message) || message.jsonrpc !== "2.0") reject(this.errorPrefix + "MESSAGE_INVALID", 5);
          this.onmessage?.(message);
        }
      }
      this.cursor = output.next_cursor;
      if (output.complete && !output.has_more) {
        this.buffer += this.decoder.decode();
        if (this.buffer.trim()) reject(this.errorPrefix + "MESSAGE_TRUNCATED", 5);
        await this.close(); return;
      }
      if (!output.has_more) await this.pause(this.pollMilliseconds);
    }
  }
  send(message) {
    this.serial = this.serial.then(async () => {
      this.binding();
      if (!this.started || this.closed || this.ended || message?.jsonrpc !== "2.0") reject(this.errorPrefix + "TRANSPORT_CLOSED", 4);
      const data = JSON.stringify(message) + "\n";
      if (Buffer.byteLength(data) > 1024 * 1024) reject(this.errorPrefix + "MESSAGE_OVERSIZE", 2);
      // supervisor 按 PIPE_BUF 原子写入，分块只在已确认接收后推进，保留 UTF-8 字符边界。
      let chunk = "", size = 0;
      const flush = async () => {
        for (let attempt = 0; ; attempt++) {
          if (this.closed) reject(this.errorPrefix + "TRANSPORT_CLOSED", 4);
          try {
            const result = await this.runtime.supervisor.call("ordinary_command_stdin", { operation_id: this.ticket.operation_id, data: chunk, end: false });
            if (result.accepted_bytes !== size || result.stdin_closed) reject(this.errorPrefix + "SEND_UNCONFIRMED", 5);
            break;
          } catch (error) {
            if (error.message !== "ORDINARY_STDIN_BACKPRESSURE" || attempt >= 99) throw error;
            await this.pause(50);
          }
        }
        chunk = ""; size = 0;
      };
      for (const character of data) {
        const length = Buffer.byteLength(character);
        if (size + length > 512) await flush();
        chunk += character; size += length;
      }
      if (chunk) await flush();
    });
    return this.serial;
  }
  async close() {
    if (this.closing) return this.closing;
    this.closed = true;
    this.closing = this.stop();
    return this.closing;
  }
  async stop() {
    if (!this.ticket) { this.onclose?.(); return; }
    let proof = await this.runtime.supervisor.call("reconcile", { lease_id: this.ticket.lease_id });
    if (proof.lease_id !== this.ticket.lease_id) reject(this.errorPrefix + "TERMINATION_UNKNOWN", 4);
    if (proof.protected || !proof.termination_evidence?.verified) {
      const manager = globalThis[Symbol.for("agentcfg.pi.managed.v1")]?.manager;
      if (this.ticket.manager_run_id && manager) await manager.abort(this.ticket.manager_run_id);
      await this.runtime.ordinaryOperations.abort(this.ticket);
      for (let count = 0; count < 100; count++) {
        proof = await this.runtime.supervisor.call("reconcile", { lease_id: this.ticket.lease_id });
        if (proof.lease_id !== this.ticket.lease_id) reject(this.errorPrefix + "TERMINATION_UNKNOWN", 4);
        if (!proof.protected && proof.termination_evidence?.verified) break;
        await this.pause(50);
      }
    }
    if (proof.protected || !proof.termination_evidence?.verified) reject(this.errorPrefix + "TERMINATION_UNKNOWN", 4);
    await this.runtime.supervisor.call("ordinary_command_finish", { operation_id: this.ticket.operation_id });
    this.onclose?.();
  }
}
