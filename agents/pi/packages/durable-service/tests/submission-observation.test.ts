import assert from "node:assert/strict";
import { test } from "node:test";
import { captureDurableSubmissionObservation as capture } from "../src/submission-observation.ts";

const secret = "SYNTHETIC_PRIVATE full body auth path error";
const expected = extra => ({ childConversationId: 9, requestKey: "root-request:1", submissionId: 4, text: secret, whenBusy: "followUp", ...extra });
function fixture(status = "queued") {
  const submission = { id: 4, conversationId: 9, requestId: "root-request:1", type: "input", status };
  if (status !== "queued") submission.entry = 5;
  if (status === "done") submission.answer = 6;
  if (status === "unanswered") { submission.reason = secret; submission.detail = { metadata: secret }; }
  const inbox = { items: [{ id: 4, mode: "followUp", content: secret }] };
  const entry = { id: 5, conversationId: 9, kind: "pi.user", model: [{ role: "user", content: secret, timestamp: 1 }] };
  return { submission, inbox, entry };
}
const fixed = code => error => { assert.equal(error.code, code); assert.equal(error.message, code); assert.equal(error.cause, undefined); assert(!error.stack.includes(secret)); return true; };
const invalid = fixed("submission-observation-invalid"), conflict = fixed("submission-input-conflict");
function restricted(result) {
  assert(Object.isFrozen(result)); assert.deepEqual(Object.keys(result).sort(), ["schema", "binding", "reason", "nativeStatus", "nativeSubmissionId", "inputEntryId", "answerEntryId", "originalEnvelopeVerified", "authorityVerified", "mayResubmit"].sort());
  assert.equal(result.originalEnvelopeVerified, false); assert.equal(result.authorityVerified, false); assert.equal(result.mayResubmit, false); assert(!JSON.stringify(result).includes(secret));
}
for (const status of ["queued", "placed", "done", "unanswered"]) test(`complete original ${status} matches content without granting envelope/authority/retry`, () => {
  const original = fixture(status), want = expected(), saved = structuredClone([want, original]); const result = capture(want, original);
  restricted(result); assert.equal(result.binding, "matched"); assert.equal(result.reason, "content-matched"); assert.equal(result.nativeStatus, status); assert.equal(result.nativeSubmissionId, 4); assert.equal(result.inputEntryId, status === "queued" ? null : 5); assert.equal(result.answerEntryId, status === "done" ? 6 : null);
  assert.deepEqual([want, original], saved); assert(!Object.isFrozen(want)); assert(!Object.isFrozen(original)); assert(!Object.isFrozen(original.entry.model));
});
test("unknown SubID can bind observed precise ID but no record even known ID is unavailable", () => {
  const result = capture(expected({ submissionId: null }), fixture()); assert.equal(result.nativeSubmissionId, 4); restricted(result);
  const missing = capture(expected(), { submission: null, inbox: null, entry: null }); restricted(missing); assert.equal(missing.reason, "record-missing"); assert.equal(missing.nativeStatus, null); assert.equal(missing.nativeSubmissionId, null);
});
for (const [change, reason] of [[value => value.inbox = null, "inbox-unavailable"], [value => value.inbox.items = [], "queued-item-missing"]]) test(`queued observation missing ${reason} never filled by supplied Entry`, () => {
  const value = fixture(); change(value); const result = capture(expected(), value); restricted(result); assert.equal(result.binding, "unavailable"); assert.equal(result.reason, reason);
});
for (const status of ["placed", "done", "unanswered"]) test(`missing ${status} original input Entry is unavailable not answer inference`, () => {
  const value = fixture(status); value.entry = null; const result = capture(expected(), value); restricted(result); assert.equal(result.reason, "entry-unavailable"); assert.equal(result.inputEntryId, 5);
});
test("unanswered no original entry never restores text from reason/detail or irrelevant inbox/Entry", () => {
  const value = fixture("unanswered"); delete value.submission.entry; const result = capture(expected(), value); restricted(result); assert.equal(result.reason, "input-not-retained"); assert.equal(result.inputEntryId, null);
});
for (const whenBusy of ["steer", "followUp", "reject"]) test(`queued mode ${whenBusy} checks normalized SDK mode only`, () => {
  const value = fixture(); value.inbox.items[0].mode = whenBusy === "steer" ? "steer" : "followUp";
  const result = capture(expected({ whenBusy }), value); assert.equal(result.binding, "matched"); restricted(result);
});
for (const change of [v => v.submission.id++, v => v.submission.conversationId++, v => v.submission.requestId = "other", v => delete v.submission.requestId, v => v.inbox.items[0].content += "changed", v => v.inbox.items[0].mode = "steer", v => v.inbox.items[0] = { id: 4, mode: "write", entry: {} }]) test(`legal record relation conflicts ${change.toString()}`, () => {
  const value = fixture(); change(value); assert.throws(() => capture(expected(), value), conflict);
});
for (const change of [v => v.entry.id = 6, v => v.entry.conversationId++, v => v.entry.kind = "pi.assistant", v => v.entry.model[0].role = "assistant", v => v.entry.model[0].content += "changed", v => v.entry.model[0].content = [{ type: "text", text: secret }]]) test(`Entry/body type relation conflicts ${change.toString()}`, () => {
  const value = fixture("done"); change(value); assert.throws(() => capture(expected(), value), conflict);
});
test("native string versus text block array never equivalent and byTask does not assert Root ancestry", () => {
  const value = fixture(); value.inbox.items[0].content = [{ type: "text", text: secret }]; assert.throws(() => capture(expected(), value), conflict);
  const placed = fixture("placed"); placed.entry.byTaskId = 987; const result = capture(expected(), placed); assert.equal(result.binding, "matched"); restricted(result);
});
for (const status of ["queued", "done", "unanswered"]) test(`legal SDK write record ${status} conflicts without being matched`, () => {
  const value = fixture(status); value.submission.type = "write"; if (status === "done") delete value.submission.answer; if (status === "unanswered") delete value.submission.entry;
  assert.throws(() => capture(expected(), value), conflict);
});
for (const change of [v => v.submission.extra = true, v => v.submission.status = "unknown", v => v.submission.type = "other", v => v.submission.entry = 5, v => v.submission.id = true, v => v.submission.id = 2**60, v => v.submission.id = 0, v => v.submission.requestId = null, v => v.entry.model.push(v.entry.model[0]), v => v.entry.model[0].timestamp = -1, v => v.entry.model[0].timestamp = NaN, v => v.entry.byTaskId = false, v => v.entry.data = {}, v => v.inbox.extra = 1, v => v.inbox.items[0].mode = "other", v => v.inbox.items[0].extra = 1]) test(`invalid structure before relation ${change.toString()}`, () => {
  const value = fixture(); change(value); assert.throws(() => capture(expected(), value), invalid);
});
test("per-state missing/extra fields and reason bound are strict", () => {
  for (const [status, change] of [["placed", s => delete s.entry], ["done", s => delete s.answer], ["unanswered", s => delete s.reason], ["unanswered", s => s.reason = ""], ["unanswered", s => s.reason = "x".repeat(4097)], ["queued", s => s.answer = 6], ["placed", s => s.detail = {}], ["unanswered", s => s.answer = 6], ["placed", s => s.type = "write"]]) {
    const value = fixture(status); change(value.submission); assert.throws(() => capture(expected(), value), invalid);
  }
  const value = fixture("unanswered"); value.submission.reason = "\0"; restricted(capture(expected(), value));
});
test("duplicate Inbox IDs including identical target and unrelated write conflict structurally", () => {
  for (const item of [{ id: 4, mode: "followUp", content: secret }, { id: 4, mode: "write", entry: {} }]) {
    const value = fixture(); value.inbox.items.push(item); assert.throws(() => capture(expected(), value), invalid);
  }
});
test("unused Inbox and Entry are still complete narrow/safe observations", () => {
  const value = fixture("placed"); value.inbox.items.push({ id: 4, mode: "write", entry: {} }); assert.throws(() => capture(expected(), value), invalid);
  const missing = { submission: null, inbox: null, entry: fixture().entry }; missing.entry.kind = "pi.assistant"; assert.throws(() => capture(expected(), missing), conflict);
  const queued = fixture(); queued.entry.id = 555; queued.entry.conversationId = 999; assert.equal(capture(expected(), queued).binding, "matched");
});
test("plain/null prototype and key ordering share full value meaning; frozen source remains unchanged", () => {
  const value = fixture("done"), want = expected();
  function copy(input) { if (Array.isArray(input)) return input.map(copy); if (input && typeof input === "object") { const result = Object.create(null); for (const key of Object.keys(input).reverse()) result[key] = copy(input[key]); return result; } return input; }
  assert.deepEqual(capture(copy(want), copy(value)), capture(want, value));
  Object.freeze(want); Object.freeze(value); const result = capture(want, value); restricted(result);
});
test("Proxy/revoked Proxy rejected before traps, accessors/toJSON/then never invoked", () => {
  let calls = 0; const proxy = new Proxy(fixture(), { get() { calls++; throw Error(secret); }, ownKeys() { calls++; throw Error(secret); }, getPrototypeOf() { calls++; throw Error(secret); } });
  assert.throws(() => capture(expected(), proxy), invalid); const revoked = Proxy.revocable({}, {}); revoked.revoke(); assert.throws(() => capture(revoked.proxy, fixture()), invalid);
  for (const make of [() => ({ get submission() { calls++; throw Error(secret); }, inbox: null, entry: null }), () => ({ ...fixture(), toJSON() { calls++; return {}; } }), () => ({ ...fixture(), extra: { get then() { calls++; throw Error(secret); } } })]) assert.throws(() => capture(expected(), make()), invalid);
  assert.equal(calls, 0);
});
test("nonJSON/symbol/inherited/holes/subclass/cycle reject with fixed nonsecret errors", () => {
  const cycle = {}; cycle.self = cycle; const sparse = [1, , 3];
  for (const detail of [undefined, 1n, () => {}, Infinity, Symbol("secret"), new Date(), new (class Value {})(), cycle, sparse]) {
    const value = fixture("unanswered"); value.submission.detail = detail; assert.throws(() => capture(expected(), value), invalid);
  }
  const value = fixture(); value.inbox[Symbol("extra")] = true; assert.throws(() => capture(expected(), value), invalid);
  assert.throws(() => capture(Object.create(expected()), fixture()), invalid);
  const hidden = fixture(); Object.defineProperty(hidden.entry, "hidden", { value: true }); assert.throws(() => capture(expected(), hidden), invalid);
});
for (const mutate of [v => v.text = "\ud800", v => v.text = "x".repeat(65537), v => v.requestKey = "bad key", v => v.requestKey = "x".repeat(201), v => v.childConversationId = false, v => v.submissionId = undefined, v => v.whenBusy = "other", v => v.extra = true]) test(`closed expected input ${mutate.toString()}`, () => {
  const value = expected(); mutate(value); assert.throws(() => capture(value, fixture()), invalid);
});
test("Unicode invalid in any ignored metadata also rejects and safe whitespace/empty text is exact", () => {
  const value = fixture("unanswered"); value.submission.detail = { "\ud800": "bad" }; assert.throws(() => capture(expected(), value), invalid);
  const empty = fixture(); empty.inbox.items[0].content = ""; const result = capture(expected({ text: "" }), empty); assert.equal(result.binding, "matched"); restricted(result);
  const spaces = fixture(); spaces.inbox.items[0].content = "  x\n"; assert.throws(() => capture(expected({ text: "x" }), spaces), conflict);
});
test("Inbox count and cumulative node caps both apply, with no hidden budget override", () => {
  const value = fixture(); value.inbox.items = Array.from({ length: 4000 }, (_, index) => ({ id: index + 1, mode: "followUp", content: secret })); assert.equal(capture(expected(), value).binding, "matched");
  for (const length of [4096, 4097]) { value.inbox.items = Array.from({ length }, (_, index) => ({ id: index + 1, mode: "followUp", content: secret })); assert.throws(() => capture(expected(), value), invalid); }
  assert.throws(() => capture(expected({ maximumBytes: 9999999 }), fixture()), invalid); assert.throws(() => capture(expected(), fixture(), { maximumBytes: 9999999 }), invalid);
});
test("cumulative JSON bytes include separate expected/observed values, UTF8 and escaping", () => {
  const value = fixture("unanswered"); value.submission.detail = "x".repeat(1024 * 1024); assert.throws(() => capture(expected(), value), invalid);
  value.submission.detail = "\u0000".repeat(Math.ceil(1024 * 1024 / 6)); assert.throws(() => capture(expected(), value), invalid);
  value.submission.detail = "😀".repeat(1024 * 1024 / 4); assert.throws(() => capture(expected(), value), invalid);
  value.submission.detail = "x".repeat(500000); restricted(capture(expected(), value));
});
test("global nodes/depth bounded; shared noncycle references copy but cannot hide exponential expansion", () => {
  const value = fixture("unanswered"); value.submission.detail = new Array(16384).fill(null); assert.throws(() => capture(expected(), value), invalid);
  let deep = null; for (let i = 0; i < 65; i++) deep = [deep]; value.submission.detail = deep; assert.throws(() => capture(expected(), value), invalid);
  const shared = { safe: [1, 2] }; value.submission.detail = [shared, shared]; restricted(capture(expected(), value));
  const large = new Array(8192).fill(0); value.submission.detail = [large, large]; assert.throws(() => capture(expected(), value), invalid);
});


