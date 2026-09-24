import { formatActionReference } from "./action-reference.ts";
import {
	actionFingerprint,
	classifyResult,
	resultFingerprint,
	resultText,
	sessionScopedDigest,
} from "./fingerprint.ts";
import { decodeCheckpoint, LOOP_GUARD_CHECKPOINT_TYPE } from "./persistence.ts";
import type {
	ExplanationObservation,
	IncidentExplanation,
	IncidentExplanationResult,
	IncidentRecord,
	IncidentSelection,
	LoopGuardCheckpointV1,
	ReasonCode,
	ResultEvidence,
	StructuralFieldSummary,
	StructuralInputSummary,
	StructuralValueKind,
} from "./types.ts";

const MAX_STRUCTURAL_FIELDS = 16;
const MAX_FIELD_NAME_CHARS = 64;
const MAX_NESTED_KEYS = 8;
const MAX_EXPLANATION_OBSERVATIONS = 32;
const EXPLAINABLE_TRANSITIONS = new Set([
	"quota-block",
	"terminal-latch",
	"internal-failure",
	"incompatible-state",
]);
const LOOP_GUARD_RESULT_PATTERN =
	/^LoopGuard \[(exact-quota-exhausted|block-defiance|task-latched|internal-failure|checkpoint-incompatible)\]:/;

interface CheckpointCandidate {
	checkpoint: LoopGuardCheckpointV1;
	incident: IncidentRecord;
	index: number;
}

interface ToolCallCandidate {
	branchIndex: number;
	toolCallId: string;
	toolName: string;
	input: Record<string, unknown>;
}

export function parseIncidentSelection(argument: string): IncidentSelection {
	const value = argument.trim();
	if (value === "" || value.toLowerCase() === "latest") return { kind: "latest" };
	return { kind: "incident-id", incidentId: value };
}

export function summarizeToolInput(
	toolName: string,
	input: Record<string, unknown>,
): StructuralInputSummary {
	const fields = Object.keys(input)
		.sort()
		.slice(0, MAX_STRUCTURAL_FIELDS)
		.map((name) => summarizeField(name, input[name]));
	return { toolName, fields };
}

export function explainIncident(
	entries: readonly unknown[],
	selection: IncidentSelection,
	cwd: string,
	scanLimit: number,
): IncidentExplanationResult {
	const boundedLimit = Math.max(1, Math.floor(scanLimit));
	const start = Math.max(0, entries.length - boundedLimit);
	const bounded = entries.slice(start);
	const checkpoints = collectCheckpointCandidates(bounded, start);
	const selected = selectCheckpoint(checkpoints, selection);
	if (!selected) {
		return {
			kind: "not-found",
			...(selection.kind === "incident-id" ? { incidentId: selection.incidentId } : {}),
			scannedEntries: bounded.length,
		};
	}

	const targetDigest = selected.incident.actionDigest ?? selected.checkpoint.challenge?.actionDigest;
	const actionReference = formatActionReference(targetDigest);
	if (!targetDigest || !actionReference) {
		return {
			kind: "unavailable",
			incident: { ...selected.incident },
			reason: "the incident has no valid challenged-action digest",
			scannedEntries: bounded.length,
		};
	}

	const missing: string[] = [];
	const boundary = findTaskBoundary(checkpoints, selected);
	if (!boundary) missing.push("task-boundary-unavailable");
	const callStart = boundary ? boundary.index + 1 : start;
	const results = collectToolResults(bounded, start);
	const calls = collectToolCalls(bounded, start).filter(
		(call) => call.branchIndex >= callStart && call.branchIndex <= selected.index,
	);
	const quotaIndex = findQuotaCheckpointIndex(checkpoints, selected, targetDigest);
	const observations: ExplanationObservation[] = [];
	const matchingResultFingerprints: string[] = [];

	for (const call of calls) {
		const fingerprint = actionFingerprint(call.toolName, call.input, cwd);
		const digest = sessionScopedDigest(fingerprint, selected.checkpoint.digestSalt);
		const reference = formatActionReference(digest);
		if (!reference) continue;
		const result = results.get(call.toolCallId);
		const guardReason = result ? loopGuardResultReason(result) : undefined;
		let kind: ExplanationObservation["kind"] | undefined;
		if (digest === targetDigest) {
			if (guardReason === "exact-quota-exhausted") kind = "quota-block";
			else if (guardReason === "block-defiance" || guardReason === "task-latched") {
				kind = "terminal-defiance";
			} else if (result) {
				kind = "matching-execution";
			} else {
				kind = "unpaired-request";
			}
		} else if (quotaIndex !== undefined && call.branchIndex > quotaIndex) {
			kind = "intervening-action";
		}
		if (!kind) continue;

		const observation: ExplanationObservation = {
			kind,
			branchIndex: call.branchIndex,
			toolCallId: call.toolCallId,
			toolName: call.toolName,
			actionReference: reference,
			input: summarizeToolInput(call.toolName, call.input),
		};
		if (result) {
			observation.resultClass = classifyResult(result.content, result.isError === true);
			observation.resultFingerprint = resultFingerprint(result.content);
			if (kind === "matching-execution") {
				matchingResultFingerprints.push(observation.resultFingerprint);
			}
		}
		observations.push(observation);
	}

	const expectedExecutions = selected.incident.executionCount ?? selected.checkpoint.challenge?.executions;
	const matchingExecutions = observations.filter((item) => item.kind === "matching-execution").length;
	if (expectedExecutions !== undefined && matchingExecutions < expectedExecutions) {
		missing.push("matching-executions-unavailable");
	}
	if (observations.some((item) => item.kind === "unpaired-request")) {
		missing.push("correlated-result-unavailable");
	}
	if (
		selected.incident.reason === "exact-quota-exhausted" &&
		!observations.some((item) => item.kind === "quota-block")
	) {
		missing.push("quota-block-result-unavailable");
	}
	if (
		selected.incident.reason === "block-defiance" &&
		!observations.some((item) => item.kind === "terminal-defiance")
	) {
		missing.push("terminal-result-unavailable");
	}
	if (observations.length > MAX_EXPLANATION_OBSERVATIONS) {
		observations.splice(1, observations.length - MAX_EXPLANATION_OBSERVATIONS);
		missing.push("observation-limit-reached");
	}

	const explanation: IncidentExplanation = {
		completeness: missing.length === 0 ? "complete" : "partial",
		incident: { ...selected.incident },
		actionReference,
		...(expectedExecutions !== undefined ? { executionCount: expectedExecutions } : {}),
		resultEvidence: resultEvidence(matchingResultFingerprints),
		observations,
		missing: [...new Set(missing)],
		scannedEntries: bounded.length,
	};
	return { kind: "explained", explanation };
}

