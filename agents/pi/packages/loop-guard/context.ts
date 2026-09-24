import type { AgentMessage } from "@earendil-works/pi-agent-core";

import { actionFingerprint } from "./fingerprint.ts";
import type { EffectiveConfig } from "./types.ts";

export interface ContextCompactionResult {
	messages: AgentMessage[];
	prunedMessages: number;
	truncatedChars: number;
}

interface ToolCallInfo {
	id?: string;
	name: string;
	arguments: Record<string, unknown>;
}

interface CallGroup {
	index: number;
	calls: ToolCallInfo[];
	signatures: string[];
	toolOnly: boolean;
}

export function compactRepeatedToolHistory(
	messages: AgentMessage[],
	cwd: string,
	config: Pick<EffectiveConfig, "contextMaxMessages" | "contextMaxChars">,
): ContextCompactionResult {
	const resultByCallId = collectToolResults(messages);
	const groups: CallGroup[] = [];
	const occurrenceBySignature = new Map<string, CallGroup[]>();

	for (let index = 0; index < messages.length; index++) {
		const calls = toolCallsFromMessage(messages[index]);
		if (calls.length === 0) continue;
		const group: CallGroup = {
			index,
			calls,
			signatures: calls.map((call) => actionFingerprint(call.name, call.arguments, cwd)),
			toolOnly: isToolOnlyAssistantMessage(messages[index]),
		};
		groups.push(group);
		for (const signature of group.signatures) {
			const occurrences = occurrenceBySignature.get(signature) ?? [];
			occurrences.push(group);
			occurrenceBySignature.set(signature, occurrences);
		}
	}

	const keepGroups = new Set<number>();
	const repeatedSignatures = new Set<string>();
	for (const [signature, occurrences] of occurrenceBySignature) {
		if (occurrences.length <= 2) {
			for (const occurrence of occurrences) keepGroups.add(occurrence.index);
			continue;
		}
		repeatedSignatures.add(signature);
		keepGroups.add(occurrences[0].index);
		keepGroups.add(occurrences.at(-1)!.index);
		const firstFailure = occurrences.find((occurrence) =>
			occurrence.calls.some((call) => call.id && resultByCallId.get(call.id)?.failed),
		);
		if (firstFailure) keepGroups.add(firstFailure.index);
	}

	const droppedGroupIndices = new Set<number>();
	const droppedCallIds = new Set<string>();
	for (const group of groups) {
		if (!group.toolOnly || keepGroups.has(group.index)) continue;
		const allRepeated = group.signatures.every((signature) => repeatedSignatures.has(signature));
		if (!allRepeated) continue;
		droppedGroupIndices.add(group.index);
		for (const call of group.calls) {
			if (call.id) droppedCallIds.add(call.id);
		}
	}

	const retainedRepeatedGroups = groups.filter(
		(group) =>
			!droppedGroupIndices.has(group.index) &&
			group.signatures.some((signature) => repeatedSignatures.has(signature)),
	);
	const maxRepeatedGroups = Math.max(3, Math.floor(config.contextMaxMessages / 2));
	if (retainedRepeatedGroups.length > maxRepeatedGroups) {
		const boundedKeep = new Set<number>();
		boundedKeep.add(retainedRepeatedGroups[0].index);
		boundedKeep.add(retainedRepeatedGroups.at(-1)!.index);
		const firstFailure = retainedRepeatedGroups.find((group) =>
			group.calls.some((call) => call.id && resultByCallId.get(call.id)?.failed),
		);
		if (firstFailure) boundedKeep.add(firstFailure.index);
		for (let index = retainedRepeatedGroups.length - 1; index >= 0; index--) {
			if (boundedKeep.size >= maxRepeatedGroups) break;
			boundedKeep.add(retainedRepeatedGroups[index].index);
		}
		for (const group of retainedRepeatedGroups) {
			if (boundedKeep.has(group.index)) continue;
			droppedGroupIndices.add(group.index);
			for (const call of group.calls) {
				if (call.id) droppedCallIds.add(call.id);
			}
		}
	}

	const retained: AgentMessage[] = [];
	let prunedMessages = 0;
	for (let index = 0; index < messages.length; index++) {
		const message = messages[index];
		if (droppedGroupIndices.has(index) || isResultForDroppedCall(message, droppedCallIds)) {
			prunedMessages++;
			continue;
		}
		retained.push(message);
	}

	const repeatedResultIds = new Set<string>();
	for (const group of groups) {
		if (!group.signatures.some((signature) => repeatedSignatures.has(signature))) continue;
		for (const call of group.calls) {
			if (call.id && !droppedCallIds.has(call.id)) repeatedResultIds.add(call.id);
		}
	}
	const bounded = boundRepeatedResultText(retained, repeatedResultIds, config.contextMaxChars);

	return {
		messages: bounded.messages,
		prunedMessages,
		truncatedChars: bounded.truncatedChars,
	};
}

