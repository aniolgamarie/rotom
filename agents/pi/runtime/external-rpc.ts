// 一个外部委托通道对应已存在的唯一管理者；重复监听者拒绝所有操作。
import { randomUUID } from "node:crypto";
import { clone, closed, isProtocolError, ProtocolError, reject, text } from "./managed-types.ts";
const prefix = "agentcfg:subagents:external:v2:";
const methods = {
  submit_delegate: ["request_id", "idempotency_key", "instance_id", "policy_digest", "request_digest", "backend_request"],
  get_delegate_result: ["owner", "run_id"], cancel_delegate: ["owner", "run_id"], submit_batch: ["owner", "batch_id", "items"],
};
function count(events) {
  const id = randomUUID(); let total = 0;
  const off = events.on(prefix + "probe:" + id, () => { total++; });
  try { events.emit(prefix + "probe", { request_id: id }); } finally { off(); }
  return total;
}
export function registerExternalRpc(events, bridge) {
  if (count(events)) reject("MANAGER_LISTENER_CONFLICT", 5);
  const off = [events.on(prefix + "probe", value => {
    try { closed(value, ["request_id"]); if (!text(value.request_id)) reject(); }
    catch { return; }
    events.emit(prefix + "probe:" + value.request_id, { schema_version: 2 });
  })];
  for (const [method, fields] of Object.entries(methods)) off.push(events.on(prefix + method, async envelope => {
    let id;
    try {
      closed(envelope, ["request_id", "args"]); if (!text(envelope.request_id)) reject(); id = envelope.request_id;
      closed(envelope.args, fields);
      if (count(events) !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
      const args = envelope.args;
      const result = method === "submit_delegate" ? await bridge.submit_delegate(args)
        : method === "submit_batch" ? await bridge.submit_batch(args.owner, args.batch_id, args.items)
        : await bridge[method](args.owner, args.run_id);
      events.emit(prefix + "reply:" + id, { ok: true, result });
    } catch (error) {
      if (id) events.emit(prefix + "reply:" + id, { ok: false, error: isProtocolError(error) ? error.code : "DELEGATE_OPERATION_FAILED",
        exit_code: isProtocolError(error) ? error.exitCode : 6 });
    }
  }));
  return () => { for (const close of off) close(); };
}
export class ExternalClient {
  constructor(events, { timeout = 30000 } = {}) {
    if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 30000) reject();
    this.events = events; this.timeout = timeout;
  }
  call(method, args) {
    if (!Object.hasOwn(methods, method)) reject();
    closed(args, methods[method]); if (count(this.events) !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
    const id = randomUUID();
    return new Promise((resolve, fail) => {
      let replies = 0;
      const off = this.events.on(prefix + "reply:" + id, value => {
        if (++replies !== 1) { fail(new ProtocolError("MANAGER_LISTENER_CONFLICT", 5)); return; }
        queueMicrotask(() => {
          clearTimeout(timer); off();
          try {
            if (count(this.events) !== 1 || replies !== 1) reject("MANAGER_LISTENER_CONFLICT", 5);
            if (value?.ok === true) { closed(value, ["ok", "result"]); resolve(clone(value.result)); }
            else { closed(value, ["ok", "error", "exit_code"]);
              if (!text(value.error) || ![2, 3, 4, 5, 6].includes(value.exit_code)) reject();
              fail(new ProtocolError(value.error, value.exit_code)); }
          } catch (error) { fail(error); }
        });
      });
      const timer = setTimeout(() => { off(); fail(new ProtocolError(method.startsWith("submit_") ? "START_UNKNOWN" : "DELEGATE_RESPONSE_MISSING", 4)); }, this.timeout);
      try { this.events.emit(prefix + method, { request_id: id, args: clone(args) }); }
      catch { clearTimeout(timer); off(); fail(new ProtocolError("START_UNKNOWN", 4)); }
    });
  }
}
