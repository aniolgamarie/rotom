import {
	cloneState,
	createInitialState,
	evaluateToolRequest,
	recordToolOutcome,
} from "./engine.ts";
import {
	actionFingerprint,
	classifyResult,
	resultFingerprint,
	resultText,
	sessionScopedDigest,
} from "./fingerprint.ts";
import { serializeCheckpoint } from "./redaction.ts";
import type {
	ActionLedgerEntry,
	EffectiveConfig,
	IncidentRecord,
	LoopGuardCheckpointV1,
	LoopGuardState,
	ReasonCode,
	TransitionKind,
} from "./types.ts";

export const LOOP_GUARD_CHECKPOINT_TYPE = "starter-pi-loop-guard-checkpoint";

const TRANSITIONS = new Set<TransitionKind>([
	"task-boundary",
	"quota-block",
	"terminal-latch",
	"internal-failure",
	"reset",
	"incompatible-state",
]);
const REASONS = new Set<ReasonCode>([
	"allowed",
	"exact-quota-exhausted",
	"block-defiance",
	"task-latched",
	"internal-failure",
	"checkpoint-incompatible",
]);

export type CheckpointRestoreResult =
	| { kind: "none" }
	| { kind: "restored"; state: LoopGuardState; checkpoint: LoopGuardCheckpointV1 }
	| { kind: "incompatible"; error: string };

export interface CheckpointAppender {
	appendEntry<T = unknown>(customType: string, data?: T): void;
}

export function buildCheckpoint(
	state: LoopGuardState,
	incident: IncidentRecord,
): LoopGuardCheckpointV1 {
	if (!state.digestSalt) throw new Error("loop-guard session digest salt is unavailable");
	const challenge = findChallenge(state, incident.actionDigest);
	return serializeCheckpoint({
		version: 1,
		transition: incident.transition,
		reason: incident.reason,
		taskEpoch: state.taskEpoch,
		sequence: state.sequence,
		timestamp: incident.timestamp,
		digestSalt: state.digestSalt,
		latched: state.latched,
		...(state.latchReason ? { latchReason: state.latchReason } : {}),
		...(state.latchIncidentId ? { latchIncidentId: state.latchIncidentId } : {}),
		counters: { ...state.counters },
		...(challenge
			? {
					challenge: {
						actionDigest: challenge.digest,
						executions: challenge.executions,
						phase: challenge.phase,
						evidenceRevision: challenge.evidenceRevision,
						noProgressCount: challenge.noProgressCount,
					},
				}
			: {}),
		incident,
	});
}

export function appendCheckpoint(
	pi: CheckpointAppender,
	state: LoopGuardState,
	incident: IncidentRecord,
): LoopGuardState {
	const next = cloneState(state);
	next.counters.checkpointWrites++;
	const checkpoint = buildCheckpoint(next, incident);
	pi.appendEntry(LOOP_GUARD_CHECKPOINT_TYPE, checkpoint);
	return next;
}

export function restoreCheckpointFromBranch(
	entries: readonly unknown[],
	config: EffectiveConfig,
	restoredFrom: LoopGuardState["restoredFrom"],
	cwd = "",
): CheckpointRestoreResult {
	const start = Math.max(0, entries.length - config.checkpointScanLimit);
	for (let index = entries.length - 1; index >= start; index--) {
		const entry = asRecord(entries[index]);
		if (entry.type !== "custom" || entry.customType !== LOOP_GUARD_CHECKPOINT_TYPE) continue;
		const decoded = decodeCheckpoint(entry.data);
		if (!decoded) {
			return { kind: "incompatible", error: "loop-guard checkpoint is malformed or unsupported" };
		}
		const reconstructed = replayBranchAfterCheckpoint(
			stateFromCheckpoint(decoded, restoredFrom),
			entries.slice(index + 1),
			config,
			cwd,
		);
		if (reconstructed.kind === "incompatible") return reconstructed;
		return { kind: "restored", state: reconstructed.state, checkpoint: decoded };
	}
	if (entries.length > config.checkpointScanLimit) {
		return {
			kind: "incompatible",
			error: "no loop-guard checkpoint exists within the bounded active-branch scan",
		};
	}
	return { kind: "none" };
}