export function formatIncidentExplanation(result: IncidentExplanationResult): string {
	if (result.kind === "not-found") {
		return [
			"Loop guard incident explanation",
			`incident: ${result.incidentId ?? "latest"}`,
			"status: not found on the bounded active branch",
			`scanned entries: ${result.scannedEntries}`,
		].join("\n");
	}
	if (result.kind === "unavailable") {
		return [
			"Loop guard incident explanation",
			`incident: ${result.incident.id}`,
			`reason: ${result.incident.reason}`,
			`task epoch: ${result.incident.taskEpoch}`,
			`action: ${result.actionReference ?? "unavailable"}`,
			"status: unavailable",
			`detail: ${result.reason}`,
			`scanned entries: ${result.scannedEntries}`,
		].join("\n");
	}

	const explanation = result.explanation;
	const lines = [
		"Loop guard incident explanation",
		`incident: ${explanation.incident.id}`,
		`reason: ${explanation.incident.reason}`,
		`task epoch: ${explanation.incident.taskEpoch}`,
		`action: ${explanation.actionReference ?? "unavailable"}`,
		`executions: ${explanation.executionCount ?? "unavailable"}`,
		`result evidence: ${explanation.resultEvidence}`,
		`status: ${explanation.completeness}`,
		"timeline:",
	];
	for (const item of explanation.observations) {
		lines.push(
			`- branch#${item.branchIndex} ${item.kind} tool=${item.toolName} ${item.actionReference}` +
				`${item.resultClass ? ` result=${item.resultClass}` : ""} input=${formatStructuralInput(item.input)}`,
		);
	}
	if (explanation.missing.length > 0) lines.push(`missing: ${explanation.missing.join(", ")}`);
	lines.push(`scanned entries: ${explanation.scannedEntries}`);
	return lines.join("\n");
}

function collectCheckpointCandidates(
	entries: readonly unknown[],
	offset: number,
): CheckpointCandidate[] {
	const candidates: CheckpointCandidate[] = [];
	for (let index = 0; index < entries.length; index++) {
		const entry = asRecord(entries[index]);
		if (entry.type !== "custom" || entry.customType !== LOOP_GUARD_CHECKPOINT_TYPE) continue;
		const checkpoint = decodeCheckpoint(entry.data);
		if (!checkpoint?.incident) continue;
		candidates.push({ checkpoint, incident: checkpoint.incident, index: offset + index });
	}
	return candidates;
}

