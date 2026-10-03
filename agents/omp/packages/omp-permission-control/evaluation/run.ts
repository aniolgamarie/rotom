import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { COVERAGE_REASONS, PermissionLedger, type ExecutionBinding } from "../controller";
import { assessBeforeReview, synthesizeReview, type PolicyInput } from "../policy";
import { buildReviewRequest, decodeReview, ReviewContractError, reviewWithFallback, type ModelReply,
  type ModelReview, type ReviewClock, type ReviewRequest, type ReviewServices } from "../reviewer";
import type { ShellEffect } from "../shell-analysis";
import { readFrozenFixture } from "./fixtures";
import { buildEvaluationReport, type EvaluationCase, type EvaluationChecks,
  type EvaluationIdentity, type EvaluationResult, type EvaluationUnverifiedReason,
  type MechanicalCaseObservation, type MechanicalFault } from "./report";

type Transport = "anthropic-messages" | "openai-completions";
type NativeRule = "explicit-deny" | "command-prompt" | "critical-safety" | "native-allow" |
  "tool-default" | "tier-default" | "compound-structural" | "not-applicable";
interface FrozenMessage {
  messageId: string;
  role: "user";
  text: string;
  sourceProof: { channel: string; authenticated: boolean; synthetic: boolean };
}
interface FrozenEvent { eventId: string; atMs: number; type: string; subject: string; value: string }
interface FrozenAction {
  kind: "bash" | "state-sequence";
  command?: string;
  compound: boolean;
  platform: string;
  shell: string;
  cwdCategory: ShellEffect["cwdCategory"];
  nativeRule: NativeRule;
  effects: ShellEffect[];
  events?: FrozenEvent[];
}
interface FrozenCase {
  id: string;
  category: EvaluationCase["category"];
  action: FrozenAction;
  userContext: {
    contextComplete: boolean;
    generation: number;
    messages: FrozenMessage[];
    requestSourceProof: { channel: string; authenticated: boolean; synthetic: boolean };
    structuredRestrictions: string[];
  };
  evidenceExpectation?: { mode: string; issue: string };
}

interface CommonOptions {
  repositoryRoot: string;
  fixtureDirectory: string;
  platform: string;
}
export type RunEvaluationOptions = CommonOptions & ({ mode: "fake" } | {
  mode: "real";
  provider: string;
  model: string;
  transport: Transport;
  services: ReviewServices;
});
type EvaluationSelection = CommonOptions & ({ mode: "fake" } | {
  mode: "real"; provider: string; model: string; transport: Transport;
});
export interface EvaluationCliDependencies {
  loadServiceModule?: (absolutePath: string) => Promise<unknown>;
  writeOutput?: (path: string, bytes: string) => void;
  stdout?: (bytes: string) => void;
}

const ROOT = resolve(import.meta.dir, "../../../../..");
const FIXTURES = resolve(ROOT, "tests/fixtures/omp/permission-control");
const SOURCE_PATHS = [
  "agents/omp/packages/omp-permission-control/types.ts",
  "agents/omp/packages/omp-permission-control/shell-analysis.ts",
  "agents/omp/packages/omp-permission-control/policy.ts",
  "agents/omp/packages/omp-permission-control/reviewer.ts",
  "agents/omp/packages/omp-permission-control/controller.ts",
  "agents/omp/packages/omp-permission-control/evaluation/fixtures.ts",
  "agents/omp/packages/omp-permission-control/evaluation/report.ts",
  "agents/omp/packages/omp-permission-control/evaluation/run.ts",
] as const;
const NULL_CHECKS: EvaluationChecks = { stalePermitUses: null, tinyAllows: null, downloads: null,
  automaticMs: null, cancelLatencyMs: null, statusComplete: null, secretLeaks: null,
  deliveryResidues: null };
const NULL_REASONS: EvaluationUnverifiedReason[] = ["stale-permit-not-observed",
  "tiny-allow-not-observed", "download-not-observed", "automatic-deadline-not-observed",
  "cancel-latency-not-observed", "status-not-observed", "secret-leak-not-observed",
  "delivery-residue-not-observed"];

