import { formatActionReference } from "./action-reference.ts";
import { buildCheckpoint, decodeCheckpoint } from "./persistence.ts";
import type {
	IncidentRecord,
	LoopGuardCheckpointV1,
	LoopGuardState,
	ReasonCode,
	TerminalReportView,
} from "./types.ts";

const TERMINAL_TRANSITIONS = new Set(["terminal-latch", "internal-failure", "incompatible-state"]);

export function buildTerminalReport(value: unknown): TerminalReportView | undefined {
	const checkpoint = decodeCheckpoint(value);
	if (!checkpoint || !TERMINAL_TRANSITIONS.has(checkpoint.transition) || !checkpoint.latched) return undefined;
	const incidentId = checkpoint.latchIncidentId ?? checkpoint.incident?.id;
	if (!incidentId) return undefined;
	const actionReference = formatActionReference(
		checkpoint.challenge?.actionDigest ?? checkpoint.incident?.actionDigest,
	);
	const executionCount = checkpoint.incident?.executionCount ?? checkpoint.challenge?.executions;
	const reason = checkpoint.latchReason ?? checkpoint.reason;
	const collapsedLines = [
		"LoopGuard terminal latch",
		`${reason} · ${actionReference ?? "action:unavailable"}`,
		`incident: ${incidentId} · epoch: ${checkpoint.taskEpoch}`,
	];
	const expandedLines = [
		...collapsedLines,
		"",
		"Cause",
		causeFor(reason),
		"",
		"Evidence",
		`action: ${actionReference ?? "unavailable"}`,
		`completed executions: ${executionCount ?? "unavailable"}`,
		`task epoch: ${checkpoint.taskEpoch}`,
		`incident: ${incidentId}`,
		"",
		"Effect",
		"The task is terminally latched and Pi termination was requested.",
		"Later tool calls that observe this latch are blocked before execution.",
		"Tool calls already started in the same batch may still finish; no rollback is claimed.",
		"",
		"Recovery",
		...recoveryFor(reason),
		`Details: /loop-guard explain ${incidentId}`,
	];
	return {
		transition: checkpoint.transition,
		reason,
		incidentId,
		taskEpoch: checkpoint.taskEpoch,
		...(actionReference ? { actionReference } : {}),
		...(executionCount !== undefined ? { executionCount } : {}),
		collapsedLines,
		expandedLines,
	};
}

export function formatTerminalNotification(
	report: TerminalReportView,
	restored = false,
): string {
	return [
		`LoopGuard ${restored ? "restored" : "committed"} terminal latch: ${report.reason}`,
		`${report.actionReference ?? "action:unavailable"} · incident ${report.incidentId} · epoch ${report.taskEpoch}`,
		`Review with /loop-guard explain ${report.incidentId}`,
	].join("\n");
}

export function buildTerminalReportFromState(
	state: LoopGuardState,
	incident: IncidentRecord | undefined,
): TerminalReportView | undefined {
	if (!incident) return undefined;
	try {
		return buildTerminalReport(buildCheckpoint(state, incident));
	} catch {
		return undefined;
	}
}

export function buildMalformedTerminalReport(): TerminalReportView {
	return {
		transition: "incompatible-state",
		reason: "checkpoint-incompatible",
		incidentId: "unavailable",
		taskEpoch: 0,
		collapsedLines: [
			"LoopGuard terminal checkpoint",
			"checkpoint-incompatible · action:unavailable",
			"incident: unavailable",
		],
		expandedLines: [
			"LoopGuard terminal checkpoint",
			"checkpoint-incompatible · action:unavailable",
			"incident: unavailable",
			"",
			"The terminal checkpoint could not be rendered safely.",
			"No checkpoint fields or raw values were displayed.",
			"Inspect /loop-guard status before an explicit reset.",
		],
	};
}

export function terminalCheckpointLooksEligible(value: unknown): boolean {
	const record = asRecord(value);
	return record.latched === true && typeof record.transition === "string" && TERMINAL_TRANSITIONS.has(record.transition);
}

export function restorationActivationKey(
	sessionId: string,
	leafId: string | null,
	incidentId: string,
): string {
	return `${sessionId}\u0000${leafId ?? "<root>"}\u0000${incidentId}`;
}

function causeFor(reason: ReasonCode): string {
	switch (reason) {
		case "block-defiance":
			return "A previously quota-blocked exact action was requested again.";
		case "checkpoint-incompatible":
			return "Saved safety state could not be restored as a trustworthy compatible checkpoint.";
		case "internal-failure":
			return "LoopGuard could not make or persist a trustworthy enforcement decision.";
		default:
			return "The task remains stopped by a previously committed LoopGuard terminal incident.";
	}
}

function recoveryFor(reason: ReasonCode): string[] {
	switch (reason) {
		case "checkpoint-incompatible":
			return [
				"Load a compatible extension or inspect the incident before an explicit reset.",
				"Do not assume that reopening or forking cleared the saved safety state.",
			];
		case "internal-failure":
			return [
				"Inspect /loop-guard status and the degraded subsystem before resetting.",
				"Fix the guard or checkpoint path before resuming sensitive work.",
			];
		default:
			return [
				"Review the incident, then send trusted interactive/RPC input for a new task epoch,",
				"or run /loop-guard reset explicitly after review.",
			];
	}
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}
