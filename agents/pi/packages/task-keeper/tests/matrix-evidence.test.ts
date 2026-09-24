import { test, assert } from "./recorded-test.ts";
import { matrixCoverage, validateDiscovery, type ExpandedMatrix, type MatrixEvidence } from "../src/contracts/test-plan.ts";
const plan: ExpandedMatrix[] = [{ id: "await", layers: ["S", "A"], cases: [{ id: "revoke-first" }, { id: "await-first" }] }];
const good: MatrixEvidence = { matrix: "await", variant: "revoke-first", level: "S", status: "passed", assertions: 2,
  file: "case.test.ts", name: "[S] actual case", artifact: "run/tests.tap", lockDigest: "current" };
test("[U VAL-017] one await order or layer cannot certify its unexecuted reverse order", () => {
  const result = matrixCoverage(plan, [good], "current");
  assert.deepEqual(result.credited, ["await:revoke-first:S"]);
  assert.deepEqual(result.missing, ["await:revoke-first:A", "await:await-first:S", "await:await-first:A"]);
  assert.equal(result.ready, false);
  const complete = plan[0].cases.flatMap(variant => plan[0].layers.map(level => ({ ...good, variant: variant.id, level })));
  assert.equal(matrixCoverage(plan, complete, "current").ready, true);
  for (const change of [{ assertions: 0 }, { status: "skipped" as const }, { status: "failed" as const }, { lockDigest: "old" }, { artifact: "" }, { file: "" }]) {
    const changed = [ { ...complete[0], ...change }, ...complete.slice(1) ];
    assert.equal(matrixCoverage(plan, changed, "current").ready, false);
  }
  assert.equal(matrixCoverage(plan, [...complete, { ...good, status: "failed" }], "current").ready, false);
  assert.throws(() => matrixCoverage(plan, [{ ...good, variant: "invented" }], "current"), /UNKNOWN_MATRIX_OBLIGATION/);
  assert.throws(() => matrixCoverage(plan, [{ ...good, level: "P" }], "current"), /UNKNOWN_MATRIX_OBLIGATION/);
  assert.throws(() => matrixCoverage([plan[0], plan[0]], [], "current"), /DUPLICATE_MATRIX_OBLIGATION/);
  assert.equal(matrixCoverage([], [], "current").ready, false);
});

test("[U VAL-013] variant assertions cannot borrow a test's aggregate count", () => {
  const identity = { file: "case.test.ts", name: "[S] test" };
  const execution = { ...identity, status: "passed" as const, assertions: 1, matrixAssertions: { "await:revoke-first": 1 } };
  assert.equal(validateDiscovery([identity], [execution], []).notExecuted.length, 0);
  assert.throws(() => validateDiscovery([identity], [{ ...execution, matrixAssertions: { "await:revoke-first": 1, "await:await-first": 1 } }], []), /INVALID_MATRIX_ATTRIBUTION/);
  for (const bad of [-1, NaN, 1.5, Infinity]) assert.throws(() => validateDiscovery([identity], [{ ...execution, matrixAssertions: { "await:revoke-first": bad } }], []), /INVALID_MATRIX_ATTRIBUTION/);
});
