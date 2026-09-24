export const LOOP_GUARD_STATE_VERSION = 1 as const;
export const LOOP_GUARD_CHECKPOINT_VERSION = 1 as const;

export type EnforcementMode = "enforce" | "off";
export type AdvisoryMode = "observe" | "off";

export type ReasonCode =
	| "allowed"
	| "exact-quota-exhausted"
	| "block-defiance"
	| "task-latched"
	| "internal-failure"
	| "checkpoint-incompatible";

export type TransitionKind =
	| "task-boundary"
	| "quota-block"
	| "terminal-latch"
	| "internal-failure"
	| "reset"
	| "incompatible-state";

export type ResultClass = "success" | "error" | "failure-text" | "empty";
export type ActionPhase = "ready" | "quota-exhausted" | "block-challenged";

export interface EffectiveConfig {
	enforcementMode: EnforcementMode;
	advisoryMode: AdvisoryMode;
	repeatLimit: number;
	failureLimit: number;
	responseRepeatLimit: number;
	responseSimilarityThreshold: number;
	windowMs: number;
	maxEntries: number;
	maxPendingCalls: number;
	maxIncidents: number;
	maxResponses: number;
	maxCycleHistory: number;
	minResponseChars: number;
	contextMaxMessages: number;
	contextMaxChars: number;
	checkpointScanLimit: number;
	warnings: string[];
}

export interface ActionLedgerEntry {
	fingerprint: string;
	digest: string;
	toolName: string;
	executions: number;
	phase: ActionPhase;
	firstSequence: number;
	lastSequence: number;
	lastResultFingerprint?: string;
	lastResultClass?: ResultClass;
	evidenceRevision: number;
	noProgressCount: number;
}

export interface PendingToolCall {
	toolCallId: string;
	actionFingerprint: string;
	taskEpoch: number;
	sequence: number;
}

export interface ActionResultObservation {
	actionFingerprint: string;
	actionDigest: string;
	resultFingerprint?: string;
	evidenceRevision: number;
	sequence: number;
}

export interface GuardCounters {
	requestedCalls: number;
	executedCalls: number;
	blockedCalls: number;
	terminalDecisions: number;
	resultUpdates: number;
	alreadyStartedSiblingResults: number;
	responseFindings: number;
	cycleFindings: number;
	checkpointWrites: number;
}

export interface IncidentRecord {
	version: 1;
	id: string;
	transition: TransitionKind;
	reason: ReasonCode;
	taskEpoch: number;
	sequence: number;
	timestamp: number;
	actionDigest?: string;
	executionCount?: number;
	count?: number;
}

export interface LoopGuardState {
	version: typeof LOOP_GUARD_STATE_VERSION;
	taskEpoch: number;
	sequence: number;
	latched: boolean;
	latchReason?: ReasonCode;
	latchIncidentId?: string;
	restored: boolean;
	restoredFrom?: "startup" | "reload" | "resume" | "fork" | "tree";
	compatibilityError?: string;
	digestSalt?: string;
	ledger: Map<string, ActionLedgerEntry>;
	pendingCalls: Map<string, PendingToolCall>;
	actionHistory: ActionResultObservation[];
	incidents: IncidentRecord[];
	degradedSubsystems: Set<string>;
	counters: GuardCounters;
}

export interface ToolDecision {
	allow: boolean;
	block: boolean;
	terminate: boolean;
	reasonCode: ReasonCode;
	reason: string;
	transition?: TransitionKind;
	actionFingerprint?: string;
	actionDigest?: string;
	executionCount?: number;
	incident?: IncidentRecord;
}

export interface EngineTransition<T = ToolDecision> {
	state: LoopGuardState;
	value: T;
	checkpointRequired: boolean;
}

export interface ToolRequest {
	toolCallId: string;
	toolName: string;
	actionFingerprint: string;
	actionDigest: string;
	timestamp: number;
}

export interface ToolOutcome {
	toolCallId: string;
	resultFingerprint: string;
	resultClass: ResultClass;
	timestamp: number;
}

export interface CheckpointLedgerEntry {
	actionDigest: string;
	executions: number;
	phase: ActionPhase;
	evidenceRevision: number;
	noProgressCount: number;
}

export interface LoopGuardCheckpointV1 {
	version: typeof LOOP_GUARD_CHECKPOINT_VERSION;
	transition: TransitionKind;
	reason: ReasonCode;
	taskEpoch: number;
	sequence: number;
	timestamp: number;
	digestSalt: string;
	latched: boolean;
	latchReason?: ReasonCode;
	latchIncidentId?: string;
	counters: GuardCounters;
	challenge?: CheckpointLedgerEntry;
	incident?: IncidentRecord;
}

export type ActionReference = `action:${string}`;

export type IncidentSelection =
	| { kind: "latest" }
	| { kind: "incident-id"; incidentId: string };

export type ExplanationCompleteness = "complete" | "partial" | "unavailable";
export type ResultEvidence = "stable" | "changed" | "insufficient" | "unavailable";
export type ExplanationObservationKind =
	| "matching-execution"
	| "quota-block"
	| "terminal-defiance"
	| "intervening-action"
	| "unpaired-request";

export type StructuralValueKind =
	| "array"
	| "boolean"
	| "null"
	| "number"
	| "object"
	| "string"
	| "undefined";

export interface StructuralFieldSummary {
	name: string;
	kind: StructuralValueKind;
	length?: number;
	lines?: number;
	keys?: string[];
}

export interface StructuralInputSummary {
	toolName: string;
	fields: StructuralFieldSummary[];
}

export interface ExplanationObservation {
	kind: ExplanationObservationKind;
	branchIndex: number;
	toolCallId?: string;
	toolName: string;
	actionReference: ActionReference;
	input: StructuralInputSummary;
	resultClass?: ResultClass;
	resultFingerprint?: string;
}

export interface IncidentExplanation {
	completeness: ExplanationCompleteness;
	incident: IncidentRecord;
	actionReference?: ActionReference;
	executionCount?: number;
	resultEvidence: ResultEvidence;
	observations: ExplanationObservation[];
	missing: string[];
	scannedEntries: number;
}

export type IncidentExplanationResult =
	| { kind: "explained"; explanation: IncidentExplanation }
	| { kind: "not-found"; incidentId?: string; scannedEntries: number }
	| {
			kind: "unavailable";
			incident: IncidentRecord;
			actionReference?: ActionReference;
			reason: string;
			scannedEntries: number;
	  };

export interface TerminalReportView {
	transition: TransitionKind;
	reason: ReasonCode;
	incidentId: string;
	taskEpoch: number;
	actionReference?: ActionReference;
	executionCount?: number;
	collapsedLines: string[];
	expandedLines: string[];
}

export type LoopGuardPresentationMode = "tui" | "rpc" | "json" | "print";

export interface RestorationActivationKey {
	sessionId: string;
	leafId: string | null;
	incidentId: string;
}

export interface ResponseObservation {
	fingerprint: string;
	grams: Set<string>;
	length: number;
	sequence: number;
}

export interface AdvisoryFinding {
	type: "response-similarity" | "action-cycle";
	key: string;
	score?: number;
	period?: 1 | 2 | 3;
	count: number;
	sequence: number;
	coverage?: "assistant-visible-text-only";
}
