import { test, assert, evidence } from "./recorded-test.ts";
import { readFileSync } from "node:fs";
import { planObligations, coverageReport, parseCsv, type TestEvidence } from "../src/contracts/test-plan.ts";
import { parseConfig } from "../src/config.ts";

test("[U VAL-002 VAL-019] structural plan success cannot create runtime evidence or a code-coverage percentage", () => {
  const plan = planObligations([{ scenario_id: "CFG-001", required_layers: "U;E", test_families: "TP01", expected: "runtime must be checked",
    phase_gates: "P0", status: "passed", test_file: "planned.test.ts", test_name: "planned name" }],
  [{ id: "T01", required_layers: "U", test_families: "TP02", expected: "observe real outcome", release_gate: "P0", status: "passed" }]);
  for (const id of ["VAL-002", "VAL-019"]) evidence(id, () => {
    const empty = coverageReport(plan, [], "current");
    assert.equal(empty.planned, 2); assert.equal(empty.evidenceRecords, 0); assert.equal(empty.ready, false);
    assert.deepEqual(empty.missing, ["CFG-001:U", "CFG-001:E", "T01:U"]); assert.equal(empty.codeCoverage, "unavailable");
  });
  const actual: TestEvidence[] = plan.flatMap(item => item.levels.map(level => ({ id: item.id, level, status: "passed", assertions: 1,
    file: "executed.test.ts", name: `${item.id} ${level}`, artifact: "actual-run/tests.tap", lockDigest: "current" })));
  assert.equal(coverageReport(plan, actual, "current").ready, true);
  assert.equal(coverageReport(plan, actual, "current").codeCoverage, "unavailable");
});

test("[U VAL-003] deferred Advisor cases remain in the original plan and unsupported modes cannot activate", () => {
  const scenarios = parseCsv(readFileSync(new URL("./plan/scenario-test-matrix.csv", import.meta.url), "utf8"));
  const faults = parseCsv(readFileSync(new URL("./plan/fault-traceability.csv", import.meta.url), "utf8"));
  const plan = planObligations(scenarios, faults), report = coverageReport(plan, [], "current");
  for (const id of ["T66", "T68", "T69", "T75"]) {
    assert.ok(plan.some(item => item.id === id)); assert.ok(report.missing.some(key => key.startsWith(id + ":")));
  }
  assert.equal(parseConfig({ advisor: { mode: "off" } }).advisor.mode, "off");
  for (const mode of ["shadow", "online", "learning", "enabled"]) assert.throws(() => parseConfig({ advisor: { mode } }));
  assert.equal(report.ready, false);
});
