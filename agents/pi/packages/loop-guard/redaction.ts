import type { IncidentRecord, LoopGuardCheckpointV1 } from "./types.ts";

const SECRET_ASSIGNMENT =
	/\b(api[_-]?key|access[_-]?token|auth(?:orization)?|password|passwd|secret)\s*[:=]\s*([^\s,;]+)/gi;
const BEARER_TOKEN = /\bbearer\s+[a-z0-9._~+\/-]+=*/gi;
const HOME_PATH = /\/(?:home|Users)\/[^\s'"`]+/g;
const GENERIC_ABSOLUTE_PATH = /\/(?:[^\s'"`/]+\/)+[^\s'"`]+/g;

export function redactText(value: unknown, maxChars = 400): string {
	return String(value ?? "")
		.replace(SECRET_ASSIGNMENT, (_match, name: string) => `${name}=<redacted>`)
		.replace(BEARER_TOKEN, "Bearer <redacted>")
		.replace(HOME_PATH, "<path>")
		.replace(GENERIC_ABSOLUTE_PATH, "<path>")
		.slice(0, maxChars);
}

export function safeErrorLabel(error: unknown): string {
	if (error instanceof Error) return redactText(error.name || "Error", 80);
	return "UnknownError";
}

export function serializeIncident(incident: IncidentRecord): IncidentRecord {
	return {
		version: 1,
		id: incident.id,
		transition: incident.transition,
		reason: incident.reason,
		taskEpoch: incident.taskEpoch,
		sequence: incident.sequence,
		timestamp: incident.timestamp,
		...(incident.actionDigest ? { actionDigest: incident.actionDigest } : {}),
		...(incident.executionCount !== undefined
			? { executionCount: incident.executionCount }
			: {}),
		...(incident.count !== undefined ? { count: incident.count } : {}),
	};
}

export function serializeCheckpoint(checkpoint: LoopGuardCheckpointV1): LoopGuardCheckpointV1 {
	return {
		version: 1,
		transition: checkpoint.transition,
		reason: checkpoint.reason,
		taskEpoch: checkpoint.taskEpoch,
		sequence: checkpoint.sequence,
		timestamp: checkpoint.timestamp,
		digestSalt: checkpoint.digestSalt,
		latched: checkpoint.latched,
		counters: { ...checkpoint.counters },
		...(checkpoint.latchReason ? { latchReason: checkpoint.latchReason } : {}),
		...(checkpoint.latchIncidentId ? { latchIncidentId: checkpoint.latchIncidentId } : {}),
		...(checkpoint.challenge
			? {
					challenge: {
						actionDigest: checkpoint.challenge.actionDigest,
						executions: checkpoint.challenge.executions,
						phase: checkpoint.challenge.phase,
						evidenceRevision: checkpoint.challenge.evidenceRevision,
						noProgressCount: checkpoint.challenge.noProgressCount,
					},
				}
			: {}),
		...(checkpoint.incident ? { incident: serializeIncident(checkpoint.incident) } : {}),
	};
}