test("expected and observed together consume one byte budget even if each separately fits", () => {
  const text = "x".repeat(65536), want = expected({ text }), value = fixture("unanswered");
  value.entry.model[0].content = text; value.inbox.items[0].content = text; value.submission.detail = "x".repeat(900000);
  assert(Buffer.byteLength(JSON.stringify(want), "utf8") < 1024 * 1024); assert(Buffer.byteLength(JSON.stringify(value), "utf8") < 1024 * 1024);
  assert.throws(() => capture(want, value), invalid);
});
test("depth64 accepted while depth65 rejected across observed container path", () => {
  const value = fixture("unanswered"); let detail = null; for (let i = 0; i < 62; i++) detail = [detail]; value.submission.detail = detail;
  restricted(capture(expected(), value)); value.submission.detail = [detail]; assert.throws(() => capture(expected(), value), invalid);
});
test("unrelated Inbox write data is copied safely but never substitutes input", () => {
  const value = fixture(); value.inbox.items.push({ id: 77, mode: "write", entry: { arbitrarySafeJSON: [null, false, "data"] } }); restricted(capture(expected(), value));
  value.inbox.items[1].entry = []; assert.throws(() => capture(expected(), value), invalid);
});

const malformedUserInputs = [null, 7, false, { text: secret }, [0], [{ type: "thinking", thinking: "synthetic" }],
  [{ type: "text", text: 7 }], [{ type: "text", text: secret, extra: true }], [{ type: "text", text: secret, textSignature: 7 }],
  [{ type: "image", data: 7, mimeType: "image/png" }], [{ type: "image", data: "synthetic", mimeType: null }],
  [{ type: "image", data: "synthetic", mimeType: "image/png", extra: true }]];
