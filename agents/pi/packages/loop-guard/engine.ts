import { formatActionReference } from "./action-reference.ts";
import type {
	ActionLedgerEntry,
	EngineTransition,
	EffectiveConfig,
	IncidentRecord,
	LoopGuardState,
	ReasonCode,
	ResultClass,
	ToolDecision,
	ToolOutcome,
	ToolRequest,
	TransitionKind,
} from "./types.ts";
import { LOOP_GUARD_STATE_VERSION } from "./types.ts";

/** 判断精确动作是否已达到当前任务的执行配额。 */
export function quotaReached(entry: ActionLedgerEntry, repeatLimit: number): boolean {
	return entry.executions >= repeatLimit;
}

/**
 * 根据当前配额状态更新 entry.phase。
 * - quota-exhausted: 配额已满但尚未被挑战
 * - ready: 配额未满
 * 注意：block-challenged 只能由 evaluateToolRequest 设置，不会被此函数覆盖
 */
function syncPhase(entry: ActionLedgerEntry, repeatLimit: number): void {
	if (entry.phase === "block-challenged") return;
	entry.phase = quotaReached(entry, repeatLimit) ? "quota-exhausted" : "ready";
}

export function createInitialState(): LoopGuardState {
	return {
		version: LOOP_GUARD_STATE_VERSION,
		taskEpoch: 0,
		sequence: 0,
		latched: false,
		restored: false,
		ledger: new Map(),
		pendingCalls: new Map(),
		actionHistory: [],
		incidents: [],
		degradedSubsystems: new Set(),
		counters: {
			requestedCalls: 0,
			executedCalls: 0,
			blockedCalls: 0,
			terminalDecisions: 0,
			resultUpdates: 0,
			alreadyStartedSiblingResults: 0,
			responseFindings: 0,
			cycleFindings: 0,
			checkpointWrites: 0,
		},
	};
}

export function beginTask(
	current: LoopGuardState,
	timestamp: number,
	transition: "task-boundary" | "reset" = "task-boundary",
	maxIncidents = 32,
): EngineTransition<IncidentRecord> {
	const state = cloneState(current);
	state.sequence++;
	state.taskEpoch = state.taskEpoch === 0 ? 1 : state.taskEpoch + 1;
	state.latched = false;
	delete state.latchReason;
	delete state.latchIncidentId;
	delete state.compatibilityError;
	state.restored = false;
	delete state.restoredFrom;
	state.ledger.clear();
	state.pendingCalls.clear();
	state.actionHistory.length = 0;

	const incident = createIncident(state, transition, "allowed", timestamp);
	appendIncident(state, incident, maxIncidents);
	return { state, value: incident, checkpointRequired: true };
}