function invalid(): never { throw new Error("INVALID_EVALUATION_ARGUMENTS"); }
function within(path: string, root: string): boolean {
  const child = relative(resolve(root), resolve(path));
  return child === "" || !child.startsWith("..") && !isAbsolute(child);
}
function digestBytes(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}
function regular(path: string): Uint8Array {
  try {
    const status = lstatSync(path);
    if (!status.isFile() || status.isSymbolicLink()) invalid();
    return readFileSync(path);
  } catch { return invalid(); }
}
function namedDigest(root: string, paths: readonly string[]): string {
  const hash = createHash("sha256");
  for (const name of paths) {
    if (!name || name.startsWith("/") || name.split("/").includes("..")) invalid();
    hash.update(name); hash.update("\0"); hash.update(regular(join(root, name))); hash.update("\0");
  }
  return hash.digest("hex");
}
function pluginDigest(repositoryRoot: string): string {
  const pluginRoot = join(repositoryRoot, "agents/omp/packages/omp-permission-control");
  const entries: { path: string; target: string; sha256: string; executable: boolean }[] = [];
  const visit = (directory: string): void => {
    let names: string[];
    try { names = readdirSync(directory).sort(); } catch { return invalid(); }
    for (const name of names) {
      const path = join(directory, name);
      let status;
      try { status = lstatSync(path); } catch { return invalid(); }
      if (status.isSymbolicLink()) invalid();
      if (status.isDirectory()) visit(path);
      else if (status.isFile()) {
        const pluginRelative = relative(pluginRoot, path).split("\\").join("/");
        const repositoryRelative = relative(repositoryRoot, path).split("\\").join("/");
        entries.push({ path: repositoryRelative,
          target: `packages/omp-permission-control/${pluginRelative}`,
          sha256: digestBytes(readFileSync(path)), executable: Boolean(status.mode & 0o111) });
      } else invalid();
    }
  };
  visit(pluginRoot);
  if (!entries.length) invalid();
  entries.sort((left, right) => Buffer.compare(Buffer.from(left.path, "utf8"),
    Buffer.from(right.path, "utf8")));
  // 字段顺序与 Python json.dumps(sort_keys=True,separators=(",",":")) 一致。
  const canonical = entries.map(entry => ({ executable: entry.executable, path: entry.path,
    sha256: entry.sha256, target: entry.target }));
  return digestBytes(`${JSON.stringify(canonical)}\n`);
}
function hostDigest(repositoryRoot: string): string {
  const root = "agents/omp/patches/permission-control";
  const seriesBytes = regular(join(repositoryRoot, root, "series"));
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let names: string[];
  try { names = decoder.decode(seriesBytes).trimEnd().split("\n"); } catch { return invalid(); }
  if (!names.length || new Set(names).size !== names.length ||
      names.some(name => !/^[a-zA-Z0-9._-]+\.patch$/u.test(name))) invalid();
  return namedDigest(repositoryRoot, [`${root}/series`, ...names.map(name => `${root}/${name}`)]);
}
function identity(options: EvaluationSelection, fixtureDigest: string): EvaluationIdentity {
  const root = resolve(options.repositoryRoot);
  if (!isAbsolute(options.repositoryRoot) || !isAbsolute(options.fixtureDirectory)) invalid();
  const result: EvaluationIdentity = {
    mode: options.mode,
    provider: options.mode === "fake" ? "fixture-fake" : options.provider,
    model: options.mode === "fake" ? "fixed-conservative-ask" : options.model,
    transport: options.mode === "fake" ? "fake" : options.transport,
    platform: options.platform,
    sourceDigest: namedDigest(root, SOURCE_PATHS),
    policyDigest: digestBytes(regular(join(root,
      "agents/omp/packages/omp-permission-control/policy.ts"))),
    fixtureDigest,
    pluginDigest: pluginDigest(root),
    hostDigest: hostDigest(root),
  };
  return result;
}