function replayBranchAfterCheckpoint(
	initial: LoopGuardState,
	entries: readonly unknown[],
	config: EffectiveConfig,
	cwd: string,
): { kind: "restored"; state: LoopGuardState } | { kind: "incompatible"; error: string } {
	let state = initial;
	const results = new Map<string, Record<string, unknown>>();
	for (const entryValue of entries) {
		const entry = asRecord(entryValue);
		if (entry.type !== "message") continue;
		const message = asRecord(entry.message);
		if (message.role !== "toolResult" || typeof message.toolCallId !== "string") continue;
		results.set(message.toolCallId, message);
	}

	const replayedIds = new Set<string>();
	for (const entryValue of entries) {
		const entry = asRecord(entryValue);
		if (entry.type !== "message") continue;
		const message = asRecord(entry.message);
		if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
		for (const partValue of message.content) {
			const part = asRecord(partValue);
			if (
				part.type !== "toolCall" ||
				typeof part.id !== "string" ||
				typeof part.name !== "string"
			) {
				continue;
			}
			if (replayedIds.has(part.id)) {
				return { kind: "incompatible", error: "duplicate post-checkpoint tool-call identifier" };
			}
			replayedIds.add(part.id);
			const result = results.get(part.id);
			if (!result) {
				return {
					kind: "incompatible",
					error: "post-checkpoint tool call has no trustworthy correlated result",
				};
			}
			const input = asRecord(part.arguments);
			const fingerprint = actionFingerprint(part.name, input, cwd);
			const digest = sessionScopedDigest(fingerprint, initial.digestSalt!);
			const timestamp = entryTimestamp(entry, initial.sequence + 1);
			const request = evaluateToolRequest(
				state,
				{
					toolCallId: part.id,
					toolName: part.name,
					actionFingerprint: fingerprint,
					actionDigest: digest,
					timestamp,
				},
				config,
			);
			state = request.state;
			if (request.checkpointRequired) {
				return {
					kind: "incompatible",
					error: "post-checkpoint safety transition is missing its required checkpoint",
				};
			}
			const resultLooksBlocked = isLoopGuardBlockedResult(result);
			if (request.value.allow === resultLooksBlocked) {
				return {
					kind: "incompatible",
					error: "post-checkpoint tool result contradicts reconstructed enforcement state",
				};
			}
			if (!request.value.allow) continue;
			const outcome = recordToolOutcome(
				state,
				{
					toolCallId: part.id,
					resultFingerprint: resultFingerprint(result.content),
					resultClass: classifyResult(result.content, result.isError === true),
					timestamp: entryTimestamp(result, timestamp),
				},
				config,
			);
			state = outcome.state;
		}
	}
	return { kind: "restored", state };
}

export function decodeCheckpoint(value: unknown): LoopGuardCheckpointV1 | undefined {
	const data = asRecord(value);
	if (data.version !== 1) return undefined;
	if (typeof data.transition !== "string" || !TRANSITIONS.has(data.transition as TransitionKind)) {
		return undefined;
	}
	if (typeof data.reason !== "string" || !REASONS.has(data.reason as ReasonCode)) return undefined;
	if (!isNonNegativeInteger(data.taskEpoch) || !isNonNegativeInteger(data.sequence)) return undefined;
	if (typeof data.timestamp !== "number" || !Number.isFinite(data.timestamp)) return undefined;
	if (typeof data.digestSalt !== "string" || !/^[0-9a-f]{64}$/.test(data.digestSalt)) return undefined;
	if (typeof data.latched !== "boolean") return undefined;
	if (data.latchReason !== undefined) {
		if (typeof data.latchReason !== "string" || !REASONS.has(data.latchReason as ReasonCode)) {
			return undefined;
		}
	}
	if (data.latchIncidentId !== undefined && typeof data.latchIncidentId !== "string") return undefined;
	const counters = decodeCounters(data.counters);
	if (!counters) return undefined;

	const challengeRecord = data.challenge === undefined ? undefined : asRecord(data.challenge);
	if (challengeRecord !== undefined && !isChallenge(challengeRecord)) return undefined;
	const incident = data.incident === undefined ? undefined : decodeIncident(data.incident);
	if (data.incident !== undefined && !incident) return undefined;

	return {
		version: 1,
		transition: data.transition as TransitionKind,
		reason: data.reason as ReasonCode,
		taskEpoch: data.taskEpoch as number,
		sequence: data.sequence as number,
		timestamp: data.timestamp,
		digestSalt: data.digestSalt,
		latched: data.latched,
		...(data.latchReason ? { latchReason: data.latchReason as ReasonCode } : {}),
		...(data.latchIncidentId ? { latchIncidentId: data.latchIncidentId } : {}),
		counters,
		...(challengeRecord
			? {
					challenge: {
						actionDigest: challengeRecord.actionDigest as string,
						executions: challengeRecord.executions as number,
						phase: challengeRecord.phase as "ready" | "quota-exhausted" | "block-challenged",
						evidenceRevision: challengeRecord.evidenceRevision as number,
						noProgressCount: challengeRecord.noProgressCount as number,
					},
				}
			: {}),
		...(incident ? { incident } : {}),
	};
}

