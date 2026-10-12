// 仅关联公开 hook 与同一原生 signal；观察不授权、不证明发送或物理终止。
import { types } from "node:util";

const applyOriginal = Reflect.apply;

const signalAborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, "aborted").get;
function failure(code) {
  const error = new Error(code);
  Object.defineProperty(error, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  return error;
}
function publicObject(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw failure("hook-invalid");
  return value;
}
function signal(value) {
  if (!value || typeof value !== "object" || types.isProxy(value) || applyOriginal(signalAborted, value, []) !== false) throw failure("signal-invalid");
  return value;
}
const nativeId = value => Number.isSafeInteger(value) && value > 0;

export function createDurableCallIdentityBridge() {
  if (arguments.length !== 0) throw failure("input-invalid");
  let records = new WeakMap(), retired = false;
  function hook(kind, api, context) {
    try {
      if (retired) throw failure("hook-invalid");
      publicObject(api); publicObject(context);
      // 接口允许公开 getter；只读这三个公共属性，不遍历消息或 SDK 私有对象。
      const nativeTaskId = api.taskId, nativeConversationId = api.conversationId;
      if (!nativeId(nativeTaskId) || !nativeId(nativeConversationId)) throw failure("hook-invalid");
      const currentSignal = signal(context.abortSignal);
      if (retired) throw failure("hook-invalid");
      const previous = records.get(currentSignal);
      if (previous && (previous.retired || previous.pending || previous.identity.nativeTaskId !== nativeTaskId
          || previous.identity.nativeConversationId !== nativeConversationId || previous.identity.call_kind !== kind)) throw failure("hook-invalid");
      records.set(currentSignal, { pending: true, retired: false,
        identity: Object.freeze({ schema: 1, nativeTaskId, nativeConversationId, call_kind: kind }) });
    } catch {
      // SDK 会吞掉普通 hook 异常；全桥退役使 Models 一侧无法消费任何旧登记。
      retired = true;
      throw failure("hook-invalid");
    }
  }
  function take(currentSignal, operation) {
    if (retired) throw failure("bridge-retired");
    const record = records.get(currentSignal);
    try { signal(currentSignal); } catch {
      if (record) { record.retired = true; record.pending = false; }
      throw failure("signal-invalid");
    }
    if (record?.retired) throw failure("identity-retired");
    if (operation === "fetchDeferred" || operation === "cancelDeferred") {
      if (record) { record.retired = true; record.pending = false; }
      throw failure("unsupported");
    }
    if (!record) throw failure("identity-unmatched");
    const expected = record.identity.call_kind === "generation" ? "streamSimple" : "completeSimple";
    if (operation !== expected) {
      record.retired = true; record.pending = false;
      throw failure("operation-invalid");
    }
    if (!record.pending) throw failure("identity-consumed");
    record.pending = false;
    return record.identity;
  }
  function close() {
    retired = true;
    records = new WeakMap();
  }
  function check(currentSignal, operation, identity) {
    if (retired) throw failure("bridge-retired");
    try { signal(currentSignal); } catch { throw failure("signal-invalid"); }
    const record = records.get(currentSignal);
    if (record?.retired) throw failure("identity-retired");
    const expected = record?.identity.call_kind === "generation" ? "streamSimple" : "completeSimple";
    // 消费后的异步等待不能沿用已被新hook覆盖的旧对象；数值相等不代表本次调用仍有效。
    if (!record || record.pending || record.identity !== identity || operation !== expected) throw failure("identity-stale");
    return true;
  }
  const generationHooks = { beforeRequest(_request, api, context) { return hook("generation", api, context); } };
  const compactionHooks = { beforeCompact(_compaction, api, context) { return hook("compaction", api, context); } };
  Object.freeze(generationHooks.beforeRequest);
  Object.freeze(compactionHooks.beforeCompact);
  return Object.freeze({
    generationHooks: Object.freeze(generationHooks),
    compactionHooks: Object.freeze(compactionHooks),
    take, check, close,
  });
}