function frozenCase(value: unknown): FrozenCase {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const item = value as Record<string, unknown>;
  const action = item.action as FrozenAction;
  const user = item.userContext as FrozenCase["userContext"];
  if (typeof item.id !== "string" || !["policy-safe", "ask-deny", "fault-state"].includes(item.category as string) ||
      !action || !["bash", "state-sequence"].includes(action.kind) || !Array.isArray(action.effects) ||
      !user || !Array.isArray(user.messages) || !Array.isArray(user.structuredRestrictions)) invalid();
  return item as unknown as FrozenCase;
}
function nativeConstraint(rule: NativeRule): PolicyInput["nativeConstraints"][number] {
  if (rule === "explicit-deny") return { source: "explicit-deny", policy: "deny" };
  if (rule === "command-prompt") return { source: "command-prompt", policy: "prompt" };
  if (rule === "critical-safety") return { source: "critical-safety", policy: "prompt" };
  if (rule === "native-allow") return { source: "native-allow", policy: "allow" };
  if (rule === "not-applicable") return { source: "unknown", policy: "prompt" };
  return { source: rule, policy: "prompt" };
}
function trustedSource(source: unknown): source is FrozenMessage["sourceProof"] {
  if (!source || typeof source !== "object" || Array.isArray(source)) return false;
  const proof = source as Record<string, unknown>;
  return proof.authenticated === true && proof.synthetic === false && proof.channel === "interactive-user";
}
function trustedMessages(item: FrozenCase): FrozenMessage[] {
  return item.userContext.messages.filter(message => Boolean(message) && typeof message === "object" &&
    message.role === "user" && trustedSource(message.sourceProof));
}
function contextComplete(item: FrozenCase): boolean {
  return item.userContext.contextComplete && trustedSource(item.userContext.requestSourceProof) &&
    trustedMessages(item).length === item.userContext.messages.length;
}
function restriction(item: FrozenCase, name: string): PolicyInput["restrictionFacts"]["structuredRestrictions"][number] {
  const kinds = new Set(item.action.effects.map(effect => effect.kind));
  const prohibited: Readonly<Record<string, ShellEffect["kind"]>> = {
    "read-only": "write", "no-network": "network-send", "no-delete": "delete",
    "no-secrets": "secret-access", "no-device": "device-access",
  };
  if (name === "read-only") {
    const satisfied = item.action.effects.every(effect => effect.kind === "read");
    return { verified: true, result: satisfied ? "satisfied" : "conflicting" };
  }
  const kind = prohibited[name];
  if (kind) return { verified: true, result: kinds.has(kind) ? "conflicting" : "satisfied" };
  // allow-write 等自然语言许可不是本 runner 能机械证明的限制。
  return { verified: false, result: "unknown" };
}
function policyInput(item: FrozenCase): PolicyInput {
  const complete = contextComplete(item);
  return {
    mode: "smart", effects: item.action.effects, analysisComplete: item.action.kind === "bash",
    nativeConstraints: [nativeConstraint(item.action.nativeRule)], restrictionFacts: {
      generation: item.userContext.generation, currentGeneration: item.userContext.generation,
      contextComplete: complete, uninterpretedUserText: item.userContext.messages.length > 0,
      structuredRestrictions: item.userContext.structuredRestrictions.map(name => restriction(item, name)),
    }, hardProhibited: false,
    mechanical: { coverageVerified: true, healthVerified: true, contextComplete: complete,
      redactionComplete: true, targetProofVerified: true, generationVerified: true },
  };
}
class EvaluationClock implements ReviewClock {
  time = 0;
  now = () => this.time;
  timer = (_callback: () => void, _milliseconds: number) => () => {};
}
class MonotonicClock implements ReviewClock {
  now = () => performance.now();
  timer = (callback: () => void, milliseconds: number) => {
    const timer = setTimeout(callback, milliseconds);
    return () => clearTimeout(timer);
  };
}
function fixedAsk(effectIds: readonly string[]): ModelReply {
  return { status: "ok", text: JSON.stringify({ decision: "ask", risk: "unknown",
    authorization: "unknown", effects: [...effectIds], unknowns: ["ambiguous-authorization"],
    reasonCode: "USER_CONFIRMATION_REQUIRED", evidence: { userMessageIds: [], bindings: [] } }),
    outputTokens: 32, toolCalls: [] };
}
export function createEvaluationReviewBoundary(options: Pick<RunEvaluationOptions, "mode"> &
    Partial<Pick<Extract<RunEvaluationOptions, { mode: "real" }>, "services">>): ReviewServices {
  const calls = new Set<string>();
  return {
    reviewOnce: async call => {
      if (calls.has(call.requestId)) throw new Error("EVALUATION_REVIEW_REPEATED");
      calls.add(call.requestId);
      if (options.mode === "fake") {
        call.onInferenceStarted();
        const envelope = JSON.parse(call.input) as { request: { effects: { effectId: string }[] } };
        return fixedAsk(envelope.request.effects.map(effect => effect.effectId));
      }
      if (!options.services) return { status: "unavailable" };
      // real adapter owns the actual send boundary and must invoke the original callback exactly there.
      return options.services.reviewOnce(call);
    },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  };
}
function cwd(category: ShellEffect["cwdCategory"]): string {
  return category === "temporary" ? "/fixture/tmp" : category === "home" ? "/fixture/home" :
    category === "outside-repo" ? "/fixture/outside" : "/fixture/repo";
}
const MECHANICAL_FAULTS = new Set<MechanicalFault>(["missing-effect", "duplicate-binding",
  "unreferenced-message", "out-of-bounds", "non-utf8-boundary", "wrong-scope-digest",
  "old-generation"]);