function stateFromCheckpoint(
	checkpoint: LoopGuardCheckpointV1,
	restoredFrom: LoopGuardState["restoredFrom"],
): LoopGuardState {
	const state = createInitialState();
	state.taskEpoch = checkpoint.taskEpoch;
	state.sequence = checkpoint.sequence;
	state.digestSalt = checkpoint.digestSalt;
	state.latched = checkpoint.latched;
	state.counters = { ...checkpoint.counters };
	state.restored = true;
	if (restoredFrom) state.restoredFrom = restoredFrom;
	if (checkpoint.latchReason) state.latchReason = checkpoint.latchReason;
	if (checkpoint.latchIncidentId) state.latchIncidentId = checkpoint.latchIncidentId;
	if (checkpoint.incident) state.incidents.push({ ...checkpoint.incident });
	if (checkpoint.challenge) {
		const key = `restored:${checkpoint.challenge.actionDigest}`;
		state.ledger.set(key, {
			fingerprint: key,
			digest: checkpoint.challenge.actionDigest,
			toolName: "restored",
			executions: checkpoint.challenge.executions,
			phase: checkpoint.challenge.phase,
			firstSequence: checkpoint.sequence,
			lastSequence: checkpoint.sequence,
			evidenceRevision: checkpoint.challenge.evidenceRevision,
			noProgressCount: checkpoint.challenge.noProgressCount,
		});
	}
	return state;
}

function findChallenge(
	state: LoopGuardState,
	preferredDigest?: string,
): ActionLedgerEntry | undefined {
	if (preferredDigest) {
		const preferred = [...state.ledger.values()].find((entry) => entry.digest === preferredDigest);
		if (preferred) return preferred;
	}
	return [...state.ledger.values()].find((entry) => entry.phase === "block-challenged");
}

function decodeCounters(value: unknown): LoopGuardState["counters"] | undefined {
	const data = asRecord(value);
	const keys: Array<keyof LoopGuardState["counters"]> = [
		"requestedCalls",
		"executedCalls",
		"blockedCalls",
		"terminalDecisions",
		"resultUpdates",
		"alreadyStartedSiblingResults",
		"responseFindings",
		"cycleFindings",
		"checkpointWrites",
	];
	if (!keys.every((key) => isNonNegativeInteger(data[key]))) return undefined;
	return Object.fromEntries(keys.map((key) => [key, data[key]])) as unknown as LoopGuardState["counters"];
}

function decodeIncident(value: unknown): IncidentRecord | undefined {
	const data = asRecord(value);
	if (data.version !== 1 || typeof data.id !== "string") return undefined;
	if (typeof data.transition !== "string" || !TRANSITIONS.has(data.transition as TransitionKind)) {
		return undefined;
	}
	if (typeof data.reason !== "string" || !REASONS.has(data.reason as ReasonCode)) return undefined;
	if (!isNonNegativeInteger(data.taskEpoch) || !isNonNegativeInteger(data.sequence)) return undefined;
	if (typeof data.timestamp !== "number" || !Number.isFinite(data.timestamp)) return undefined;
	if (data.actionDigest !== undefined && typeof data.actionDigest !== "string") return undefined;
	if (data.executionCount !== undefined && !isNonNegativeInteger(data.executionCount)) return undefined;
	if (data.count !== undefined && !isNonNegativeInteger(data.count)) return undefined;
	return {
		version: 1,
		id: data.id,
		transition: data.transition as TransitionKind,
		reason: data.reason as ReasonCode,
		taskEpoch: data.taskEpoch as number,
		sequence: data.sequence as number,
		timestamp: data.timestamp,
		...(data.actionDigest ? { actionDigest: data.actionDigest as string } : {}),
		...(data.executionCount !== undefined ? { executionCount: data.executionCount as number } : {}),
		...(data.count !== undefined ? { count: data.count as number } : {}),
	};
}

function isChallenge(data: Record<string, unknown>): boolean {
	return (
		typeof data.actionDigest === "string" &&
		isNonNegativeInteger(data.executions) &&
		(data.phase === "ready" || data.phase === "quota-exhausted" || data.phase === "block-challenged") &&
		isNonNegativeInteger(data.evidenceRevision) &&
		isNonNegativeInteger(data.noProgressCount)
	);
}

function isNonNegativeInteger(value: unknown): boolean {
	return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function entryTimestamp(entry: Record<string, unknown>, fallback: number): number {
	if (typeof entry.timestamp === "number" && Number.isFinite(entry.timestamp)) return entry.timestamp;
	if (typeof entry.timestamp === "string") {
		const parsed = Date.parse(entry.timestamp);
		if (Number.isFinite(parsed)) return parsed;
	}
	return fallback;
}

function isLoopGuardBlockedResult(message: Record<string, unknown>): boolean {
	return (
		message.isError === true &&
		/^LoopGuard \[(?:exact-quota-exhausted|block-defiance|task-latched|internal-failure|checkpoint-incompatible)\]:/.test(
			resultText(message.content),
		)
	);
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}
