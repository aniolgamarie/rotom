import { mayTransformHistory } from "@agentcfg/pi-runtime/capability-policy";
/**
 * Deterministic, fail-closed loop guard for Pi.
 *
 * Enforcement decisions live in pure modules. This entry point only translates
 * Pi events, commits state, persists recovery checkpoints, and renders bounded
 * best-effort diagnostics.
 */

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { formatActionReference } from "./action-reference.ts";
import { AdvisoryTracker } from "./advisory.ts";
import { readLoopGuardConfig } from "./config.ts";
import { compactRepeatedToolHistory } from "./context.ts";
import {
	formatActiveLatchStatus,
	formatLoopGuardStatus,
	minimalStatusFallback,
} from "./diagnostics.ts";
import {
	beginTask,
	cloneState,
	createCompatibilityLatch,
	createInitialState,
	createInternalFailureTransition,
	evaluateToolRequest,
	markDegraded,
	recordToolOutcome,
} from "./engine.ts";
import {
	explainIncident,
	formatIncidentExplanation,
	parseIncidentSelection,
} from "./explanation.ts";
import {
	actionFingerprint,
	classifyResult,
	createSessionSalt,
	resultFingerprint,
	sessionScopedDigest,
} from "./fingerprint.ts";
import {
	appendCheckpoint,
	restoreCheckpointFromBranch,
} from "./persistence.ts";
import { registerTerminalCheckpointRenderer } from "./renderer.ts";
import {
	buildTerminalReport,
	buildTerminalReportFromState,
	formatTerminalNotification,
	restorationActivationKey,
} from "./terminal-report.ts";
import type {
	AdvisoryFinding,
	EffectiveConfig,
	EngineTransition,
	IncidentRecord,
	LoopGuardState,
	ToolDecision,
} from "./types.ts";

export interface LoopGuardDependencies {
	config?: EffectiveConfig;
	now?: () => number;
	evaluateRequest?: typeof evaluateToolRequest;
	recordOutcome?: typeof recordToolOutcome;
	appendCheckpoint?: typeof appendCheckpoint;
	restoreCheckpoint?: typeof restoreCheckpointFromBranch;
	compactContext?: typeof compactRepeatedToolHistory;
	advisory?: AdvisoryTracker;
}

