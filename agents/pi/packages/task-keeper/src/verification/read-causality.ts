import { digest } from "../contracts/primitives.ts";
import type { ReadDelivery } from "../adapters/child-contract.ts";

export function textPayload(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (!Array.isArray(value) || value.some(part => !part || part.type !== "text" || typeof part.text !== "string")) return null;
  return value.map(part => part.text).join("\n");
}

/** Match the actual provider payload, not merely a tool finishing on the host. */
export function presentedReads<T extends ReadDelivery>(reads: T[], payload: unknown, requestOrdinal: number): T[] {
  const messages = (payload as {messages?: unknown[]})?.messages;
  if (!Array.isArray(messages)) return [];
  const visible = new Map<string, Set<string>>();
  for (const value of messages) {
    const message = value as {role?:unknown;tool_call_id?:unknown;content?:unknown};
    if (!message || message.role !== "tool" || typeof message.tool_call_id !== "string") continue;
    const text = textPayload(message.content); if (text === null) continue;
    const hashes = visible.get(message.tool_call_id) ?? new Set<string>(); hashes.add(digest(text)); visible.set(message.tool_call_id, hashes);
  }
  return reads.filter(read => typeof read.readRequest === "number" && read.readRequest < requestOrdinal
    && !!read.toolCallId && !!read.payloadDigest && visible.get(read.toolCallId)?.has(read.payloadDigest));
}

export function readBeforeVerdict(read: ReadDelivery, verdictRequest: number): boolean {
  return typeof read.toolCallId === "string" && read.toolCallId.length > 0 && typeof read.payloadDigest === "string" && /^[a-f0-9]{64}$/.test(read.payloadDigest)
    && Number.isSafeInteger(read.readRequest) && Number.isSafeInteger(read.deliveredRequest) && Number.isSafeInteger(verdictRequest)
    && read.readRequest! > 0 && read.readRequest! < read.deliveredRequest! && read.deliveredRequest! <= verdictRequest;
}