export function evaluateToolRequest(
	current: LoopGuardState,
	request: ToolRequest,
	config: EffectiveConfig,
): EngineTransition {
	const state = cloneState(current);
	state.sequence++;
	state.counters.requestedCalls++;
	if (state.taskEpoch === 0) state.taskEpoch = 1;

	if (config.enforcementMode === "off") {
		return {
			state,
			value: allowDecision(request.actionFingerprint, request.actionDigest, 0),
			checkpointRequired: false,
		};
	}

	if (state.latched) {
		state.counters.blockedCalls++;
		state.counters.terminalDecisions++;
		const challenge = findChallengeEntry(state);
		return {
			state,
			value: terminalDecision(
				state.latchReason === "checkpoint-incompatible"
					? "checkpoint-incompatible"
					: "task-latched",
				{
					incidentId: state.latchIncidentId,
					actionDigest: challenge?.digest,
					executionCount: challenge?.executions,
					taskEpoch: state.taskEpoch,
					latchReason: state.latchReason,
				},
			),
			checkpointRequired: false,
		};
	}

	const existingKey = findLedgerKey(state, request.actionFingerprint, request.actionDigest);
	const existing = existingKey ? state.ledger.get(existingKey) : undefined;
	if (existing?.phase === "block-challenged") {
		state.latched = true;
		state.latchReason = "block-defiance";
		state.counters.blockedCalls++;
		state.counters.terminalDecisions++;
		const incident = createIncident(
			state,
			"terminal-latch",
			"block-defiance",
			request.timestamp,
			existing.digest,
			existing.executions,
		);
		state.latchIncidentId = incident.id;
		appendIncident(state, incident, config.maxIncidents);
		return {
			state,
			value: {
				...terminalDecision("block-defiance", {
					incidentId: incident.id,
					actionDigest: existing.digest,
					executionCount: existing.executions,
					taskEpoch: state.taskEpoch,
					latchReason: "block-defiance",
				}),
				transition: "terminal-latch",
				actionFingerprint: request.actionFingerprint,
				actionDigest: existing.digest,
				executionCount: existing.executions,
				incident,
			},
			checkpointRequired: true,
		};
	}

	// 执行配额只由规范化后的精确动作和当前 task epoch 决定。
	// 工具结果仅用于诊断，不会因为输出变化而重置或放宽配额。
	if (existing && quotaReached(existing, config.repeatLimit)) {
		existing.phase = "block-challenged";
		existing.lastSequence = state.sequence;
		state.counters.blockedCalls++;
		const incident = createIncident(
			state,
			"quota-block",
			"exact-quota-exhausted",
			request.timestamp,
			existing.digest,
			existing.executions,
		);
		appendIncident(state, incident, config.maxIncidents);
		return {
			state,
			value: {
				allow: false,
				block: true,
				terminate: false,
				reasonCode: "exact-quota-exhausted",
				reason: buildReason("exact-quota-exhausted", {
					executionCount: existing.executions,
					actionDigest: existing.digest,
					incidentId: incident.id,
					taskEpoch: state.taskEpoch,
				}),
				transition: "quota-block",
				actionFingerprint: request.actionFingerprint,
				actionDigest: existing.digest,
				executionCount: existing.executions,
				incident,
			},
			checkpointRequired: true,
		};
	}

	if (state.pendingCalls.size >= config.maxPendingCalls) {
		return internalFailureTransition(state, request.timestamp, config, "pending-call-capacity");
	}
	if (!existing && state.ledger.size >= config.maxEntries && !evictOneLedgerEntry(state, config)) {
		return internalFailureTransition(state, request.timestamp, config, "action-ledger-capacity");
	}

	const entry = existing ?? {
		fingerprint: request.actionFingerprint,
		digest: request.actionDigest,
		toolName: request.toolName,
		executions: 0,
		phase: "ready",
		firstSequence: state.sequence,
		lastSequence: state.sequence,
		evidenceRevision: 0,
		noProgressCount: 0,
	};
	entry.fingerprint = request.actionFingerprint;
	entry.executions++;
	entry.lastSequence = state.sequence;
	syncPhase(entry, config.repeatLimit);
	if (existingKey && existingKey !== request.actionFingerprint) state.ledger.delete(existingKey);
	state.ledger.set(request.actionFingerprint, entry);
	state.pendingCalls.set(request.toolCallId, {
		toolCallId: request.toolCallId,
		actionFingerprint: request.actionFingerprint,
		taskEpoch: state.taskEpoch,
		sequence: state.sequence,
	});
	state.counters.executedCalls++;

	return {
		state,
		value: allowDecision(request.actionFingerprint, request.actionDigest, entry.executions),
		checkpointRequired: false,
	};
}

export function recordToolOutcome(
	current: LoopGuardState,
	outcome: ToolOutcome,
	config: EffectiveConfig,
): EngineTransition<undefined> {
	const state = cloneState(current);
	state.sequence++;
	const pending = state.pendingCalls.get(outcome.toolCallId);
	if (!pending) return { state, value: undefined, checkpointRequired: false };
	state.pendingCalls.delete(outcome.toolCallId);
	if (state.latched) state.counters.alreadyStartedSiblingResults++;
	if (pending.taskEpoch !== state.taskEpoch) {
		return { state, value: undefined, checkpointRequired: false };
	}

	const entry = state.ledger.get(pending.actionFingerprint);
	if (!entry) return { state, value: undefined, checkpointRequired: false };
	const changed =
		entry.lastResultFingerprint !== undefined &&
		entry.lastResultFingerprint !== outcome.resultFingerprint;
	if (changed) {
		entry.evidenceRevision++;
		entry.noProgressCount = 0;
	} else if (entry.lastResultFingerprint === outcome.resultFingerprint) {
		entry.noProgressCount++;
	}
	entry.lastResultFingerprint = outcome.resultFingerprint;
	entry.lastResultClass = outcome.resultClass;
	entry.lastSequence = state.sequence;
	// Major #1 fix: 结果变化可能改变配额状态，需要同步 phase
	// 例如：noProgressCount 从 >=limit 重置为 0，phase 应从 quota-exhausted 恢复为 ready
	syncPhase(entry, config.repeatLimit);
	state.counters.resultUpdates++;
	state.actionHistory.push({
		actionFingerprint: entry.fingerprint,
		actionDigest: entry.digest,
		resultFingerprint: outcome.resultFingerprint,
		evidenceRevision: entry.evidenceRevision,
		sequence: state.sequence,
	});
	while (state.actionHistory.length > config.maxCycleHistory) state.actionHistory.shift();
	return { state, value: undefined, checkpointRequired: false };
}