function mechanicalFault(item: FrozenCase): MechanicalFault | undefined {
  const evidence = item.evidenceExpectation;
  return evidence?.mode === "invalid" && MECHANICAL_FAULTS.has(evidence.issue as MechanicalFault) ?
    evidence.issue as MechanicalFault : undefined;
}
function mechanicalObservation(item: FrozenCase, request: Readonly<ReviewRequest>,
    fault: MechanicalFault): MechanicalCaseObservation {
  const message = request.authorization_evidence[0];
  if (!message) throw new Error("INVALID_EVALUATION_STATE");
  const endByte = new TextEncoder().encode(message.text).length;
  const positive: ModelReview = { decision: "allow", risk: "low", authorization: "sufficient",
    effects: request.effects.map(effect => effect.effectId), unknowns: [],
    reasonCode: "LOW_RISK_AUTHORIZED", evidence: {
      userMessageIds: [message.messageId],
      bindings: request.effects.map(effect => ({ effectId: effect.effectId,
        userMessageId: message.messageId, startByte: 0, endByte, scopeDigest: effect.scopeDigest })),
    } };
  const context = { effects: request.effects, messages: request.authorization_evidence,
    verifiedUserMessageIds: new Set(request.authorization_evidence.map(item => item.messageId)),
    generation: request.generation, currentGeneration: request.generation, contextComplete: true,
    redactionComplete: true, outputTokens: 64, toolCalls: [] };
  decodeReview(JSON.stringify(positive), context);
  const injected = structuredClone(positive);
  let injectedContext = context;
  if (fault === "missing-effect") injected.evidence.bindings.pop();
  else if (fault === "duplicate-binding")
    injected.evidence.bindings.push(structuredClone(injected.evidence.bindings[0]!));
  else if (fault === "unreferenced-message") {
    const unreferenced = request.authorization_evidence.find(item => item.messageId !== message.messageId);
    if (!unreferenced) throw new Error("INVALID_EVALUATION_STATE");
    injected.evidence.userMessageIds.push(unreferenced.messageId);
  } else if (fault === "out-of-bounds") injected.evidence.bindings[0]!.endByte = endByte + 1;
  else if (fault === "non-utf8-boundary") injected.evidence.bindings[0]!.startByte = 1;
  else if (fault === "wrong-scope-digest") injected.evidence.bindings[0]!.scopeDigest = "0".repeat(64);
  else injectedContext = { ...context, currentGeneration: request.generation + 1 };
  let faultRejected = false;
  try { decodeReview(JSON.stringify(injected), injectedContext); }
  catch (error) {
    if (!(error instanceof ReviewContractError)) throw error;
    faultRejected = true;
  }
  if (!faultRejected) throw new Error("INVALID_EVALUATION_STATE");
  return { caseId: item.id, fault, positiveControlAccepted: true, faultRejected, modelCalls: 0 };
}
async function evaluateBash(item: FrozenCase, options: RunEvaluationOptions,
    evaluationIdentity: EvaluationIdentity): Promise<{ result: EvaluationResult;
      mechanical?: MechanicalCaseObservation }> {
  const input = policyInput(item);
  let assessment = assessBeforeReview(input);
  let primaryCalls = 0;
  let tinyCalls = 0;
  if (assessment.outcome === "review") {
    const messages = trustedMessages(item).map(message => ({ messageId: message.messageId, text: message.text }));
    const clock = options.mode === "fake" ? new EvaluationClock() : new MonotonicClock();
    const startedAt = clock.now();
    const prepared = buildReviewRequest({ session_id: `evaluation-${item.id}`,
      generation: item.userContext.generation, session_salt: digestBytes(`evaluation:${item.id}`),
      operation: item.action.command!, final_args: { command: item.action.command! },
      prepared_execution_id: {}, execution_binding: { digest: digestBytes(`binding:${item.id}`), local_ref: {} },
      transformation_summary: { version: 1, transformations: [] }, execution_context: {
        cwd: cwd(item.action.cwdCategory), shell: { path: "/bin/bash", args: [],
          identityDigest: digestBytes("frozen-simulated-bash") }, backend: "native",
        environmentDigest: digestBytes(`environment:${item.id}`),
        targetFingerprint: digestBytes(JSON.stringify(item.action.effects)),
      }, effects: item.action.effects, native_constraints: input.nativeConstraints,
      authorization_evidence: messages, verified_user_message_ids: new Set(messages.map(message => message.messageId)),
      context_complete: contextComplete(item), redaction_complete: true,
      restriction_state: assessment.restrictionState, mode: "smart", policy_version: evaluationIdentity.policyDigest,
      reviewer: { provider: evaluationIdentity.provider, model: evaluationIdentity.model },
      reviewer_source: "explicit-profile",
    }, clock.now, { requestId: `evaluation-${item.id}`, startedAt });
    const fault = mechanicalFault(item);
    if (fault) {
      const mechanical = mechanicalObservation(item, prepared.request, fault);
      assessment = synthesizeReview(input, undefined, true);
      if (assessment.outcome === "review") throw new Error("INVALID_EVALUATION_STATE");
      return { result: { id: item.id, outcome: assessment.outcome,
        humanPrompts: assessment.outcome === "ask" ? 1 : 0,
        coveredEffectIds: item.action.effects.map(effect => effect.effectId), primaryCalls: 0, tinyCalls: 0,
        commandExecutions: 0, checks: { ...NULL_CHECKS },
        unverifiedReasons: [...NULL_REASONS, "simulated-host-context",
          "adapter-internal-retries-unverified", ...(options.mode === "fake" ?
            ["real-inference-not-run" as const] : [])] }, mechanical };
    } else {
      const pipeline = await reviewWithFallback(prepared, createEvaluationReviewBoundary(options), {
        verifiedUserMessageIds: new Set(messages.map(message => message.messageId)),
        currentGeneration: () => item.userContext.generation,
      }, clock);
      primaryCalls = pipeline.primaryCalls; tinyCalls = pipeline.tinyCalls;
      assessment = synthesizeReview(input, pipeline.primary, true);
    }
  }
  if (assessment.outcome === "review") throw new Error("INVALID_EVALUATION_STATE");
  return { result: { id: item.id, outcome: assessment.outcome, humanPrompts: assessment.outcome === "ask" ? 1 : 0,
    coveredEffectIds: item.action.effects.map(effect => effect.effectId), primaryCalls, tinyCalls,
    commandExecutions: 0, checks: { ...NULL_CHECKS },
    unverifiedReasons: [...NULL_REASONS, "simulated-host-context",
      "adapter-internal-retries-unverified", ...(options.mode === "fake" ? ["real-inference-not-run" as const] : [])] } };
}

