// 通道只提供封闭协议；未知方法、多个监听者或丢失响应都不能重发执行。
import { randomUUID } from "node:crypto";
import { closed, clone, isProtocolError, ProtocolError, reject, text } from "./managed-types.ts";
const prefix = "agentcfg:subagents:managed:";
const operations = {
  handshake: ["protocol_version", "instance_id", "request_id"],
  preflight: ["descriptor"], dispatch: ["descriptor", "admission_token", "idempotency_key"],
  inspect: ["owner", "manager_run_id"], get_result: ["owner", "attempt_id"],
  cancel: ["owner", "attempt_id", "reason"], reconcile: ["owner", "lease_id"],
  consume: ["owner", "receipt_id", "receipt_digest"],
};

export function listenerCount(events) {
  const id = randomUUID(), replies = [];
  const off = events.on(prefix + "probe:" + id, value => { replies.push(value); });
  try { events.emit(prefix + "probe", { request_id: id }); } finally { off(); }
  return replies.length;
}
export function registerManagedRpc(events, bridge) {
  if (listenerCount(events) !== 0) reject("MANAGER_LISTENER_CONFLICT", 5);
  const off = [];
  off.push(events.on(prefix + "probe", value => {
    try { closed(value, ["request_id"]); if (!text(value.request_id)) reject(); }
    catch { return; }
    events.emit(prefix + "probe:" + value.request_id, { protocol_version: 1 });
  }));
  for (const [method, fields] of Object.entries(operations)) {
    off.push(events.on(prefix + method, async envelope => {
      let replyId;
      try {
        closed(envelope, ["request_id", "args"]);
        if (!text(envelope.request_id)) reject();
        replyId = envelope.request_id;
        closed(envelope.args, fields);
        if (listenerCount(events) !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
        const args = envelope.args;
        let value;
        if (method === "handshake" || method === "dispatch") value = await bridge[method](args);
        else if (method === "preflight") value = await bridge.preflight(args.descriptor);
        else if (method === "inspect") value = await bridge.inspect(args.owner, args.manager_run_id);
        else if (method === "get_result") value = await bridge.get_result(args.owner, args.attempt_id);
        else if (method === "cancel") value = await bridge.cancelAttempt(args.owner, args.attempt_id, args.reason);
        else if (method === "reconcile") value = await bridge.reconcile(args.owner, args.lease_id);
        else value = await bridge.consume(args.owner, args.receipt_id, args.receipt_digest);
        events.emit(prefix + "reply:" + replyId, { ok: true, result: value });
      } catch (error) {
        if (replyId) events.emit(prefix + "reply:" + replyId, { ok: false,
          error: isProtocolError(error) ? error.code : "MANAGED_OPERATION_FAILED",
          exit_code: isProtocolError(error) ? error.exitCode : 6 });
      }
    }));
  }
  return () => { for (const unsubscribe of off) unsubscribe(); };
}

export class ManagedClient {
  constructor(events, { timeout = 30000 } = {}) {
    if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 30000) reject();
    this.events = events; this.timeout = timeout;
  }
  async call(method, args) {
    if (!Object.hasOwn(operations, method)) reject();
    closed(args, operations[method]);
    if (listenerCount(this.events) !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
    const request_id = randomUUID();
    return new Promise((resolve, rejectReply) => {
      let replied = false;
      const off = this.events.on(prefix + "reply:" + request_id, response => {
        // 多响应先于 microtask 被发现；不从第一份响应推断唯一管理者。
        if (replied) { rejectReply(new ProtocolError("MANAGER_LISTENER_CONFLICT", 5)); return; }
        replied = true;
        queueMicrotask(() => {
          clearTimeout(timer); off();
          try {
            if (listenerCount(this.events) !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
            if (response?.ok === true) { closed(response, ["ok", "result"]); resolve(clone(response.result)); }
            else {
              closed(response, ["ok", "error", "exit_code"]);
              if (response.ok !== false || !text(response.error) || ![2, 3, 4, 5, 6].includes(response.exit_code)) reject();
              rejectReply(new ProtocolError(response.error, response.exit_code));
            }
          } catch (error) { rejectReply(error); }
        });
      });
      const timer = setTimeout(() => { off(); rejectReply(new ProtocolError(method === "dispatch" ? "START_UNKNOWN" : "MANAGED_RESPONSE_MISSING", 4)); }, this.timeout);
      try { this.events.emit(prefix + method, { request_id, args: clone(args) }); }
      catch { clearTimeout(timer); off(); rejectReply(new ProtocolError(method === "dispatch" ? "START_UNKNOWN" : "MANAGED_RESPONSE_MISSING", 4)); }
    });
  }
}
