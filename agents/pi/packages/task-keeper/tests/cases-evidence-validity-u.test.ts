import { test, assert, evidence } from "./recorded-test.ts";
import { coverageReport, type TestEvidence, type TestObligation } from "../src/contracts/test-plan.ts";

const obligation = (id: string, levels: string[]): TestObligation => ({ id, levels, source: "scenario", phase: "P1", planned: true });
const fact = (id: string, level: string): TestEvidence => ({ id, level, status: "passed", assertions: 1,
  file: "fixture.test.ts", name: "explicit report input", artifact: "retained-observer.json", lockDigest: "candidate" });

test("[U VAL-004 VAL-006] offline or smoke-only evidence leaves live recovery acceptance pending", () => {
  // These are synthetic inputs to the reporting contract, not live service evidence.
  const plan = [obligation("VAL-004", ["U", "V"]), obligation("VAL-007", ["A", "E", "L", "V"])];
  const offline = [fact("VAL-004", "U"), fact("VAL-004", "V")];
  evidence("VAL-004", () => {
    const report = coverageReport(plan, offline, "candidate");
    assert.equal(report.ready, false);
    assert.deepEqual(report.missing, ["VAL-007:A", "VAL-007:E", "VAL-007:L", "VAL-007:V"]);
    assert.deepEqual(coverageReport([plan[0]], offline, "candidate").missing, []);
  });
  evidence("VAL-006", () => {
    const both = [obligation("VAL-005", ["L"]), obligation("VAL-007", ["L"])];
    const smoke = fact("VAL-005", "L"), before = structuredClone(smoke);
    assert.deepEqual(coverageReport(both, [smoke], "candidate").missing, ["VAL-007:L"]);
    assert.equal(coverageReport(both, [smoke], "candidate").ready, false);
    assert.deepEqual(smoke, before);
    // An independent current recovery record is necessary; another profile's
    // evidence or an unavailable/skipped recovery cannot substitute for it.
    for (const patch of [{ lockDigest: "another-profile" }, { status: "skipped" as const }, { artifact: "" }])
      assert.equal(coverageReport(both, [smoke, { ...fact("VAL-007", "L"), ...patch }], "candidate").ready, false);
    assert.equal(coverageReport(both, [smoke, fact("VAL-007", "L")], "candidate").ready, true);
  });
});

test("[U VAL-018] malformed assertion counts and execution states cannot become passing evidence", () => {
  const plan = [obligation("VAL-018", ["U"])], good = fact("VAL-018", "U");
  assert.equal(coverageReport(plan, [good], "candidate").ready, true);
  assert.equal(coverageReport(plan, [{ ...good, assertions: 0 }], "candidate").ready, false);
  for (const assertions of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])
    assert.throws(() => coverageReport(plan, [{ ...good, assertions }], "candidate"), { code: "INVALID_TEST_EVIDENCE" });
  assert.throws(() => coverageReport(plan, [{ ...good, status: "finished" as TestEvidence["status"] }], "candidate"), { code: "INVALID_TEST_EVIDENCE" });
});
