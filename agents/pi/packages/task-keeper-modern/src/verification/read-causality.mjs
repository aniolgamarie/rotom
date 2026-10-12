import { digest } from "../contracts/primitives.mjs";
export function textPayload(value) {
    if (typeof value === "string") return value;
    if (!Array.isArray(value) || value.some((part)=>!part || part.type !== "text" || typeof part.text !== "string")) return null;
    return value.map((part)=>part.text).join("\n");
}
export function presentedReads(reads, payload, requestOrdinal) {
    const messages = payload?.messages;
    if (!Array.isArray(messages)) return [];
    const visible = new Map();
    for (const value of messages){
        const message = value;
        if (!message || message.role !== "tool" || typeof message.tool_call_id !== "string") continue;
        const text = textPayload(message.content);
        if (text === null) continue;
        const hashes = visible.get(message.tool_call_id) ?? new Set();
        hashes.add(digest(text));
        visible.set(message.tool_call_id, hashes);
    }
    return reads.filter((read)=>typeof read.readRequest === "number" && read.readRequest < requestOrdinal && !!read.toolCallId && !!read.payloadDigest && visible.get(read.toolCallId)?.has(read.payloadDigest));
}
export function readBeforeVerdict(read, verdictRequest) {
    return typeof read.toolCallId === "string" && read.toolCallId.length > 0 && typeof read.payloadDigest === "string" && /^[a-f0-9]{64}$/.test(read.payloadDigest) && Number.isSafeInteger(read.readRequest) && Number.isSafeInteger(read.deliveredRequest) && Number.isSafeInteger(verdictRequest) && read.readRequest > 0 && read.readRequest < read.deliveredRequest && read.deliveredRequest <= verdictRequest;
}
