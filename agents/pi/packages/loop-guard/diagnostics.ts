import type { AdvisorySummary } from "./advisory.ts";
import { formatActionReference } from "./action-reference.ts";
import { findChallengeEntry } from "./engine.ts";
import type { EffectiveConfig, LoopGuardState } from "./types.ts";

export function formatLoopGuardStatus(
	config: EffectiveConfig,
	state: LoopGuardState,
	advisory: AdvisorySummary,
): string {
	const latest = state.incidents.at(-1);
	const challenge = findChallengeEntry(state);
	const actionReference = formatActionReference(challenge?.digest);
	return [
		"Loop guard status",
		`deterministic mode: ${config.enforcementMode}`,
		`advisory mode: ${config.advisoryMode}`,
		`exact execution quota: ${config.repeatLimit}`,
		`legacy failure threshold (diagnostic compatibility): ${config.failureLimit}`,
		`response repeat threshold: ${config.responseRepeatLimit}`,
		`response similarity threshold: ${config.responseSimilarityThreshold}`,
		`legacy observation window: ${config.windowMs}ms`,
		`task epoch: ${state.taskEpoch}`,
		`latch: ${state.latched ? "terminal" : "open"}`,
		`latest reason: ${state.latchReason ?? latest?.reason ?? "none"}`,
		`latest incident: ${state.latchIncidentId ?? latest?.id ?? "none"}`,
		`challenged action: ${actionReference ?? "none"}`,
		`challenge executions: ${challenge?.executions ?? "none"}`,
		`challenge phase: ${challenge?.phase ?? "none"}`,
		`restored state: ${state.restored ? state.restoredFrom ?? "yes" : "no"}`,
		`tracked actions: ${state.ledger.size}/${config.maxEntries}`,
		`pending calls: ${state.pendingCalls.size}/${config.maxPendingCalls}`,
		`incidents: ${state.incidents.length}/${config.maxIncidents}`,
		`requests/executed/blocked/terminal: ${state.counters.requestedCalls}/${state.counters.executedCalls}/${state.counters.blockedCalls}/${state.counters.terminalDecisions}`,
		`result updates: ${state.counters.resultUpdates}`,
		`already-started sibling results: ${state.counters.alreadyStartedSiblingResults}`,
		`checkpoint writes: ${state.counters.checkpointWrites}`,
		`response observations/findings: ${advisory.responseObservations}/${advisory.responseFindings}`,
		`cycle findings: ${advisory.cycleFindings}`,
		`response coverage: ${advisory.coverage}`,
		`degraded subsystems: ${[...state.degradedSubsystems].sort().join(", ") || "none"}`,
		`configuration warnings: ${config.warnings.join("; ") || "none"}`,
		"allow-repeat annotation: recognized, never bypasses the exact quota or latch",
		"commands: /loop-guard explain [latest|<incident-id>] | reset | on | off | response-on | response-off",
	].join("\n");
}

export function minimalStatusFallback(state: LoopGuardState): string {
	const challenge = findChallengeEntry(state);
	return `LoopGuard: epoch=${state.taskEpoch} latch=${state.latched ? "terminal" : "open"} reason=${state.latchReason ?? "none"} incident=${state.latchIncidentId ?? "none"} action=${formatActionReference(challenge?.digest) ?? "none"}`;
}

export function formatActiveLatchStatus(
	config: Pick<EffectiveConfig, "enforcementMode">,
	state: LoopGuardState,
): string | undefined {
	const challenge = findChallengeEntry(state);
	const actionReference = formatActionReference(challenge?.digest) ?? "action:unavailable";
	if (config.enforcementMode === "off") {
		return state.latched
			? `LoopGuard: OFF · retained ${state.latchReason ?? "terminal latch"} · ${state.latchIncidentId ?? "incident unavailable"}`
			: "LoopGuard: OFF";
	}
	if (!state.latched) return undefined;
	return `LoopGuard: terminal · ${state.latchReason ?? "unknown"} · ${actionReference} · ${state.latchIncidentId ?? "incident unavailable"}`;
}