function collectToolResults(messages: AgentMessage[]): Map<string, { failed: boolean; index: number }> {
	const results = new Map<string, { failed: boolean; index: number }>();
	for (let index = 0; index < messages.length; index++) {
		const message = messages[index] as unknown as Record<string, unknown>;
		if (message.role !== "toolResult" || typeof message.toolCallId !== "string") continue;
		const text = messageText(message);
		results.set(message.toolCallId, {
			failed:
				message.isError === true ||
				/\b(error|failed|failure|exception|permission denied|not found|exit code [1-9])\b/i.test(text),
			index,
		});
	}
	return results;
}

function toolCallsFromMessage(message: AgentMessage): ToolCallInfo[] {
	const record = message as unknown as { role?: unknown; content?: unknown };
	if (record.role !== "assistant" || !Array.isArray(record.content)) return [];
	return record.content
		.filter(
			(part): part is Record<string, unknown> =>
				!!part &&
				typeof part === "object" &&
				(part as Record<string, unknown>).type === "toolCall" &&
				typeof (part as Record<string, unknown>).name === "string",
		)
		.map((part) => ({
			...(typeof part.id === "string" ? { id: part.id } : {}),
			name: part.name as string,
			arguments: asRecord(part.arguments),
		}));
}

function isToolOnlyAssistantMessage(message: AgentMessage): boolean {
	const record = message as unknown as { role?: unknown; content?: unknown };
	if (record.role !== "assistant" || !Array.isArray(record.content)) return false;
	return record.content.every((part) => {
		if (!part || typeof part !== "object") return false;
		const item = part as Record<string, unknown>;
		if (item.type === "toolCall") return true;
		return item.type === "text" && String(item.text ?? "").trim() === "";
	});
}

function isResultForDroppedCall(message: AgentMessage, droppedCallIds: Set<string>): boolean {
	const record = message as unknown as { role?: unknown; toolCallId?: unknown };
	return (
		record.role === "toolResult" &&
		typeof record.toolCallId === "string" &&
		droppedCallIds.has(record.toolCallId)
	);
}

function boundRepeatedResultText(
	messages: AgentMessage[],
	resultIds: Set<string>,
	maxChars: number,
): { messages: AgentMessage[]; truncatedChars: number } {
	const resultMessages = messages.filter((message) => {
		const record = message as unknown as { role?: unknown; toolCallId?: unknown };
		return (
			record.role === "toolResult" &&
			typeof record.toolCallId === "string" &&
			resultIds.has(record.toolCallId)
		);
	});
	const total = resultMessages.reduce((sum, message) => sum + messageText(message).length, 0);
	if (total <= maxChars || resultMessages.length === 0) {
		return { messages, truncatedChars: 0 };
	}

	const perResult = Math.max(256, Math.floor(maxChars / resultMessages.length));
	let truncatedChars = 0;
	const bounded = messages.map((message) => {
		const record = message as unknown as Record<string, unknown>;
		if (
			record.role !== "toolResult" ||
			typeof record.toolCallId !== "string" ||
			!resultIds.has(record.toolCallId)
		) {
			return message;
		}
		const text = messageText(message);
		if (text.length <= perResult) return message;
		truncatedChars += text.length - perResult;
		const headSize = Math.floor((perResult - 80) / 2);
		const tailSize = Math.max(0, perResult - 80 - headSize);
		const compacted = `${text.slice(0, headSize)}\n[LoopGuard compacted repeated tool result]\n${text.slice(-tailSize)}`;
		return {
			...record,
			content: [{ type: "text", text: compacted }],
		} as unknown as AgentMessage;
	});
	return { messages: bounded, truncatedChars };
}

function messageText(message: unknown): string {
	const record = message as { content?: unknown };
	if (typeof record.content === "string") return record.content;
	if (!Array.isArray(record.content)) return "";
	return record.content
		.map((part) => {
			if (!part || typeof part !== "object" || !("text" in part)) return "";
			return String((part as { text?: unknown }).text ?? "");
		})
		.join("\n");
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}