export function installLoopGuard(
	pi: ExtensionAPI,
	dependencies: LoopGuardDependencies = {},
): void {
	registerTerminalCheckpointRenderer(pi);
	let config = cloneConfig(dependencies.config ?? readLoopGuardConfig());
	let state = createInitialState();
	let lastLiveTerminalIncidentId: string | undefined;
	let lastRestoredActivationKey: string | undefined;
	let latchStatusPublished = false;
	const advisory = dependencies.advisory ?? new AdvisoryTracker();
	const now = dependencies.now ?? Date.now;
	const evaluateRequest = dependencies.evaluateRequest ?? evaluateToolRequest;
	const recordOutcome = dependencies.recordOutcome ?? recordToolOutcome;
	const persist = dependencies.appendCheckpoint ?? appendCheckpoint;
	const restore = dependencies.restoreCheckpoint ?? restoreCheckpointFromBranch;
	const compactContext = dependencies.compactContext ?? compactRepeatedToolHistory;

	function commit(next: LoopGuardState): void {
		state = next;
	}

	function clearPresentationDedupe(): void {
		lastLiveTerminalIncidentId = undefined;
		lastRestoredActivationKey = undefined;
	}

	function markPresentationDegraded(subsystem: string): void {
		commit(markDegraded(state, subsystem));
	}

	function syncLatchStatus(ctx: ExtensionContext): void {
		if (!ctx.hasUI) return;
		const status = formatActiveLatchStatus(config, state);
		if (status === undefined && !latchStatusPublished) return;
		try {
			ctx.ui.setStatus("loop-guard", status);
			latchStatusPublished = status !== undefined;
		} catch {
			markPresentationDegraded("latch-status");
		}
	}

	function notifyPresentation(
		ctx: ExtensionContext,
		message: string,
		type: "info" | "warning" | "error",
		subsystem: string,
	): void {
		if (!ctx.hasUI) return;
		try {
			ctx.ui.notify(message, type);
		} catch {
			markPresentationDegraded(subsystem);
		}
	}

	function presentLiveTerminal(
		ctx: ExtensionContext,
		decision: ToolDecision,
		checkpointPersisted: boolean,
	): void {
		syncLatchStatus(ctx);
		const incident = decision.incident;
		if (!incident || lastLiveTerminalIncidentId === incident.id) return;
		lastLiveTerminalIncidentId = incident.id;
		const report = buildTerminalReportFromState(state, incident);
		if (!report) return;
		if (ctx.mode === "tui" && checkpointPersisted) return;
		if (ctx.mode === "rpc" || (ctx.mode === "tui" && !checkpointPersisted)) {
			notifyPresentation(ctx, formatTerminalNotification(report), "error", "terminal-notification");
		}
	}

	function presentRestoredLatch(
		ctx: ExtensionContext,
		checkpoint?: unknown,
	): void {
		syncLatchStatus(ctx);
		if (!state.latched || !state.latchIncidentId) {
			lastRestoredActivationKey = undefined;
			return;
		}
		const key = restorationActivationKey(
			ctx.sessionManager.getSessionId(),
			ctx.sessionManager.getLeafId(),
			state.latchIncidentId,
		);
		if (lastRestoredActivationKey === key) return;
		lastRestoredActivationKey = key;
		const incident = state.incidents.find((item) => item.id === state.latchIncidentId);
		const report = buildTerminalReport(checkpoint) ?? buildTerminalReportFromState(state, incident);
		if (!report) {
			notifyPresentation(ctx, minimalStatusFallback(state), "error", "restored-notification");
			return;
		}
		notifyPresentation(
			ctx,
			formatTerminalNotification(report, true),
			"warning",
			"restored-notification",
		);
	}

	function ensureDigestSalt(sessionId: string, replace = false): void {
		if (!replace && state.digestSalt) return;
		const next = cloneState(state);
		next.digestSalt = createSessionSalt(sessionId);
		commit(next);
	}

	function commitRequired(transition: EngineTransition<IncidentRecord>): void {
		commit(transition.state);
		if (transition.checkpointRequired) commit(persist(pi, state, transition.value));
	}

	function persistDecision(transition: EngineTransition): void {
		commit(transition.state);
		if (transition.checkpointRequired && transition.value.incident) {
			commit(persist(pi, state, transition.value.incident));
		}
	}

	function enterInternalFailure(timestamp: number): {
		decision: ToolDecision;
		checkpointPersisted: boolean;
	} {
		const failure = createInternalFailureTransition(state, timestamp, config);
		commit(failure.state);
		let checkpointPersisted = false;
		if (failure.value.incident) {
			try {
				commit(persist(pi, state, failure.value.incident));
				checkpointPersisted = true;
			} catch {
				commit(markDegraded(state, "checkpoint"));
			}
		}
		return { decision: failure.value, checkpointPersisted };
	}

	function initializeFreshSession(ctx: ExtensionContext): void {
		state = createInitialState();
		clearPresentationDedupe();
		ensureDigestSalt(ctx.sessionManager.getSessionId(), true);
		try {
			commitRequired(beginTask(state, now(), "task-boundary", config.maxIncidents));
		} catch {
			const failure = enterInternalFailure(now());
			presentLiveTerminal(ctx, failure.decision, failure.checkpointPersisted);
		}
		advisory.reset();
		syncLatchStatus(ctx);
	}

	function restoreActiveBranch(
		ctx: ExtensionContext,
		source: LoopGuardState["restoredFrom"],
	): void {
		const restored = restore(ctx.sessionManager.getBranch(), config, source, ctx.cwd);
		if (restored.kind === "restored") {
			commit(restored.state);
			advisory.reset();
			presentRestoredLatch(ctx, restored.checkpoint);
			return;
		}
		if (restored.kind === "incompatible") {
			state = createInitialState();
			ensureDigestSalt(ctx.sessionManager.getSessionId(), true);
			const failure = createCompatibilityLatch(state, now(), config);
			commit(failure.state);
			if (failure.value.incident) {
				try {
					commit(persist(pi, state, failure.value.incident));
				} catch {
					commit(markDegraded(state, "checkpoint"));
				}
			}
			presentRestoredLatch(ctx);
			return;
		}
		initializeFreshSession(ctx);
	}

	pi.on("session_start", (event, ctx) => {
		if (event.reason === "new") {
			initializeFreshSession(ctx);
			return;
		}
		const source =
			event.reason === "reload"
				? "reload"
				: event.reason === "resume"
					? "resume"
					: event.reason === "fork"
						? "fork"
						: "startup";
		restoreActiveBranch(ctx, source);
	});

	pi.on("session_tree", (_event, ctx) => {
		restoreActiveBranch(ctx, "tree");
	});

	pi.on("input", (event, ctx) => {
		if (event.source !== "interactive" && event.source !== "rpc") return undefined;
		ensureDigestSalt(ctx.sessionManager.getSessionId());
		clearPresentationDedupe();
		try {
			commitRequired(beginTask(state, now(), "task-boundary", config.maxIncidents));
			advisory.reset();
		} catch {
			const failure = enterInternalFailure(now());
			presentLiveTerminal(ctx, failure.decision, failure.checkpointPersisted);
		}
		syncLatchStatus(ctx);
		return undefined;
	});

	pi.on("tool_call", (event, ctx) => {
		if (config.enforcementMode === "off") return undefined;
		const timestamp = now();
		let transition: EngineTransition;
		try {
			ensureDigestSalt(ctx.sessionManager.getSessionId());
			const input = asRecord(event.input);
			const fingerprint = actionFingerprint(event.toolName, input, ctx.cwd);
			const digest = sessionScopedDigest(fingerprint, state.digestSalt!);
			transition = evaluateRequest(
				state,
				{
					toolCallId: event.toolCallId,
					toolName: event.toolName,
					actionFingerprint: fingerprint,
					actionDigest: digest,
					timestamp,
				},
				config,
			);
			persistDecision(transition);
		} catch {
			const failure = enterInternalFailure(timestamp);
			presentLiveTerminal(ctx, failure.decision, failure.checkpointPersisted);
			return { block: true, reason: failure.decision.reason, terminate: true };
		}

		if (!transition.value.block) return undefined;
		if (transition.value.terminate) {
			presentLiveTerminal(ctx, transition.value, transition.checkpointRequired);
			return { block: true, reason: transition.value.reason, terminate: true };
		}

		if (ctx.hasUI) {
			try {
				ctx.ui.notify(
					`LoopGuard quota block: ${formatActionReference(transition.value.actionDigest) ?? "action:unavailable"} · incident ${transition.value.incident?.id ?? "unavailable"}`,
					"warning",
				);
			} catch {
				const failure = enterInternalFailure(timestamp);
				presentLiveTerminal(ctx, failure.decision, failure.checkpointPersisted);
				return { block: true, reason: failure.decision.reason, terminate: true };
			}
		}
		return { block: true, reason: transition.value.reason, terminate: false };
	});

	pi.on("tool_result", (event) => {
		if (config.enforcementMode === "off" && config.advisoryMode === "off") return undefined;
		try {
			const transition = recordOutcome(
				state,
				{
					toolCallId: event.toolCallId,
					resultFingerprint: resultFingerprint(event.content),
					resultClass: classifyResult(event.content, event.isError),
					timestamp: now(),
				},
				config,
			);
			commit(transition.state);
			if (config.advisoryMode === "observe") {
				const finding = advisory.observeCycle(state.actionHistory, state.sequence);
				if (finding) recordAdvisoryFinding(finding);
			}
		} catch {
			commit(markDegraded(state, "tool-result-observation"));
		}
		return undefined;
	});

	pi.on("message_end", (event, ctx) => {
		if (config.advisoryMode !== "observe" || event.message.role !== "assistant") return undefined;
		try {
			const analysis = advisory.observeResponse(visibleMessageText(event.message), state.sequence, config);
			if (analysis.finding) {
				recordAdvisoryFinding(analysis.finding);
				if (ctx.hasUI) {
					try {
						ctx.ui.notify(
							`LoopGuard advisory: repeated response (${Math.round((analysis.finding.score ?? 0) * 100)}%)`,
							"warning",
						);
					} catch {
						commit(markDegraded(state, "advisory-ui"));
					}
				}
			}
		} catch {
			commit(markDegraded(state, "response-observation"));
		}
		return undefined;
	});

	pi.on("context", (event, ctx) => {
    if (!mayTransformHistory((globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")])) return undefined;
		if (config.enforcementMode === "off" && config.advisoryMode === "off") return undefined;
		try {
			const compacted = compactContext(event.messages, ctx.cwd, config);
			if (compacted.prunedMessages === 0 && compacted.truncatedChars === 0) return undefined;
			return { messages: compacted.messages };
		} catch {
			commit(markDegraded(state, "context-compaction"));
			return undefined;
		}
	});

	pi.registerCommand("loop-guard", {
		description: "Show, explain, reset, enable, or disable loop guard state",
		handler: async (args, ctx) => {
			const rawAction = args.trim();
			const action = rawAction.toLowerCase();
			if (action === "explain" || action.startsWith("explain ")) {
				try {
					const selection = parseIncidentSelection(rawAction.slice("explain".length));
					const result = explainIncident(
						ctx.sessionManager.getBranch(),
						selection,
						ctx.cwd,
						config.checkpointScanLimit,
					);
					notifyCommand(ctx, formatIncidentExplanation(result), result.kind === "not-found" ? "warning" : "info");
				} catch {
					markPresentationDegraded("incident-explanation");
					notifyCommand(ctx, minimalStatusFallback(state), "error");
				}
				return;
			}
			if (action === "reset") {
				ensureDigestSalt(ctx.sessionManager.getSessionId());
				clearPresentationDedupe();
				try {
					commitRequired(beginTask(state, now(), "reset", config.maxIncidents));
					advisory.reset();
					notifyCommand(ctx, "Loop guard reset", "info");
				} catch {
					const failure = enterInternalFailure(now());
					presentLiveTerminal(ctx, failure.decision, failure.checkpointPersisted);
					notifyCommand(ctx, minimalStatusFallback(state), "error");
				}
				syncLatchStatus(ctx);
				return;
			}
			if (action === "off" || action === "disable") {
				config = { ...config, enforcementMode: "off" };
				notifyCommand(ctx, "Loop guard deterministic enforcement disabled", "warning");
				syncLatchStatus(ctx);
				return;
			}
			if (action === "on" || action === "enable") {
				config = { ...config, enforcementMode: "enforce" };
				notifyCommand(ctx, "Loop guard deterministic enforcement enabled", "info");
				syncLatchStatus(ctx);
				return;
			}
			if (action === "response-off") {
				config = { ...config, advisoryMode: "off" };
				notifyCommand(ctx, "Loop guard advisory observation disabled", "info");
				return;
			}
			if (action === "response-on") {
				config = { ...config, advisoryMode: "observe" };
				notifyCommand(ctx, "Loop guard advisory observation enabled", "info");
				return;
			}

			notifyCommand(ctx, formatLoopGuardStatus(config, state, advisory.summary()), "info");
		},
	});

	function recordAdvisoryFinding(finding: AdvisoryFinding): void {
		const next = cloneState(state);
		if (finding.type === "response-similarity") next.counters.responseFindings++;
		else next.counters.cycleFindings++;
		commit(next);
	}

	function notifyCommand(
		ctx: ExtensionContext,
		message: string,
		type: "info" | "warning" | "error",
	): void {
		try {
			ctx.ui.notify(message, type);
		} catch {
			commit(markDegraded(state, "command-ui"));
			try {
				ctx.ui.setStatus("loop-guard", minimalStatusFallback(state));
			} catch {
				commit(markDegraded(state, "command-status"));
			}
		}
	}
}

export default function loopGuard(pi: ExtensionAPI): void {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") throw new Error("AGENTCFG_RUNTIME_REQUIRED");
	installLoopGuard(pi);
}

function cloneConfig(config: EffectiveConfig): EffectiveConfig {
	return { ...config, warnings: [...config.warnings] };
}

function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function visibleMessageText(message: AgentMessage): string {
	const content = (message as unknown as { content?: unknown }).content;
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.map((part) => {
			if (!part || typeof part !== "object" || !("text" in part)) return "";
			return String((part as { text?: unknown }).text ?? "");
		})
		.join("\n");
}