function binding(item: FrozenCase, ledger: PermissionLedger): ExecutionBinding {
  const hash = (name: string) => digestBytes(`${item.id}:${name}`);
  return { request_id: `evaluation-${item.id}`, session_id: ledger.sessionId, generation: ledger.generation,
    prepared_execution_id: {}, execution_ref: {}, execution_digest: hash("execution"),
    operation_digest: hash("operation"), argv_digest: hash("argv"), cwd: cwd(item.action.cwdCategory),
    shell_digest: hash("shell"), backend: "native", target_digest: hash("target"),
    authorization_digest: hash("authorization"), mode: ledger.mode,
    policy_version: hash("policy"), reviewer_identity: "fixture-fake/fixed-conservative-ask",
    plugin_digest: hash("plugin"), runtime_identity: "frozen-simulated-runtime", health_digest: hash("health") };
}
function exactObject(value: unknown, required: readonly string[], optional: readonly string[] = []):
    value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return required.every(key => Object.hasOwn(value, key)) &&
    keys.every(key => required.includes(key) || optional.includes(key));
}
function completeStatus(value: unknown): boolean {
  const required = ["reviewer_selection", "reviewer", "fallback_state", "bridge_health",
    "identity_verified", "policy_version", "native_protection", "coverage", "session_id", "generation",
    "configured_mode", "active_mode", "mode_source", "pending"] as const;
  if (!exactObject(value, required, ["reviewer_state", "remote_fallback", "remote_fallback_state",
    "last_decision_id", "pending_permit_id"])) return false;
  const native = value.native_protection;
  const nativeFields = ["bashPrompt", "denyPreserved", "commandPromptPreserved", "criticalSafetyPreserved",
    "taskPrompt", "evalPrompt", "noYolo"] as const;
  const coverage = value.coverage;
  const coverageFields = ["tool", "session", "shell", "platform", "backend", "execution", "eligible", "reasons"] as const;
  if (!exactObject(native, nativeFields) || nativeFields.some(field => typeof native[field] !== "boolean") ||
      !exactObject(coverage, coverageFields) || coverage.tool !== "bash" || coverage.session !== "main" ||
      coverage.shell !== "bash" || coverage.platform !== "linux" || coverage.backend !== "native" ||
      coverage.execution !== "foreground" || typeof coverage.eligible !== "boolean" ||
      !Array.isArray(coverage.reasons) || new Set(coverage.reasons).size !== coverage.reasons.length ||
      coverage.reasons.some(reason => typeof reason !== "string" ||
        !(COVERAGE_REASONS as readonly string[]).includes(reason))) return false;
  return ["session-default", "explicit"].includes(value.reviewer_selection as string) &&
    typeof value.reviewer === "string" && value.reviewer.length > 0 &&
    (value.reviewer_state === undefined || ["ready", "unavailable", "unsupported"].includes(value.reviewer_state as string)) &&
    ((value.remote_fallback === undefined && value.remote_fallback_state === undefined) ||
      typeof value.remote_fallback === "string" && value.remote_fallback.length > 0 &&
      ["disabled", "ready", "unavailable", "unhealthy"].includes(value.remote_fallback_state as string)) &&
    ["disabled", "ready", "unavailable", "unhealthy"].includes(value.fallback_state as string) &&
    ["healthy", "degraded", "unavailable"].includes(value.bridge_health as string) &&
    typeof value.identity_verified === "boolean" && typeof value.policy_version === "string" &&
    (value.policy_version === "unavailable" || /^[a-f0-9]{64}$/u.test(value.policy_version)) &&
    typeof value.session_id === "string" && value.session_id.length > 0 &&
    Number.isSafeInteger(value.generation) && (value.generation as number) >= 0 &&
    ["smart", "manual"].includes(value.configured_mode as string) &&
    ["smart", "manual"].includes(value.active_mode as string) &&
    ["profile-default", "session-command"].includes(value.mode_source as string) &&
    ["none", "reviewing", "awaiting-human", "permitted"].includes(value.pending as string) &&
    [value.last_decision_id, value.pending_permit_id]
      .every(item => item === undefined || typeof item === "string" && item.length > 0);
}
function evaluateState(item: FrozenCase): EvaluationResult {
  let now = 0;
  const ledger = new PermissionLedger(`evaluation-${item.id}`, "smart", () => now);
  const cancel = new AbortController();
  const handle = ledger.beginRequest(binding(item, ledger), cancel.signal);
  let explicitCancel = false;
  let cancelLatency: number | null = null;
  for (const event of [...(item.action.events ?? [])].sort((left, right) => left.atMs - right.atMs)) {
    now = event.atMs;
    if (event.type === "cancel") {
      explicitCancel = true; cancel.abort();
      if (handle.signal.aborted) cancelLatency = 0;
    } else if (event.type === "mode-change") {
      ledger.setMode(event.value.includes("manual") ? "manual" : "smart");
    } else if (event.type === "authorization-change") ledger.invalidate("authorization-changed");
    else if (event.type === "target-change" || event.type === "runtime-identity-change")
      ledger.invalidate("binding-changed");
    else if (event.type === "plugin-health-change") ledger.invalidate("health-changed");
    else if (event.type === "model-change") ledger.invalidate("model-changed");
    else if (event.type === "policy-change") ledger.invalidate("policy-changed");
    else if (event.type === "session-restore") ledger.invalidate("session-changed");
  }
  const statusComplete = completeStatus(ledger.snapshot());
  const checks = { ...NULL_CHECKS, cancelLatencyMs: cancelLatency, statusComplete };
  const reasons = NULL_REASONS.filter(reason => reason !== "status-not-observed" &&
    !(cancelLatency !== null && reason === "cancel-latency-not-observed"));
  return { id: item.id, outcome: explicitCancel && handle.signal.aborted ? "cancelled" : "ask",
    humanPrompts: explicitCancel ? 0 : 1, coveredEffectIds: [], primaryCalls: 0, tinyCalls: 0,
    commandExecutions: 0, checks,
    unverifiedReasons: [...reasons, "simulated-host-context", "real-inference-not-run",
      "event-observation-unavailable", "adapter-internal-retries-unverified"] };
}

