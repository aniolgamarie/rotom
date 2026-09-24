import { test, assert, evidence } from "./recorded-test.ts";
import { validateDiscovery, attributedAssertions, coverageReport, type TestExecution, type TestObligation } from "../src/contracts/test-plan.ts";
const plan: TestObligation[] = ["VAL-013", "VAL-018"].map(id => ({ id, source: "scenario", levels: ["U", "V"], phase: "P0", planned: true }));
const declared = { file: "tests/case.test.ts", name: "[U VAL-013 VAL-018] assertion identity" };
const execution: TestExecution = { ...declared, status: "passed", assertions: 2, attributed: { "VAL-013": 1 } };
test("[U VAL-013] aggregate assertions cannot certify several obligations", async () => {
  assert.equal(attributedAssertions(execution, "VAL-013"), 1);
  assert.equal(attributedAssertions(execution, "VAL-018"), 0);
  assert.equal(validateDiscovery([declared], [execution], plan).unattributed.length, 1);
  assert.throws(() => validateDiscovery([declared], [{ ...execution, attributed: { "VAL-013": 3 } }], plan), { code: "INVALID_ASSERTION_ATTRIBUTION" });
  assert.throws(() => validateDiscovery([declared], [{ ...execution, attributed: { "T01": 1 } }], plan), { code: "INVALID_ASSERTION_ATTRIBUTION" });
  await evidence("VAL-013", async () => { await Promise.resolve(); assert.equal(2 + 2, 4); });
});
test("[U VAL-018] discovery and execution identities must agree and zero runs cannot pass", () => {
  assert.throws(() => validateDiscovery([], [], plan), /ZERO_DISCOVERED/);
  assert.throws(() => validateDiscovery([declared], [], plan), /ZERO_DISCOVERED/);
  assert.throws(() => validateDiscovery([declared, declared], [execution], plan), /DUPLICATE_OR_INVALID/);
  assert.throws(() => validateDiscovery([declared], [execution, execution], plan), /UNDISCOVERED_OR_DUPLICATE/);
  assert.throws(() => validateDiscovery([declared], [{ ...execution, name: "renamed" }], plan), /UNDISCOVERED/);
  assert.throws(() => validateDiscovery([{ ...declared, name: "[U VAL-999] unknown" }], [execution], plan), { code: "UNKNOWN_TEST_ID" });
  const skipped = { file: "tests/skipped.test.ts", name: "[U VAL-018] skipped" };
  assert.deepEqual(validateDiscovery([declared, skipped], [execution], plan).notExecuted, [skipped]);
  const good = { id: "VAL-018", level: "U", status: "passed" as const, assertions: 1, file: declared.file, name: declared.name, artifact: "artifact", lockDigest: "lock" };
  const one = plan.filter(item => item.id === "VAL-018").map(item => ({ ...item, levels: ["U"] }));
  assert.equal(coverageReport(one, [good], "lock").ready, true);
  for (const patch of [{ assertions: 0 }, { status: "skipped" as const }, { artifact: "" }, { lockDigest: "stale" }]) assert.equal(coverageReport(one, [{ ...good, ...patch }], "lock").ready, false);
});
