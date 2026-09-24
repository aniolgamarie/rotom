import { test, assert, evidence } from "./recorded-test.ts";
import { outcome, presentReceipt } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U EXE-003 T06 T07] registration or completion claims cannot fill a missing reporter observation", () => {
  for (const id of ["EXE-003", "T06", "T07"]) evidence(id, () => {
    const { spec, facts } = acceptedCandidate(); assert.equal(outcome(spec, facts).status, "COMPLETED");
    for (const observation of [{ complete: false, gaps: [] }, { complete: true, gaps: ["registration-readback"] }, { complete: false, gaps: ["event-channel"] }]) {
      const input = structuredClone(facts); input.observation = observation; input.claims = ["reporter registered", "ready", "all done"];
      const result = outcome(spec, input); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes("observation_incomplete"));
      assert.equal(result.nativeStatus, "completed"); assert.ok(presentReceipt(result).includes("observation_incomplete"));
    }
  });
});

test("[U EXE-004 T08] silent mode thinking or workspace downgrade remains distinct from requested identity", () => {
  for (const id of ["EXE-004", "T08"]) evidence(id, () => {
    const { spec, facts } = acceptedCandidate();
    facts.contract = { requested: { mode: "fork", thinking: "high", cwd: "isolated" }, resolved: { mode: "fork", thinking: "high", cwd: "isolated" },
      runtimeObserved: { mode: "fork", thinking: "high", cwd: "isolated" }, violations: [] };
    assert.equal(outcome(spec, facts).status, "COMPLETED");
    for (const [key, value] of [["mode", "fresh"], ["thinking", "off"], ["cwd", "shared"]]) for (const target of ["resolved", "runtimeObserved"] as const) {
      const input = structuredClone(facts); input.contract[target]![key] = value;
      const result = outcome(spec, input); assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes(`contract_mismatch:${key}`));
      assert.deepEqual(input.contract.requested, facts.contract.requested); assert.equal(input.contract[target]![key], value);
    }
  });
});

test("[U EXE-007] healthy execution retains independent native identity and optional observation metadata", () => {
  const { spec, facts } = acceptedCandidate(), before = structuredClone(facts), result = outcome(spec, facts);
  assert.equal(result.status, "COMPLETED"); assert.equal(result.nativeStatus, "completed"); assert.deepEqual(result.reasons, []);
  assert.equal(result.jobId, spec.id); assert.equal(result.snapshot, spec.snapshot); assert.equal(result.specVersion, spec.version);
  assert.ok(facts.nativeRunId); assert.deepEqual(facts, before);
  const extra = structuredClone(facts); extra.contract.runtimeObserved!.optionalRuntimeLabel = null;
  assert.equal(outcome(spec, extra).status, "COMPLETED");
  const missing = structuredClone(facts); missing.nativeRunId = null;
  assert.equal(outcome(spec, missing).status, "BLOCKED");
});

test("[U WFL-005 T45] old checks or check policy cannot certify a new snapshot or acceptance version", () => {
  for (const id of ["WFL-005", "T45"]) evidence(id, () => {
    const { spec, facts } = acceptedCandidate(); assert.equal(outcome(spec, facts).status, "COMPLETED");
    for (const change of [{ snapshot: "changed-candidate" }, { policyDigest: "changed-filter-or-threshold" }, { version: spec.version + 1 }]) {
      const revised = { ...spec, ...change }, before = structuredClone(facts), result = outcome(revised, facts);
      assert.equal(result.status, "BLOCKED"); assert.ok(result.reasons.includes("required:tests")); assert.ok(result.reasons.includes("required:review"));
      assert.deepEqual(facts, before);
    }
  });
});