function prepareEvaluation(selection: EvaluationSelection) {
  if (!selection || !["fake", "real"].includes(selection.mode) ||
      !isAbsolute(selection.repositoryRoot) || !isAbsolute(selection.fixtureDirectory) ||
      !/^[a-zA-Z0-9_.-]{1,128}$/u.test(selection.platform) ||
      selection.mode === "real" && (![selection.provider, selection.model].every(value =>
        /^[a-zA-Z0-9_./:-]{1,256}$/u.test(value)) ||
        !["anthropic-messages", "openai-completions"].includes(selection.transport))) invalid();
  const fixture = readFrozenFixture(selection.fixtureDirectory);
  const evaluationIdentity = identity(selection, fixture.digest);
  const items = fixture.cases.map(frozenCase);
  if (items.some(item => item.action.platform !== selection.platform)) invalid();
  return { evaluationIdentity, items };
}

export async function runEvaluation(options: RunEvaluationOptions) {
  const prepared = prepareEvaluation(options as EvaluationSelection);
  if (options.mode === "real" && (!options.services ||
      typeof options.services.reviewOnce !== "function" ||
      typeof options.services.tinyInstalledOnly !== "function")) invalid();
  const { evaluationIdentity, items } = prepared;
  const cases: EvaluationCase[] = items.map(item => ({ id: item.id, category: item.category,
    compound: item.action.compound, effectIds: item.action.effects.map(effect => effect.effectId) }));
  const rows: EvaluationResult[] = [];
  const mechanicalCases: MechanicalCaseObservation[] = [];
  for (const item of items) {
    if (item.action.kind !== "bash") rows.push(evaluateState(item));
    else {
      const evaluated = await evaluateBash(item, options, evaluationIdentity);
      rows.push(evaluated.result);
      if (evaluated.mechanical) mechanicalCases.push(evaluated.mechanical);
    }
  }
  return buildEvaluationReport(cases, rows, evaluationIdentity, mechanicalCases);
}

