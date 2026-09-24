import { ContractError, digest, finiteInteger, object } from "../contracts/primitives.ts";

export interface RecoveryAcceptanceInput {
  runId: string;
  binding: null | { family: string; bindingDigest: string; runtimeDigest: string; profileDigest: string; requestCeiling: number };
  expected: { bindingDigest: string; runtimeDigest: string; profileDigest: string };
  controlledFaultsPassed: boolean;
  observations: Array<{
    requestId: string; sessionId: string; continuationKey: string;
    bindingDigest: string; runtimeDigest: string; profileDigest: string;
    origin: "injected" | "service-origin" | "loopback";
    sentAt: number; endedAt: number; notBefore: number;
    outcome: "rate-limited" | "completed" | "failed" | "unknown";
    artifact: string;
  }>;
  effects: Array<{ id: string; requestId: string; artifact: string }>;
  terminal: null | { sessionId: string; continuationKey: string; outcome: "completed" | "failed" | "unknown"; artifact: string };
}

const identityFields = ["bindingDigest", "runtimeDigest", "profileDigest"] as const;
function nonempty(value: unknown): asserts value is string {
  if (typeof value !== "string" || !value.trim()) throw new ContractError("INVALID_RECOVERY_EVIDENCE");
}

/** Reporting policy only. Artifacts must already have been captured by the acceptance runner. */
export function recoveryAcceptance(value: unknown) {
  const raw = object(value, ["runId", "binding", "expected", "controlledFaultsPassed", "observations", "effects", "terminal"]);
  nonempty(raw.runId);
  const expected = object(raw.expected, identityFields);
  for (const key of identityFields) nonempty(expected[key]);
  if (typeof raw.controlledFaultsPassed !== "boolean" || !Array.isArray(raw.observations) || !Array.isArray(raw.effects))
    throw new ContractError("INVALID_RECOVERY_EVIDENCE");
  if (raw.binding !== null) {
    const binding = object(raw.binding, ["family", ...identityFields, "requestCeiling"]);
    nonempty(binding.family);
    for (const key of identityFields) nonempty(binding[key]);
    finiteInteger(binding.requestCeiling, 1);
  }
  for (const item of raw.observations) {
    const row = object(item, ["requestId", "sessionId", "continuationKey", ...identityFields, "origin", "sentAt", "endedAt", "notBefore", "outcome", "artifact"]);
    for (const key of ["requestId", "sessionId", "continuationKey", ...identityFields, "artifact"]) nonempty(row[key]);
    for (const key of ["sentAt", "endedAt", "notBefore"]) finiteInteger(row[key]);
    if (Number(row.endedAt) < Number(row.sentAt)
      || !["injected", "service-origin", "loopback"].includes(String(row.origin))
      || !["rate-limited", "completed", "failed", "unknown"].includes(String(row.outcome))) throw new ContractError("INVALID_RECOVERY_EVIDENCE");
  }
  for (const item of raw.effects) {
    const effect = object(item, ["id", "requestId", "artifact"]);
    for (const key of ["id", "requestId", "artifact"]) nonempty(effect[key]);
  }
  if (raw.terminal !== null) {
    const terminal = object(raw.terminal, ["sessionId", "continuationKey", "outcome", "artifact"]);
    for (const key of ["sessionId", "continuationKey", "artifact"]) nonempty(terminal[key]);
    if (!["completed", "failed", "unknown"].includes(String(terminal.outcome))) throw new ContractError("INVALID_RECOVERY_EVIDENCE");
  }
  const input = value as RecoveryAcceptanceInput;
  const reasons: string[] = [];
  const requests = input.observations;
  if (!input.binding) reasons.push("LIVE_BINDING_MISSING");
  else {
    if (identityFields.some(key => input.binding![key] !== input.expected[key])) reasons.push("BINDING_CERTIFICATION_STALE");
    if (requests.length > input.binding.requestCeiling) reasons.push("REQUEST_CEILING_EXCEEDED");
  }
  if (!input.controlledFaultsPassed) reasons.push("CONTROLLED_FAULTS_NOT_PASSED");
  if (requests.some(row => identityFields.some(key => row[key] !== input.expected[key]))) reasons.push("OBSERVED_IDENTITY_MISMATCH");
  if (new Set(requests.map(row => row.requestId)).size !== requests.length) reasons.push("DUPLICATE_REQUEST_IDENTITY");
  if (input.effects.some(effect => !requests.some(row => row.requestId === effect.requestId))) reasons.push("UNOWNED_EFFECT");
  if (new Set(input.effects.map(effect => effect.id)).size !== input.effects.length) reasons.push("DUPLICATE_SIDE_EFFECT");
  const service = requests.filter(row => row.origin === "service-origin");
  const availability = service.some(row => row.outcome === "completed");
  if (!availability) reasons.push("LIVE_SERVICE_NOT_COMPLETED");
  if (requests.some(row => row.origin === "loopback")) reasons.push("LOOPBACK_IS_NOT_LIVE_ACCEPTANCE");
  const limited = requests.filter(row => row.outcome === "rate-limited" && row.origin !== "loopback");
  if (!limited.length) reasons.push("RECOVERY_NOT_EXERCISED");
  if (requests.filter(row => row.origin === "injected").some(row => row.outcome !== "rate-limited")
    || requests.filter(row => row.origin === "injected").length > 1) reasons.push("INVALID_CONTROLLED_INJECTION");
  if (requests.some((row, index) => index > 0 && row.sentAt < requests[index - 1].endedAt)) reasons.push("REQUEST_ORDER_OR_OVERLAP");
  const first = requests[0];
  if (first && requests.some(row => row.sessionId !== first.sessionId || row.continuationKey !== first.continuationKey))
    reasons.push("CONTINUATION_IDENTITY_CHANGED");
  for (const failure of limited) {
    const resumed = service.find(row => row.sentAt >= failure.endedAt && row.outcome === "completed");
    if (!resumed) reasons.push("RECOVERY_SERVICE_NOT_COMPLETED");
    if (requests.some(row => row.sentAt >= failure.endedAt && row.requestId !== failure.requestId && row.sentAt < failure.notBefore))
      reasons.push("RECOVERY_BEFORE_NOT_BEFORE");
  }
  if (!input.terminal || input.terminal.outcome !== "completed") reasons.push("TASK_NOT_COMPLETED");
  else if (!first || input.terminal.sessionId !== first.sessionId || input.terminal.continuationKey !== first.continuationKey)
    reasons.push("TERMINAL_IDENTITY_MISMATCH");
  if (requests.at(-1)?.outcome !== "completed" || requests.some(row => row.outcome === "unknown")) reasons.push("UNRESOLVED_REQUEST_OUTCOME");
  const qualified = reasons.length === 0;
  return { runId: input.runId, inputDigest: digest(value), availabilityPassed: availability,
    recoveryQualified: qualified, reasons: [...new Set(reasons)],
    certificationKey: qualified ? digest(input.expected) : null,
    scope: input.expected, requests: requests.length, sideEffects: input.effects.length,
    origins: Object.fromEntries(["injected", "service-origin", "loopback"].map(origin => [origin, requests.filter(row => row.origin === origin).map(row => row.requestId)])),
    observations: requests, effects: input.effects, terminal: input.terminal,
    limitations: ["Qualifies supplied evidence for this binding/runtime/profile only; does not execute or authenticate a live service", "Artifact provenance must be independently audited; synthetic reporting fixtures do not certify any live provider"] };
}