for (const [index, content] of malformedUserInputs.entries()) for (const where of ["unused-entry", "unrelated-inbox"]) test(`unused UserInput schema ${where} ${index} rejects before selected content matches`, () => {
  const value = fixture(where === "unused-entry" ? "queued" : "placed");
  if (where === "unused-entry") value.entry.model[0].content = content;
  else value.inbox.items.push({ id: 77, mode: "followUp", content });
  assert.throws(() => capture(expected(), value), invalid);
});
for (const where of ["unused-entry", "unrelated-inbox"]) test(`valid native text/image blocks ${where} stay opaque and never replace selected string`, () => {
  const value = fixture(where === "unused-entry" ? "queued" : "placed");
  const content = [{ type: "text", text: secret, textSignature: "synthetic-signature" }, { type: "image", data: "synthetic-data", mimeType: "image/png" }];
  if (where === "unused-entry") value.entry.model[0].content = content;
  else value.inbox.items.push({ id: 77, mode: "followUp", content });
  const saved = structuredClone(value), result = capture(expected(), value);
  restricted(result); assert.equal(result.binding, "matched"); assert.deepEqual(value, saved); assert(!Object.isFrozen(content));
  assert(!JSON.stringify(result).includes("synthetic-signature")); assert(!JSON.stringify(result).includes("synthetic-data"));
});
