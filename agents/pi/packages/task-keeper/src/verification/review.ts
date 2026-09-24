import { readFileSync } from "node:fs";
import { relative } from "node:path";
import { object, finiteInteger, ContractError, digest } from "../contracts/primitives.ts";
import type { TaskSpec } from "../contracts/task.ts";
import type { DelegationResult } from "../adapters/subagents.ts";
import { guardedPath } from "../adapters/child-reporter.ts";
import { readBeforeVerdict } from "./read-causality.ts";
import type { ChildObservation } from "../adapters/child-contract.ts";

export function reviewSchema(spec: TaskSpec) {
  return { type: "object", additionalProperties: false,
    required: ["verdict", "snapshot", "summary", "scopeComplete", "findings", "evidence", "unverified"],
    properties: {
      verdict: { type: "string", enum: ["pass", "fail", "unknown"] }, snapshot: { type: "string", const: spec.snapshot },
      summary: { type: "string", maxLength: 4000 }, scopeComplete: { type: "boolean" },
      findings: { type: "array", maxItems: 100, items: { type: "object", additionalProperties: false,
        required: ["id", "severity", "message"], properties: { id: { type: "string", minLength: 1, maxLength: 200 }, severity: { enum: ["critical", "high", "medium", "low", "info"] }, message: { type: "string", maxLength: 4000 }, actionable: { type: "boolean" }, evidenceIndices: { type: "array", items: { type: "integer", minimum: 0 }, uniqueItems: true } } } },
      evidence: { type: "array", minItems: 1, maxItems: 100, items: { type: "object", additionalProperties: false,
        required: ["path", "startLine", "endLine"], properties: { path: { type: "string" }, startLine: { type: "integer", minimum: 1 }, endLine: { type: "integer", minimum: 1 } } } },
      resolvedFailures: { type: "array", uniqueItems: true, maxItems: 100, items: { type: "string" } },
      unverified: { type: "array", uniqueItems: true, items: { enum: [...spec.required, ...spec.optional] } },
    } };
}

function fullArtifactRead(result: DelegationResult, id: string, verdicts?: Map<ChildObservation, number>): boolean {
  const ranges = result.observations.flatMap((observation) => observation.artifactReads.filter((range) => range.id === id
    && (!verdicts || readBeforeVerdict(range, verdicts.get(observation) ?? 0)))).sort((a, b) => a.start - b.start);
  if (!ranges.length) return false;
  let end = 0;
  for (const range of ranges) {
    if (range.start > end) return false;
    end = Math.max(end, range.end);
  }
  return ranges.every((range) => range.total === ranges[0].total) && end === ranges[0].total;
}

