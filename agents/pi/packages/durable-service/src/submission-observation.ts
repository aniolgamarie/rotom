// 纯原提交内容观察：不查询、推进、授权或允许重提，不返回正文。
import { types } from "node:util";

const MAX_BYTES = 1024 * 1024, MAX_NODES = 16384, MAX_DEPTH = 64;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const ownErrors = new WeakSet();
function fail(code = "submission-observation-invalid") {
  const error = new Error(code);
  Object.defineProperty(error, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  ownErrors.add(error); throw error;
}
function require(value) { if (!value) fail(); }
function conflict() { fail("submission-input-conflict"); }
function unicode(value) {
  require(typeof value === "string");
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(++index); require(next >= 0xdc00 && next <= 0xdfff); }
    else require(code < 0xdc00 || code > 0xdfff);
  }
  return value;
}
function cloneInputs(expected, observed) {
  let bytes = 0, nodes = 0; const active = new Set();
  function add(count) { bytes += count; require(bytes <= MAX_BYTES); }
  function quoted(value) {
    require(typeof value === "string" && value.length + 2 <= MAX_BYTES - bytes);
    require(Buffer.byteLength(value, "utf8") + 2 <= MAX_BYTES - bytes); unicode(value); add(2);
    for (let index = 0; index < value.length; index++) {
      const code = value.charCodeAt(index);
      if (code < 32) add([8, 9, 10, 12, 13].includes(code) ? 2 : 6);
      else if (code === 34 || code === 92) add(2);
      else if (code < 128) add(1);
      else if (code < 2048) add(2);
      else if (code >= 0xd800 && code <= 0xdbff) { index++; add(4); }
      else add(3);
    }
  }
  function copy(value, depth) {
    require(++nodes <= MAX_NODES && depth <= MAX_DEPTH);
    if (value === null) { add(4); return value; }
    if (typeof value === "string") { quoted(value); return value; }
    if (typeof value === "boolean") { add(value ? 4 : 5); return value; }
    if (typeof value === "number") { require(Number.isFinite(value)); add(JSON.stringify(value).length); return value === 0 ? 0 : value; }
    require(value && typeof value === "object" && !types.isProxy(value));
    const array = Array.isArray(value), prototype = Object.getPrototypeOf(value);
    require(array ? prototype === Array.prototype : prototype === Object.prototype || prototype === null);
    require(!active.has(value)); active.add(value);
    try {
      const keys = Reflect.ownKeys(value); require(keys.every(key => typeof key === "string" && key !== "toJSON"));
      add(2);
      if (array) {
        const length = Object.getOwnPropertyDescriptor(value, "length").value; require(length <= MAX_NODES - nodes && keys.length === length + 1);
        const result = [];
        for (let index = 0; index < length; index++) {
          const descriptor = Object.getOwnPropertyDescriptor(value, String(index)); require(descriptor?.enumerable && Object.hasOwn(descriptor, "value"));
          if (index) add(1); result.push(copy(descriptor.value, depth + 1));
        }
        return result;
      }
      require(keys.length <= MAX_NODES - nodes); const result = Object.create(null);
      for (let index = 0; index < keys.length; index++) {
        const key = keys[index], descriptor = Object.getOwnPropertyDescriptor(value, key); require(descriptor?.enumerable && Object.hasOwn(descriptor, "value"));
        if (index) add(1); quoted(key); add(1); result[key] = copy(descriptor.value, depth + 1);
      }
      return result;
    } finally { active.delete(value); }
  }
  return [copy(expected, 0), copy(observed, 0)];
}
function shape(value, allowed, required = allowed) {
  require(value && typeof value === "object" && !Array.isArray(value));
  const keys = Object.keys(value); require(keys.every(key => allowed.includes(key)) && required.every(key => Object.hasOwn(value, key))); return value;
}
function nativeId(value) { require(Number.isSafeInteger(value) && value > 0); }
function expectedInput(value) {
  shape(value, ["childConversationId", "requestKey", "submissionId", "text", "whenBusy"]);
  nativeId(value.childConversationId); require(typeof value.requestKey === "string" && ID.test(value.requestKey));
  if (value.submissionId !== null) nativeId(value.submissionId);
  require(typeof value.text === "string" && Buffer.byteLength(value.text, "utf8") <= 65536);
  require(["steer", "followUp", "reject"].includes(value.whenBusy)); return value;
}
function submission(value) {
  if (value === null) return null;
  const base = ["id", "conversationId", "requestId", "type", "status"];
  shape(value, [...base, "entry", "answer", "reason", "detail"], ["id", "conversationId", "type", "status"]);
  nativeId(value.id); nativeId(value.conversationId); require(["input", "write"].includes(value.type));
  if (Object.hasOwn(value, "requestId")) require(typeof value.requestId === "string");
  require(["queued", "placed", "done", "unanswered"].includes(value.status));
  let allowed = [...base];
  if (value.status === "placed") { require(value.type === "input"); allowed.push("entry"); nativeId(value.entry); }
  if (value.status === "done") { allowed.push("entry"); nativeId(value.entry); if (value.type === "input") { allowed.push("answer"); nativeId(value.answer); } }
  if (value.status === "unanswered") {
    allowed.push("reason", "detail"); require(typeof value.reason === "string" && value.reason.length > 0 && Buffer.byteLength(value.reason, "utf8") <= 4096);
    if (value.type === "input") { allowed.push("entry"); if (Object.hasOwn(value, "entry")) nativeId(value.entry); }
  }
  shape(value, allowed, ["id", "conversationId", "type", "status"]); return value;
}
function userInput(value) {
  if (typeof value === "string") return;
  require(Array.isArray(value));
  // 固定pi-ai公开UserInput形状；不转换块数组，不解释签名或解码图片。
  for (const block of value) {
    shape(block, ["type", "text", "textSignature", "data", "mimeType"], ["type"]);
    if (block.type === "text") {
      shape(block, ["type", "text", "textSignature"], ["type", "text"]);
      require(typeof block.text === "string");
      if (Object.hasOwn(block, "textSignature")) require(typeof block.textSignature === "string");
    } else {
      require(block.type === "image"); shape(block, ["type", "data", "mimeType"]);
      require(typeof block.data === "string" && typeof block.mimeType === "string");
    }
  }
}
function inbox(value) {
  if (value === null) return null;
  shape(value, ["items"]); require(Array.isArray(value.items) && value.items.length <= 4096); const ids = new Set();
  for (const item of value.items) {
    shape(item, ["id", "mode", "content", "entry"], ["id", "mode"]); nativeId(item.id); require(!ids.has(item.id)); ids.add(item.id);
    require(["steer", "followUp", "write"].includes(item.mode));
    if (item.mode === "write") { shape(item, ["id", "mode", "entry"]); require(item.entry && typeof item.entry === "object" && !Array.isArray(item.entry)); }
    else { shape(item, ["id", "mode", "content"]); userInput(item.content); }
  }
  return value;
}
function entry(value) {
  if (value === null) return null;
  shape(value, ["id", "conversationId", "kind", "model", "byTaskId"], ["id", "conversationId", "kind", "model"]);
  nativeId(value.id); nativeId(value.conversationId); require(typeof value.kind === "string" && value.kind.length > 0);
  if (Object.hasOwn(value, "byTaskId")) nativeId(value.byTaskId);
  require(Array.isArray(value.model) && value.model.length === 1); const message = shape(value.model[0], ["role", "content", "timestamp"]);
  require(typeof message.role === "string" && message.role.length > 0 && typeof message.timestamp === "number" && Number.isFinite(message.timestamp) && message.timestamp >= 0);
  userInput(message.content);
  return value;
}
function result(record, binding, reason) {
  return Object.freeze({ schema: 1, binding, reason, nativeStatus: record?.status ?? null, nativeSubmissionId: record?.id ?? null,
    inputEntryId: record && Object.hasOwn(record, "entry") ? record.entry : null, answerEntryId: record && Object.hasOwn(record, "answer") ? record.answer : null,
    originalEnvelopeVerified: false, authorityVerified: false, mayResubmit: false });
}
export function captureDurableSubmissionObservation(expected, observed) {
  try {
    require(arguments.length === 2);
    const [copiedExpected, copiedObserved] = cloneInputs(expected, observed), required = expectedInput(copiedExpected);
    const values = shape(copiedObserved, ["submission", "inbox", "entry"]), record = submission(values.submission), queued = inbox(values.inbox), original = entry(values.entry);
    // 所有结构先校验；任何 match 仍不证明原 envelope 或权限。
    if (original && (original.kind !== "pi.user" || original.model[0].role !== "user")) conflict();
    if (!record) return result(null, "unavailable", "record-missing");
    if (record.type !== "input" || record.conversationId !== required.childConversationId || record.requestId !== required.requestKey || required.submissionId !== null && record.id !== required.submissionId) conflict();
    if (record.status === "queued") {
      if (!queued) return result(record, "unavailable", "inbox-unavailable");
      const item = queued.items.find(item => item.id === record.id);
      if (!item) return result(record, "unavailable", "queued-item-missing");
      if (item.mode !== (required.whenBusy === "steer" ? "steer" : "followUp") || typeof item.content !== "string" || item.content !== required.text) conflict();
      return result(record, "matched", "content-matched");
    }
    if (!Object.hasOwn(record, "entry")) return result(record, "unavailable", "input-not-retained");
    if (!original) return result(record, "unavailable", "entry-unavailable");
    if (original.id !== record.entry || original.conversationId !== required.childConversationId || typeof original.model[0].content !== "string" || original.model[0].content !== required.text) conflict();
    return result(record, "matched", "content-matched");
  } catch (error) {
    if (ownErrors.has(error)) throw error;
    fail();
  }
}