export function createInternalFailureTransition(
	current: LoopGuardState,
	timestamp: number,
	config: EffectiveConfig,
): EngineTransition {
	return internalFailureTransition(cloneState(current), timestamp, config, "adapter-failure");
}

export function createCompatibilityLatch(
	current: LoopGuardState,
	timestamp: number,
	config: EffectiveConfig,
): EngineTransition {
	const state = cloneState(current);
	state.sequence++;
	state.taskEpoch = Math.max(1, state.taskEpoch);
	state.latched = true;
	state.latchReason = "checkpoint-incompatible";
	state.compatibilityError = "checkpoint schema is not compatible";
	state.counters.blockedCalls++;
	state.counters.terminalDecisions++;
	const incident = createIncident(
		state,
		"incompatible-state",
		"checkpoint-incompatible",
		timestamp,
	);
	state.latchIncidentId = incident.id;
	appendIncident(state, incident, config.maxIncidents);
	return {
		state,
		value: {
			...terminalDecision("checkpoint-incompatible", {
				incidentId: incident.id,
				taskEpoch: state.taskEpoch,
				latchReason: "checkpoint-incompatible",
			}),
			transition: "incompatible-state",
			incident,
		},
		checkpointRequired: true,
	};
}

export function markDegraded(current: LoopGuardState, subsystem: string): LoopGuardState {
	const state = cloneState(current);
	state.degradedSubsystems.add(subsystem);
	return state;
}

export function cloneState(current: LoopGuardState): LoopGuardState {
	return {
		...current,
		ledger: new Map(
			[...current.ledger].map(([key, entry]) => [key, { ...entry }] as const),
		),
		pendingCalls: new Map(
			[...current.pendingCalls].map(([key, call]) => [key, { ...call }] as const),
		),
		actionHistory: current.actionHistory.map((item) => ({ ...item })),
		incidents: current.incidents.map((incident) => ({ ...incident })),
		degradedSubsystems: new Set(current.degradedSubsystems),
		counters: { ...current.counters },
	};
}

function internalFailureTransition(
	state: LoopGuardState,
	timestamp: number,
	config: EffectiveConfig,
	_subsystem: string,
): EngineTransition {
	state.sequence++;
	state.taskEpoch = Math.max(1, state.taskEpoch);
	state.latched = true;
	state.latchReason = "internal-failure";
	state.counters.blockedCalls++;
	state.counters.terminalDecisions++;
	const incident = createIncident(state, "internal-failure", "internal-failure", timestamp);
	state.latchIncidentId = incident.id;
	appendIncident(state, incident, config.maxIncidents);
	return {
		state,
		value: {
			...terminalDecision("internal-failure", {
				incidentId: incident.id,
				taskEpoch: state.taskEpoch,
				latchReason: "internal-failure",
			}),
			transition: "internal-failure",
			incident,
		},
		checkpointRequired: true,
	};
}

function findLedgerKey(
	state: LoopGuardState,
	fingerprint: string,
	digest: string,
): string | undefined {
	if (state.ledger.has(fingerprint)) return fingerprint;
	for (const [key, entry] of state.ledger) {
		if (entry.digest === digest) return key;
	}
	return undefined;
}

export function findChallengeEntry(state: LoopGuardState): ActionLedgerEntry | undefined {
	return [...state.ledger.values()].find((entry) => entry.phase === "block-challenged");
}

