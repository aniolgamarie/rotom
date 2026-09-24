// 审查证据记录“读了什么”和“哪次真实请求交付了它”；仅工具完成不能证明模型看到内容。
import { createHash } from "node:crypto";
import { assertProcess, canonical, clone, closed, digest, reject, sha, text } from "./managed-types.ts";
const textDigest = value => createHash("sha256").update(canonical(value)).digest("hex");
function payloadText(value) {
  if (typeof value === "string") return value;
  if (!Array.isArray(value) || value.some(part => part?.type !== "text" || typeof part.text !== "string")) return null;
  return value.map(part => part.text).join("\n");
}
export class ManagedObservation {
  constructor(descriptor, processIdentity) {
    if (processIdentity !== null) assertProcess(processIdentity);
    this.candidateDigest = descriptor.snapshot_digest;
    this.descriptor = descriptor; this.processIdentity = processIdentity;
    this.ordinal = 0; this.reads = []; this.outputs = []; this.errors = []; this.requests = []; this.lastResponse = null; this.denials = [];
  }
  response(record) {
    if (record.phase === "request_denied") {
      this.denials.push({ request_id: record.request_id, code: record.code });
      return;
    }
    if (!["request_committed", "response_headers"].includes(record.phase)) return;
    if (!Number.isSafeInteger(record.ordinal) || record.ordinal < 1) reject("REQUEST_ORDINAL_CONFLICT", 4);
    let existing = this.requests.find(value => value.request_id === record.request_id);
    if (!existing) {
      if (record.ordinal <= this.ordinal) reject("REQUEST_ORDINAL_CONFLICT", 4);
      this.ordinal = record.ordinal;
      existing = { request_id: record.request_id, ordinal: record.ordinal, status: null };
      this.requests.push(existing);
    } else if (existing.ordinal !== record.ordinal) reject("REQUEST_ORDINAL_CONFLICT", 4);
    if (record.phase === "response_headers") {
      existing.status = record.status;
      this.lastResponse = { status: record.status, headers: clone(record.headers ?? {}) };
    }
  }
  tool(name, toolCallId, args, result) {
    if (this.ordinal < 1) reject("TOOL_WITHOUT_MODEL_REQUEST", 4);
    if (name === "tk_read" && result.details?.read) {
      const text = payloadText(result.content);
      if (text === null) reject("READ_PAYLOAD_UNOBSERVED", 5);
      this.reads.push({ ...clone(result.details.read), content_digest: result.details.content_digest,
        tool_call_id: toolCallId, payload_digest: textDigest(text), read_request: this.ordinal, delivered_request: null });
    }
    if (["tk_write", "tk_edit"].includes(name) && result.details?.candidate_digest) this.candidateDigest = result.details.candidate_digest;
    if (name === "structured_output") this.outputs.push({ tool_call_id: toolCallId, request_ordinal: this.ordinal,
      value_digest: digest(args), compatibility_digest: textDigest(args) });
  }
  toolError(name, toolCallId, code) {
    this.errors.push({ tool_name: name, tool_call_id: toolCallId, code: /^[A-Z][A-Z0-9_]+$/.test(code ?? "") ? code : "TOOL_OPERATION_FAILED" });
  }
  delivered({ ordinal, payload }) {
    const messages = payload?.messages;
    if (!Array.isArray(messages)) reject("MODEL_PAYLOAD_UNOBSERVED", 5);
    const visible = new Map();
    for (const message of messages) {
      if (message.role !== "tool" || typeof message.tool_call_id !== "string") continue;
      const text = payloadText(message.content);
      if (text !== null) visible.set(message.tool_call_id, textDigest(text));
    }
    for (const read of this.reads) {
      if (read.read_request < ordinal && visible.get(read.tool_call_id) === read.payload_digest) read.delivered_request ??= ordinal;
    }
  }
  snapshot() {
    return clone({ schema_version: 1, attempt_id: this.descriptor.attempt_id, process_identity: this.processIdentity,
      last_request_ordinal: this.ordinal, reads: this.reads, structured_outputs: this.outputs, tool_errors: this.errors,
      requests: this.requests, request_denials: this.denials, last_response: this.lastResponse });
  }
}

export function assertObservation(value, attemptId, { failed = false } = {}) {
  closed(value, ["schema_version", "attempt_id", "process_identity", "last_request_ordinal", "reads", "structured_outputs", "tool_errors", "requests", "request_denials", "last_response"]);
  if (value.schema_version !== 1 || value.attempt_id !== attemptId || !Number.isSafeInteger(value.last_request_ordinal) || value.last_request_ordinal < (failed ? 0 : 1)
      || ![value.reads, value.structured_outputs, value.tool_errors, value.requests, value.request_denials].every(Array.isArray)) reject("EVIDENCE_IDENTITY", 4);
  assertProcess(value.process_identity);
  for (const read of value.reads) {
    closed(read, ["kind", "artifact_id", "root_ref", "path", "first_line", "last_line", "start", "end", "total", "content_digest", "tool_call_id", "payload_digest", "read_request", "delivered_request"]);
    if (!["file", "artifact"].includes(read.kind) || !sha(read.content_digest) || !sha(read.payload_digest) || !text(read.tool_call_id)
        || ![read.start, read.end, read.total].every(number => Number.isSafeInteger(number) && number >= 0) || read.start > read.end || read.end > read.total
        || !Number.isSafeInteger(read.read_request) || read.read_request < 1 || read.read_request > value.last_request_ordinal
        || read.delivered_request !== null && (!Number.isSafeInteger(read.delivered_request) || read.delivered_request <= read.read_request || read.delivered_request > value.last_request_ordinal)) reject("EVIDENCE_IDENTITY", 4);
    if (read.kind === "file" && (!text(read.path) || !text(read.root_ref) || !Number.isSafeInteger(read.first_line) || read.first_line < 1
        || !Number.isSafeInteger(read.last_line) || read.last_line < 0) || read.kind === "artifact" && !text(read.artifact_id)) reject("EVIDENCE_IDENTITY", 4);
  }
  for (const output of value.structured_outputs) {
    closed(output, ["tool_call_id", "request_ordinal", "value_digest", "compatibility_digest"]);
    if (!text(output.tool_call_id) || !sha(output.value_digest) || !sha(output.compatibility_digest) || !Number.isSafeInteger(output.request_ordinal)
        || output.request_ordinal < 1 || output.request_ordinal > value.last_request_ordinal) reject("EVIDENCE_IDENTITY", 4);
  }
  for (const error of value.tool_errors) { closed(error, ["tool_name", "tool_call_id", "code"]); if (!Object.values(error).every(text)) reject(); }
  const ordinals = new Set();
  for (const request of value.requests) {
    closed(request, ["request_id", "ordinal", "status"]);
    if (!text(request.request_id) || !Number.isSafeInteger(request.ordinal) || request.ordinal < 1 || request.ordinal > value.last_request_ordinal
        || ordinals.has(request.ordinal) || request.status !== null && (!Number.isSafeInteger(request.status) || request.status < 100 || request.status > 599)) reject("EVIDENCE_IDENTITY", 4);
    ordinals.add(request.ordinal);
  }
  if (value.last_request_ordinal > 0 && !ordinals.has(value.last_request_ordinal)) reject("EVIDENCE_MISSING", 5);
  for (const denial of value.request_denials) { closed(denial, ["request_id", "code"]); if (!Object.values(denial).every(text)) reject(); }
  if (value.last_response !== null) closed(value.last_response, ["status", "headers"]);
  return value;
}
