import { test, assert } from "./recorded-test.ts";
import { readFileSync, readdirSync } from "node:fs";
import { parseCsv, planObligations, verifyScenarioMapping, coverageReport } from "../src/contracts/test-plan.ts";

const root = new URL("./plan/", import.meta.url);
const scenarios = parseCsv(readFileSync(new URL("scenario-test-matrix.csv", root), "utf8"));
const faults = parseCsv(readFileSync(new URL("fault-traceability.csv", root), "utf8"));
const specs = Object.fromEntries(readdirSync(new URL("specs/", root)).map((name) => [
  `specs/${name}/spec.md`, readFileSync(new URL(`specs/${name}/spec.md`, root), "utf8"),
]));

test("[VAL-001 VAL-002] all reviewed obligations match their actual spec digest", () => {
  verifyScenarioMapping(specs, scenarios);
  const obligations = planObligations(scenarios, faults);
  assert.equal(obligations.length, 228);
  assert.equal(faults.filter((row) => /^T\d/.test(row.id)).length, 88);
  assert.equal(coverageReport(obligations, [], "lock").ready, false);
});

test("[VAL-012] changed requirements, duplicate mappings and missing tests fail closed", () => {
  const copy = structuredClone(specs);
  const first = Object.keys(copy)[0];
  copy[first] = copy[first].replace(/\*\*THEN\*\* /, "**THEN** changed ");
  assert.throws(() => verifyScenarioMapping(copy, scenarios));
  assert.throws(() => verifyScenarioMapping(specs, scenarios.slice(1)));
  assert.throws(() => planObligations([...scenarios, scenarios[0]], faults));
  assert.throws(() => planObligations([], faults));
});

test("[VAL-004 VAL-006 VAL-013 VAL-018 VAL-019] zero assertions, wrong levels, skipped results and stale evidence cannot certify", () => {
  const obligations = [{ id: "x", source: "scenario" as const, levels: ["P"], phase: "P1", planned: true }];
  const good = { id: "x", level: "P", status: "passed" as const, assertions: 1, file: "process.test.ts",
    name: "one winner", artifact: "observed.json", lockDigest: "lock" };
  assert.equal(coverageReport(obligations, [good], "lock").ready, true);
  for (const result of [{ ...good, assertions: 0 }, { ...good, status: "skipped" as const }, { ...good, artifact: "" }]) {
    assert.equal(coverageReport(obligations, [result], "lock").ready, false);
  }
  assert.equal(coverageReport(obligations, [good], "new-lock").ready, false);
  assert.throws(() => coverageReport(obligations, [{ ...good, level: "U" }], "lock"));
  assert.equal(coverageReport(obligations, [{ ...good, status: "failed" }, good], "lock").ready, false);
  assert.equal(coverageReport([], [], "lock").ready, false);
});

test("CSV preserves BOM, quotes, CRLF and multiline cells", () => {
  assert.deepEqual(parseCsv('\uFEFFa,b\r\nx,"comma, and ""quote""\nline"\r\n'), [{ a: "x", b: 'comma, and "quote"\nline' }]);
  assert.throws(() => parseCsv('a,b\nx,"broken'));
  assert.throws(() => parseCsv('a,a\nx,y'));
});
