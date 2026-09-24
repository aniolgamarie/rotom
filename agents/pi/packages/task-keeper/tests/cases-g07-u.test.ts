import { test, assert, evidence } from "./recorded-test.ts";
import { outcome, presentReceipt, transition, type ExecutionFacts } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";
const failure = { id: "failure", layer: "tool" as const, code: "TOOL_FAILED", message: "source missing", attemptId: "attempt-1", required: true, resolvedBy: null as string | null };

for (const id of ["EVD-010", "T03", "T12", "T61", "T83"]) test(`[U ${id}] TC-${id}-U native completion and finish claims cannot replace missing required acceptance`, () => {
  for (const evidenceId of [id]) evidence(evidenceId, () => {
    const { spec, facts } = acceptedCandidate(); assert.equal(outcome(spec, facts).status, "COMPLETED");
    for (const checkId of ["tests", "review"]) for (const status of ["failed", "not_run", "unknown", "not_applicable"] as const) {
      const next = structuredClone(facts); next.checks.find(c => c.checkId === checkId)!.status = status; next.claims = ["request_finish", "everything passed"];
      const result = outcome(spec, next); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes(`required:${checkId}`));
      assert.match(presentReceipt(result), /BLOCKED; native: completed/);
    }
  });
});
for (const id of ["EVD-003", "T05"]) test(`[U ${id}] TC-${id}-U explicit recovery preserves failed attempt and requires current authenticated evidence`, () => {
  for (const evidenceId of [id]) evidence(evidenceId, () => {
    const { spec, facts } = acceptedCandidate(); facts.failures = [failure]; facts.claims = ["recovered using a different model"];
    assert.equal(outcome(spec, facts).status, "BLOCKED");
    facts.failures = [{ ...failure, resolvedBy: "artifact-tests" }];
    const resolved = outcome(spec, facts); assert.equal(resolved.status, "COMPLETED"); assert.deepEqual(resolved.failureHistory, facts.failures);
    for (const change of [{ snapshot: "old-tree" }, { specVersion: 0 }, { policyDigest: "old-policy" }, { source: "claim" as const }]) {
      const next = structuredClone(facts); Object.assign(next.checks[0], change);
      assert.ok(outcome(spec, next).reasons.includes("unresolved:failure"));
    }
    const newSnapshot = { ...spec, snapshot: "new-tree" }; assert.equal(outcome(newSnapshot, facts).status, "BLOCKED");
    assert.equal(facts.failures[0].attemptId, "attempt-1");
  });
});
for (const id of ["EVD-011", "T13"]) test(`[U ${id}] TC-${id}-U optional failure is disclosed even beside an earlier pass and never demotes required`, () => {
  const { spec, facts } = acceptedCandidate();
  const earlier = structuredClone(facts.checks.find(c => c.checkId === "extra")!);
  facts.checks.push({ ...earlier, status: "failed" });
  const result = outcome(spec, facts); assert.equal(result.status, "PARTIAL"); assert.deepEqual(result.optionalGaps, ["extra"]);
  assert.equal(outcome({ ...spec, allowPartial: false }, facts).status, "BLOCKED");
  const required = { ...spec, optional: [], required: [...spec.required, "extra"] };
  assert.equal(outcome(required, facts).status, "BLOCKED"); assert.ok(outcome(required, facts).reasons.includes("required:extra"));
  facts.checks.pop(); assert.equal(outcome(spec, facts).status, "COMPLETED");
  // Untrusted claims cannot manufacture either success or a contradictory verification fact.
  facts.checks.push({ ...earlier, status: "failed", source: "claim" }); assert.equal(outcome(spec, facts).status, "COMPLETED");
});
for (const id of ["EXE-005", "T01"]) test(`[U ${id}] TC-${id}-U accepted delivery without a started run stays blocked`, () => {
  const { spec, facts } = acceptedCandidate(); facts.delivery = "accepted"; facts.nativeRunId = null; facts.execution = "failed";
  facts.failures = [{ ...failure, layer: "runner", code: "START_FAILED" }];
  const result = outcome(spec, facts); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes("execution_not_started"));
  assert.equal(result.failureHistory[0].code, "START_FAILED");
});
for (const id of ["EXE-006", "T02"]) test(`[U ${id}] TC-${id}-U interrupted execution cannot become successful through exit-zero native metadata`, () => {
  const { spec, facts } = acceptedCandidate(); facts.execution = "interrupted"; facts.nativeStatus = "exitCode=0; interrupted=true";
  const result = outcome(spec, facts); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes("execution_not_ended"));
  assert.equal(result.nativeStatus, facts.nativeStatus);
  facts.execution = "ended"; facts.nativeStatus = "completed"; assert.equal(outcome(spec, facts).status, "COMPLETED");
});
for (const id of ["T04", "T17"]) test(`[U ${id}] TC-${id}-U requested resolved and runtime-observed identities remain independent`, () => {
  const { spec, facts } = acceptedCandidate();
  for (const observation of [null, {}, { model: "other", thinking: "high" }, { model: "configured-model", thinking: "off" }]) {
    const next = structuredClone(facts); next.contract.runtimeObserved = observation;
    const result = outcome(spec, next); assert.equal(result.status, "BLOCKED"); assert.deepEqual(next.contract.runtimeObserved, observation);
    assert.deepEqual(next.contract.requested, facts.contract.requested);
  }
  const approved = structuredClone(facts); approved.contract.requested.model = approved.contract.resolved!.model = approved.contract.runtimeObserved!.model = "approved-other";
  assert.equal(outcome(spec, approved).status, "COMPLETED");
});
test("[U T09] TC-T09-U final success text cannot hide an unresolved required tool failure", () => {
  for (const id of ["T09"]) evidence(id, () => {
    const { spec, facts } = acceptedCandidate(); facts.failures = [failure]; facts.claims = ["Done; all checks passed"];
    const result = outcome(spec, facts); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes("unresolved:failure"));
    assert.match(presentReceipt(result), /TOOL_FAILED/); assert.equal(result.failureHistory[0].resolvedBy, null);
  });
});
test("[U EVD-012] TC-EVD-012-U each independent completion prerequisite has a failing counterexample", () => {
  const mutations: Array<(f: ExecutionFacts) => void> = [f => { f.delivery = "queued"; }, f => { f.nativeRunId = null; },
    f => { f.execution = "unknown"; }, f => { f.terminationConfirmed = false; }, f => { f.contract.violations = ["isolation"]; },
    f => { f.contract.resolved = null; }, f => { f.contract.runtimeObserved = null; }, f => { f.observation.complete = false; },
    f => { f.observation.gaps = ["critical-sequence"]; }, f => { f.unknownMutators = ["writer"]; },
    f => { f.failures = [failure]; }, f => { f.checks[0].artifactId = null; }, f => { f.checks[0].status = "unknown"; },
    f => { f.checks[1].source = "claim"; }, f => { f.checks[0].snapshot = "old"; }, f => { f.checks[0].specVersion = 0; }, f => { f.checks[0].policyDigest = "old"; }];
  const good = acceptedCandidate(); assert.equal(outcome(good.spec, good.facts).status, "COMPLETED");
  for (const mutate of mutations) {
    const { spec, facts } = acceptedCandidate(); mutate(facts); const before = structuredClone(facts);
    const result = outcome(spec, facts); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.length); assert.deepEqual(facts, before);
  }
  for (const target of ["RUNNING", "COMPLETED"] as const) assert.throws(() => transition("CANCELLED", target));
});