function evictOneLedgerEntry(state: LoopGuardState, config: EffectiveConfig): boolean {
	const candidate = [...state.ledger.entries()]
		.filter(([, entry]) => entry.phase === "ready" && !quotaReached(entry, config.repeatLimit))
		.sort((a, b) => a[1].lastSequence - b[1].lastSequence)[0];
	if (!candidate) return false;
	state.ledger.delete(candidate[0]);
	return true;
}

function appendIncident(state: LoopGuardState, incident: IncidentRecord, maxIncidents: number): void {
	state.incidents.push(incident);
	while (state.incidents.length > maxIncidents) state.incidents.shift();
}

function createIncident(
	state: LoopGuardState,
	transition: TransitionKind,
	reason: ReasonCode,
	timestamp: number,
	actionDigest?: string,
	executionCount?: number,
): IncidentRecord {
	return {
		version: 1,
		id: `lg-${state.taskEpoch}-${state.sequence}-${transition}`,
		transition,
		reason,
		taskEpoch: state.taskEpoch,
		sequence: state.sequence,
		timestamp,
		...(actionDigest ? { actionDigest } : {}),
		...(executionCount !== undefined ? { executionCount } : {}),
	};
}

function allowDecision(
	actionFingerprint: string,
	actionDigest: string,
	executionCount: number,
): ToolDecision {
	return {
		allow: true,
		block: false,
		terminate: false,
		reasonCode: "allowed",
		reason: "LoopGuard: action is within the task execution budget.",
		actionFingerprint,
		actionDigest,
		executionCount,
	};
}

interface ReasonContext {
	executionCount?: number;
	actionDigest?: string;
	incidentId?: string;
	taskEpoch?: number;
	latchReason?: ReasonCode;
}

function terminalDecision(reasonCode: ReasonCode, context: ReasonContext = {}): ToolDecision {
	return {
		allow: false,
		block: true,
		terminate: true,
		reasonCode,
		reason: buildReason(reasonCode, context),
		...(context.actionDigest ? { actionDigest: context.actionDigest } : {}),
		...(context.executionCount !== undefined ? { executionCount: context.executionCount } : {}),
	};
}


function buildReason(reason: ReasonCode, context: ReasonContext = {}): string {
	const action = formatActionReference(context.actionDigest) ?? "action:unavailable";
	const incident = context.incidentId ?? "unavailable";
	const epoch = context.taskEpoch ?? "unavailable";
	switch (reason) {
		case "exact-quota-exhausted":
			return `LoopGuard [exact-quota-exhausted]: ${action} already executed ${context.executionCount ?? "the maximum number of"} times in task epoch ${epoch}. It remains blocked until trusted interactive/RPC input or /loop-guard reset opens a new epoch; different actions do not clear this challenge. Requesting it again will terminate the current task. Incident: ${incident}.`;
		case "block-defiance":
			return `LoopGuard [block-defiance]: challenged ${action} was requested again after an explicit quota block. Task epoch ${epoch} is terminally latched and Pi termination was requested. Review /loop-guard explain ${incident}; then use trusted interactive/RPC input or /loop-guard reset after review.`;
		case "task-latched":
			return `LoopGuard [task-latched]: task epoch ${epoch} remains terminally latched by ${context.latchReason ?? "a prior terminal incident"}. No tool observed after the latch may execute. Original ${action}; incident: ${incident}. Review /loop-guard explain ${incident}, then use trusted interactive/RPC input or an explicit reset.`;
		case "checkpoint-incompatible":
			return `LoopGuard [checkpoint-incompatible]: saved safety state for task epoch ${epoch} cannot be restored safely. Incident: ${incident}. Load a compatible extension or review the incident before an explicit reset; reopening or forking does not clear this latch.`;
		case "internal-failure":
			return `LoopGuard [internal-failure]: the guard could not make or persist a trustworthy decision for task epoch ${epoch}, so this tool was blocked and the task was terminally latched. Incident: ${incident}. Inspect /loop-guard status and the degraded subsystem before resetting.`;
		default:
			return "LoopGuard: action is within the task execution budget.";
	}
}

export function outcomeClassIsFailure(resultClass: ResultClass): boolean {
	return resultClass === "error" || resultClass === "failure-text";
}