interface CliOptions extends CommonOptions {
  mode: "fake" | "real";
  output?: string;
  serviceModule?: string;
  provider?: string;
  model?: string;
  transport?: Transport;
}
function parseCli(argv: readonly string[]): CliOptions {
  const values = new Map<string, string>();
  const allowed = new Set(["--mode", "--repository-root", "--fixtures", "--platform", "--output",
    "--service-module", "--provider", "--model", "--transport"]);
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]; const value = argv[index + 1];
    if (!allowed.has(key) || value === undefined || value.startsWith("--") || values.has(key)) invalid();
    values.set(key, value);
  }
  const mode = values.get("--mode") ?? "fake";
  const repositoryRoot = resolve(values.get("--repository-root") ?? ROOT);
  const fixtureDirectory = resolve(values.get("--fixtures") ?? FIXTURES);
  const common = { mode, repositoryRoot, fixtureDirectory,
    platform: values.get("--platform") ?? "linux-glibc-x64",
    ...(values.has("--output") ? { output: resolve(values.get("--output")!) } : {}) };
  if (common.output) {
    try { common.output = join(realpathSync(dirname(common.output)), basename(common.output)); }
    catch { invalid(); }
    if ([fixtureDirectory, join(repositoryRoot, "agents/omp/packages/omp-permission-control"),
      join(repositoryRoot, "agents/omp/patches/permission-control")]
      .some(root => within(common.output!, realpathSync(root)))) invalid();
  }
  const realFields = ["--service-module", "--provider", "--model", "--transport"];
  if (mode === "fake") {
    if (realFields.some(field => values.has(field))) invalid();
    return common as CliOptions;
  }
  if (mode !== "real" || realFields.some(field => !values.has(field))) invalid();
  const serviceModule = values.get("--service-module")!;
  const provider = values.get("--provider")!; const model = values.get("--model")!;
  const transport = values.get("--transport")!;
  if (!isAbsolute(serviceModule) || ![provider, model].every(value => /^[a-zA-Z0-9_./:-]{1,256}$/u.test(value)) ||
      !["anthropic-messages", "openai-completions"].includes(transport)) invalid();
  return { ...common, mode: "real", serviceModule, provider, model, transport: transport as Transport };
}