/** Invocation, source scope and coverage are checked by code; semantic judgement remains attributed to the reviewer. */
export function validateReview(result: DelegationResult, spec: TaskSpec, cwd: string, requiredArtifact?: string | string[], allowedFailures: readonly string[] = []) {
  if (result.status !== "ended" || !result.terminationConfirmed) throw new ContractError("REVIEW_EXECUTION_NOT_VERIFIED");
  const envelope = object(result.content);
  const raw = envelope.kind === "structured" ? envelope.value : typeof envelope.text === "string" ? JSON.parse(envelope.text) : null;
  const report = object(raw, ["verdict", "snapshot", "summary", "scopeComplete", "findings", "evidence", "unverified", "resolvedFailures"]);
  if (!["pass", "fail", "unknown"].includes(report.verdict as string) || report.snapshot !== spec.snapshot
    || typeof report.summary !== "string" || report.summary.length > 4000 || typeof report.scopeComplete !== "boolean"
    || !Array.isArray(report.findings) || report.findings.length > 100 || !Array.isArray(report.evidence) || !report.evidence.length || report.evidence.length > 100 || !Array.isArray(report.unverified) || new Set(report.unverified).size !== report.unverified.length) {
    throw new ContractError("INVALID_REVIEW_REPORT");
  }
  const reportDigest = digest(report), verdicts = new Map<ChildObservation, number>();
  for (const observation of result.observations) {
    const candidates = observation.structuredOutputs?.filter(value => value.valueDigest === reportDigest
      && Number.isSafeInteger(value.requestOrdinal) && value.requestOrdinal > 0) ?? [];
    if (candidates.length) verdicts.set(observation, Math.max(...candidates.map(value => value.requestOrdinal)));
  }
  if (!verdicts.size) throw new ContractError("REVIEW_VERDICT_NOT_OBSERVED");
  for (const artifact of requiredArtifact ? typeof requiredArtifact === "string" ? [requiredArtifact] : requiredArtifact : []) {
    if (!fullArtifactRead(result, artifact)) throw new ContractError("REVIEW_EVIDENCE_NOT_READ");
    if (!fullArtifactRead(result, artifact, verdicts)) throw new ContractError("REVIEW_EVIDENCE_NOT_DELIVERED");
  }
  if (report.resolvedFailures !== undefined && (!Array.isArray(report.resolvedFailures) || report.resolvedFailures.length > 100 || new Set(report.resolvedFailures).size !== report.resolvedFailures.length || report.resolvedFailures.some((id) => !allowedFailures.includes(id)))) throw new ContractError("UNKNOWN_REVIEW_FAILURE");
  for (const item of report.evidence) {
    const ref = object(item, ["path", "startLine", "endLine"]);
    finiteInteger(ref.startLine, 1); finiteInteger(ref.endLine, ref.startLine);
    const path = guardedPath(cwd, ref.path, false), lines = readFileSync(path, "utf8").split("\n").length;
    if (ref.endLine > lines) throw new ContractError("INVALID_REVIEW_REFERENCE");
    if (!result.observations.some((observation) => observation.fileReads.some((read) => read.path === relative(cwd, path)
      && read.firstLine <= Number(ref.startLine) && read.lastLine >= Number(ref.endLine)))) throw new ContractError("REVIEW_EVIDENCE_NOT_READ");
    if (!result.observations.some((observation) => observation.fileReads.some((read) => read.path === relative(cwd, path)
      && read.firstLine <= Number(ref.startLine) && read.lastLine >= Number(ref.endLine)
      && readBeforeVerdict(read, verdicts.get(observation) ?? 0)))) throw new ContractError("REVIEW_EVIDENCE_NOT_DELIVERED");
  }
  const findings = report.findings.map((item) => object(item, ["id", "severity", "message", "actionable", "evidenceIndices"]));
  if (findings.some((finding) => typeof finding.id !== "string" || !finding.id.trim() || finding.id.length>200 || typeof finding.message !== "string"
    || !["critical", "high", "medium", "low", "info"].includes(finding.severity as string))) throw new ContractError("INVALID_REVIEW_FINDING");
  if(new Set(findings.map(finding=>finding.id)).size!==findings.length)throw new ContractError("DUPLICATE_REVIEW_FINDING");
  if (report.unverified.some((id) => typeof id !== "string" || ![...spec.required, ...spec.optional].includes(id))) throw new ContractError("UNKNOWN_REVIEW_REQUIREMENT");
  for (const finding of findings) if ((finding.actionable !== undefined && typeof finding.actionable !== "boolean")
    || (finding.evidenceIndices !== undefined && (!Array.isArray(finding.evidenceIndices)
      || finding.evidenceIndices.some((index) => !Number.isSafeInteger(index) || index < 0 || index >= (report.evidence as unknown[]).length)))) throw new ContractError("INVALID_FINDING_EVIDENCE");
  const requiredUnknown = report.unverified.some((id) => spec.required.includes(id as string));
  const passed = report.verdict === "pass" && report.scopeComplete && !requiredUnknown && !findings.some((finding) => ["critical", "high"].includes(finding.severity as string));
  return { passed, status: passed ? "passed" as const : requiredUnknown || report.verdict === "unknown" ? "unknown" as const : "failed" as const, report };
}
