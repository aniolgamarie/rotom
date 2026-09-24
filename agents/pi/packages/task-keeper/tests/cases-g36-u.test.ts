import { test, assert } from "./recorded-test.ts";
import { evaluate } from "../src/evidence/evaluation.ts";
import { evaluationStarts } from "./fixtures/evaluation.ts";
for (const id of ["VAL-009", "T74"]) test(`[U ${id}] TC-${id}-U start inventory retains infrastructure failures parked and censored runs`, () => {
  const runs = evaluationStarts(), inventory = runs.map(r => r.id), report = evaluate(runs, inventory), group = report.groups[0];
  assert.equal(report.totalStarted, 10); assert.equal(report.startInventoryVerified, true); assert.equal(group.successPerStarted, 4 / 10);
  assert.equal(group.failures, 2); assert.equal(group.infraFailures, 1); assert.equal(group.parked, 1); assert.equal(group.censored, 1); assert.equal(group.cancelled, 1);
  assert.equal(group.knownCost, 6); assert.equal(group.unknownCostRuns, 2); assert.equal(group.unknownRequests, 1); assert.equal(group.artifacts.length, 10);
  for (const removed of [4, 6, 7, 8, 9]) assert.throws(() => evaluate(runs.filter((_, i) => i !== removed), inventory), { code: "EVALUATION_START_INVENTORY_MISMATCH" });
  assert.throws(() => evaluate(runs, [...inventory, inventory[0]])); assert.equal(evaluate(runs).startInventoryVerified, false);
});
test("[U T73] TC-T73-U changing file names or family labels cannot hide shared issue or snapshot holdout leakage", () => {
  const runs = evaluationStarts();
  const dev = { ...runs[0], id: "development", family: "renamed-family", split: "development" as const, artifact: "renamed-file.json" };
  for (const change of [{ sourceSnapshot: "new-snapshot" }, { issueId: "new-issue" }, {}]) assert.throws(() => evaluate([runs[0], { ...dev, ...change }]), { code: "HOLDOUT_FAMILY_LEAKAGE" });
  const clean = evaluate([runs[0], { ...dev, issueId: "new-issue", sourceSnapshot: "new-snapshot" }]);
  assert.equal(clean.totalStarted, 2); assert.equal(clean.efficacyClaim, "not_established");
});
for (const id of ["VAL-010", "T75"]) test(`[U ${id}] TC-${id}-U an unexecuted shadow has no accepted outcome or established downstream utility`, () => {
  const run = { ...evaluationStarts()[0], accepted: null, executionMode: "shadow" as const };
  for (const level of ["L1", "L2", "L3"] as const) {
    const report = evaluate([{ ...run, level }], [run.id]);
    assert.equal(report.groups[0].accepted, 0); assert.equal(report.groups[0].shadowOnly, 1); assert.equal(report.groups[0].unknownOutcome, 1);
    assert.equal(report.efficacyClaim, "not_established");
  }
  assert.throws(() => evaluate([{ ...run, accepted: true }]), { code: "CONFLICTING_EVALUATION_OUTCOME" });
  assert.equal(evaluate(evaluationStarts()).groups[0].accepted, 4);
});