function selectCheckpoint(
	candidates: CheckpointCandidate[],
	selection: IncidentSelection,
): CheckpointCandidate | undefined {
	const explainable = candidates.filter((candidate) => EXPLAINABLE_TRANSITIONS.has(candidate.incident.transition));
	if (selection.kind === "latest") return explainable.at(-1);
	return explainable.find((candidate) => candidate.incident.id === selection.incidentId);
}

function findTaskBoundary(
	candidates: CheckpointCandidate[],
	selected: CheckpointCandidate,
): CheckpointCandidate | undefined {
	return candidates
		.filter(
			(candidate) =>
				candidate.index < selected.index &&
				candidate.incident.taskEpoch === selected.incident.taskEpoch &&
				(candidate.incident.transition === "task-boundary" || candidate.incident.transition === "reset"),
		)
		.at(-1);
}

function findQuotaCheckpointIndex(
	candidates: CheckpointCandidate[],
	selected: CheckpointCandidate,
	targetDigest: string,
): number | undefined {
	return candidates
		.filter(
			(candidate) =>
				candidate.index <= selected.index &&
				candidate.incident.taskEpoch === selected.incident.taskEpoch &&
				candidate.incident.reason === "exact-quota-exhausted" &&
				(candidate.incident.actionDigest ?? candidate.checkpoint.challenge?.actionDigest) === targetDigest,
		)
		.at(-1)?.index;
}

function collectToolCalls(entries: readonly unknown[], offset: number): ToolCallCandidate[] {
	const calls: ToolCallCandidate[] = [];
	for (let index = 0; index < entries.length; index++) {
		const entry = asRecord(entries[index]);
		if (entry.type !== "message") continue;
		const message = asRecord(entry.message);
		if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
		for (const partValue of message.content) {
			const part = asRecord(partValue);
			if (part.type !== "toolCall" || typeof part.id !== "string" || typeof part.name !== "string") continue;
			calls.push({
				branchIndex: offset + index,
				toolCallId: part.id,
				toolName: part.name,
				input: asRecord(part.arguments),
			});
		}
	}
	return calls;
}

function collectToolResults(
	entries: readonly unknown[],
	_offset: number,
): Map<string, Record<string, unknown>> {
	const results = new Map<string, Record<string, unknown>>();
	for (const entryValue of entries) {
		const entry = asRecord(entryValue);
		if (entry.type !== "message") continue;
		const message = asRecord(entry.message);
		if (message.role !== "toolResult" || typeof message.toolCallId !== "string") continue;
		results.set(message.toolCallId, message);
	}
	return results;
}

function loopGuardResultReason(result: Record<string, unknown>): ReasonCode | undefined {
	if (result.isError !== true) return undefined;
	const match = LOOP_GUARD_RESULT_PATTERN.exec(resultText(result.content));
	return match?.[1] as ReasonCode | undefined;
}

function resultEvidence(fingerprints: string[]): ResultEvidence {
	if (fingerprints.length < 2) return fingerprints.length === 0 ? "unavailable" : "insufficient";
	return new Set(fingerprints).size === 1 ? "stable" : "changed";
}

function summarizeField(name: string, value: unknown): StructuralFieldSummary {
	const summary: StructuralFieldSummary = {
		name: safeFieldName(name),
		kind: structuralKind(value),
	};
	if (typeof value === "string") {
		summary.length = value.length;
		summary.lines = value === "" ? 0 : value.split(/\r?\n/).length;
	} else if (Array.isArray(value)) {
		summary.length = value.length;
	} else if (value && typeof value === "object") {
		summary.keys = Object.keys(value as Record<string, unknown>)
			.sort()
			.slice(0, MAX_NESTED_KEYS)
			.map(safeFieldName);
	}
	return summary;
}

function structuralKind(value: unknown): StructuralValueKind {
	if (value === null) return "null";
	if (Array.isArray(value)) return "array";
	if (typeof value === "boolean") return "boolean";
	if (typeof value === "number" || typeof value === "bigint") return "number";
	if (typeof value === "string") return "string";
	if (typeof value === "undefined") return "undefined";
	return "object";
}

function safeFieldName(value: string): string {
	return value.normalize("NFKC").replace(/[^a-zA-Z0-9_.-]/g, "_").slice(0, MAX_FIELD_NAME_CHARS) || "field";
}

function formatStructuralInput(input: StructuralInputSummary): string {
	if (input.fields.length === 0) return "{}";
	return `{${input.fields
		.map((field) => {
			const metrics = [
				field.length !== undefined ? `length=${field.length}` : "",
				field.lines !== undefined ? `lines=${field.lines}` : "",
				field.keys ? `keys=${field.keys.join("|")}` : "",
			].filter(Boolean);
			return `${field.name}:${field.kind}${metrics.length > 0 ? `(${metrics.join(",")})` : ""}`;
		})
		.join(",")}}`;
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}
