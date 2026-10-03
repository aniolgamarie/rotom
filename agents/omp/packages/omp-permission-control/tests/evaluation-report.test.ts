import { expect, test } from "bun:test";
import { buildEvaluationReport, type EvaluationCase, type EvaluationResult, type EvaluationIdentity } from "../evaluation/report";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { FROZEN_DIGEST, readFrozenFixture, verifyFrozenBytes } from "../evaluation/fixtures";

const hash = "a".repeat(64);
const cases: EvaluationCase[] = [
  { id: "safe-1", category: "policy-safe", compound: true, effectIds: ["e1", "e2"] },
  { id: "risk-1", category: "ask-deny", compound: false, effectIds: ["e1"] },
  { id: "fault-1", category: "fault-state", compound: false, effectIds: ["e1"] },
];
const identity: EvaluationIdentity = { mode: "fake", provider: "fake", model: "fixed",
  transport: "fake", platform: "linux-glibc-x64", sourceDigest: hash, policyDigest: hash, fixtureDigest: hash,
  pluginDigest: hash, hostDigest: hash };
const unverified = ["stale-permit-not-observed", "tiny-allow-not-observed", "download-not-observed",
  "automatic-deadline-not-observed", "cancel-latency-not-observed", "status-not-observed",
  "secret-leak-not-observed", "delivery-residue-not-observed"] as const;
const rows = (): EvaluationResult[] => cases.map(item => ({ id: item.id,
  outcome: item.category === "policy-safe" ? "allow" : "ask", humanPrompts: 0,
  coveredEffectIds: [...item.effectIds], primaryCalls: 0, tinyCalls: 0, commandExecutions: 0,
  checks: { stalePermitUses: null, tinyAllows: null, downloads: null, automaticMs: null,
    cancelLatencyMs: null, statusComplete: null, secretLeaks: null, deliveryResidues: null },
  unverifiedReasons: [...unverified] }));

test("frozen fixture preserves the original generator order and rejects even whitespace drift", () => {
  const directory = resolve(import.meta.dir, "../../../../../tests/fixtures/omp/permission-control");
  const fixture = readFrozenFixture(directory);
  expect(fixture.digest).toBe(FROZEN_DIGEST);
  expect(fixture.cases).toHaveLength(240);
  const files = {
    "fixture-schema.json": readFileSync(resolve(directory, "fixture-schema.json")),
    "cases.jsonl": readFileSync(resolve(directory, "cases.jsonl")),
    "labels.json": readFileSync(resolve(directory, "labels.json")),
  };
  files["labels.json"] = Buffer.concat([files["labels.json"], Buffer.from(" ")]);
  expect(() => verifyFrozenBytes(files)).toThrow("FROZEN_FIXTURE_IDENTITY_CHANGED");
});

test("fake report cannot claim real-model quality or treat unmeasured checks as zero", () => {
  const report = buildEvaluationReport(cases, rows(), identity);
  expect(report.metrics.safeNoPromptRate).toBe(1);
  expect(report.successCriteria.sc001).toBeNull();
  expect(report.metrics.dangerousAllows).toBe(0);
  expect(report.metrics.stalePermitUses).toBeNull();
  expect(report.metrics.compoundCompleteRate).toBe(1);
  expect(report.metricSemantics.compoundCompleteRate).toBe(
    "input-effect-inventory-only; not-model-response-effect-coverage");
  expect(report.mechanicalCases).toEqual([]);
  expect(report.claimScope).toBe("fixed-fixture-only; no-general-safety-guarantee");
  expect(report.unverified).toContain("real-model-authorization-semantics");
});

test("dangerous allow and omitted pipeline effect stay visible in metrics", () => {
  const data = rows();
  data[1].outcome = "allow";
  data[0].coveredEffectIds = ["e1"];
  const report = buildEvaluationReport(cases, data, { ...identity, mode: "real", provider: "fictional",
    model: "small", transport: "openai-completions" });
  expect(report.metrics.dangerousAllows).toBe(1);
  expect(report.successCriteria.sc002).toBe(false);
  expect(report.metrics.compoundCompleteRate).toBe(0);
  expect(report.successCriteria.sc001).toBe(true);
});

test("all observations are required before reporting a measured invariant", () => {
  const data = rows();
  for (const item of data) item.checks = { stalePermitUses: 0, tinyAllows: 0, downloads: 0,
    automaticMs: 20, cancelLatencyMs: null, statusComplete: true, secretLeaks: 0, deliveryResidues: 0 };
  for (const item of data) item.unverifiedReasons = ["cancel-latency-not-observed"];
  data[1].checks.automaticMs = 30_001;
  data[2].checks.stalePermitUses = 1;
  const report = buildEvaluationReport(cases, data, identity);
  expect(report.metrics.stalePermitUses).toBe(1);
  expect(report.metrics.automaticDeadlineViolations).toBe(1);
  expect(report.metrics.cancelLatencyViolations).toBeNull();
  expect(report.metrics.statusCompleteRate).toBe(1);
});

test("missing/duplicate results, extra effects, calls above one, and execution cannot be hidden", () => {
  const invalid = [rows().slice(1), [...rows(), rows()[0]]];
  for (const data of invalid) expect(() => buildEvaluationReport(cases, data, identity)).toThrow("INVALID_EVALUATION_REPORT");
  for (const change of [
    (row: EvaluationResult) => { row.commandExecutions = 1; },
    (row: EvaluationResult) => { row.primaryCalls = 2; },
    (row: EvaluationResult) => { row.coveredEffectIds.push("unknown"); },
    (row: EvaluationResult) => { row.checks.secretLeaks = -1; },
  ]) {
    const data = rows(); change(data[0]);
    expect(() => buildEvaluationReport(cases, data, identity)).toThrow("INVALID_EVALUATION_REPORT");
  }
});

test("unknown fields and free-text identities cannot leak commands or secrets", () => {
  const data = rows();
  Object.assign(data[0], { command: "SECRET_SENTINEL" });
  expect(() => buildEvaluationReport(cases, data, identity)).toThrow("INVALID_EVALUATION_REPORT");
  expect(() => buildEvaluationReport(cases, rows(), { ...identity, provider: "secret sentinel" }))
    .toThrow("INVALID_EVALUATION_REPORT");
});

test("each null observation requires its closed unverified reason", () => {
  const missing = rows();
  missing[0].unverifiedReasons = missing[0].unverifiedReasons.filter(reason =>
    reason !== "stale-permit-not-observed");
  expect(() => buildEvaluationReport(cases, missing, identity)).toThrow("INVALID_EVALUATION_REPORT");
  const falseDisclaimer = rows();
  falseDisclaimer[0].checks.stalePermitUses = 0;
  expect(() => buildEvaluationReport(cases, falseDisclaimer, identity)).toThrow("INVALID_EVALUATION_REPORT");
  const unknown = rows();
  unknown[0].unverifiedReasons.push("secret-sentinel" as never);
  expect(() => buildEvaluationReport(cases, unknown, identity)).toThrow("INVALID_EVALUATION_REPORT");
});