export async function runEvaluationCli(argv: readonly string[], dependencies: EvaluationCliDependencies = {}) {
  const parsed = parseCli(argv);
  const selection: EvaluationSelection = parsed.mode === "fake" ? {
    mode: "fake", repositoryRoot: parsed.repositoryRoot,
    fixtureDirectory: parsed.fixtureDirectory, platform: parsed.platform,
  } : { mode: "real", repositoryRoot: parsed.repositoryRoot,
    fixtureDirectory: parsed.fixtureDirectory, platform: parsed.platform,
    provider: parsed.provider!, model: parsed.model!, transport: parsed.transport! };
  // 显式 adapter 仍是可执行模块；先完成全部参数、冻结集和参与源码身份验证。
  prepareEvaluation(selection);
  let options: RunEvaluationOptions;
  if (parsed.mode === "fake") options = { mode: "fake", repositoryRoot: parsed.repositoryRoot,
    fixtureDirectory: parsed.fixtureDirectory, platform: parsed.platform };
  else {
    const loader = dependencies.loadServiceModule ?? (async path => import(pathToFileURL(path).href));
    let module: unknown;
    try { module = await loader(parsed.serviceModule!); }
    catch { throw new Error("EVALUATION_SERVICE_UNAVAILABLE"); }
    const factory = (module as { createEvaluationReviewServices?: unknown })?.createEvaluationReviewServices;
    if (typeof factory !== "function") invalid();
    let services: ReviewServices;
    try { services = await factory({ provider: parsed.provider, model: parsed.model, transport: parsed.transport }); }
    catch { throw new Error("EVALUATION_SERVICE_UNAVAILABLE"); }
    if (!services || typeof services.reviewOnce !== "function" || typeof services.tinyInstalledOnly !== "function") invalid();
    options = { mode: "real", repositoryRoot: parsed.repositoryRoot,
      fixtureDirectory: parsed.fixtureDirectory, platform: parsed.platform,
      provider: parsed.provider!, model: parsed.model!, transport: parsed.transport!, services };
  }
  const report = await runEvaluation(options);
  const bytes = `${JSON.stringify(report, null, 2)}\n`;
  if (parsed.output) {
    try { (dependencies.writeOutput ?? ((path, value) => writeFileSync(path, value,
      { encoding: "utf8", flag: "wx" })))(parsed.output, bytes); }
    catch { throw new Error("EVALUATION_OUTPUT_FAILED"); }
  }
  else (dependencies.stdout ?? (value => process.stdout.write(value)))(bytes);
  return report;
}

if (import.meta.main) await runEvaluationCli(Bun.argv.slice(2));
