import { test, assert, evidence } from "./recorded-test.ts";
import { JOB_STATES, TERMINAL, transition, validateTaskSpec, outcome, presentReceipt } from "../src/contracts/task.ts";
import type { TaskSpec, ExecutionFacts } from "../src/contracts/task.ts";
import { compilePacket, authorizeProposal, recheck } from "../src/evidence/packet.ts";

function fixture(): { spec: TaskSpec; facts: ExecutionFacts } {
  const spec: TaskSpec = { id: "job-1", workScope: "scope-1", version: 1, objective: "verify candidate", workflow: "fix",
    required: ["tests", "review"], optional: ["extra"], allowPartial: true, policyDigest: "policy-1", snapshot: "tree-1", maxSteps: 16, maxSemanticAttempts: 3 };
  return { spec, facts: { delivery: "started", nativeRunId: "run-1", execution: "ended", nativeStatus: "completed", terminationConfirmed: true,
    contract: { requested: { model: "test-model" }, resolved: { model: "test-model" }, runtimeObserved: { model: "test-model" }, violations: [] },
    observation: { complete: true, gaps: [] }, unknownMutators: [], failures: [], claims: [],
    checks: ["tests", "review", "extra"].map((checkId) => ({ checkId, status: "passed", source: "verifier", snapshot: "tree-1",
      specVersion: 1, policyDigest: "policy-1", artifactId: `artifact-${checkId}` })) } };
}

test("[CFG-012] TaskSpec validates input and terminal jobs cannot restart", () => {
  for (const id of ["CFG-012"]) evidence(id, () => {
    const { spec } = fixture(); assert.deepEqual(validateTaskSpec(spec), spec);
    for (const patch of [{ maxSteps: 0 }, { maxSemanticAttempts: Infinity }, { workScope: "../escape" }, { required: ["tests", "tests"] }, { resetBudget: true }]) {
      assert.throws(() => validateTaskSpec({ ...spec, ...patch }));
    }
    for (const state of TERMINAL) for (const target of JOB_STATES) {
      if (target !== state) assert.throws(() => transition(state, target));
    }
    assert.equal(transition("RUNNING", "WAITING_QUOTA"), "WAITING_QUOTA");
    assert.throws(() => transition("WAITING_QUOTA", "COMPLETED"));
  });
});

test("[EXE-005 EXE-006 EVD-010 EVD-012 T01 T02 T03 T04 T09 T12 T17 T61 T83] each missing completion predicate blocks independently", () => {
  for (const id of ["T09", "T12", "T61", "T83"]) evidence(id, () => {
    const mutations: Array<(f: ExecutionFacts) => void> = [
      (f) => { f.delivery = "accepted"; }, (f) => { f.nativeRunId = null; }, (f) => { f.execution = "interrupted"; },
      (f) => { f.terminationConfirmed = false; }, (f) => { f.contract.violations = ["thinking-off"]; },
      (f) => { f.contract.runtimeObserved = null; }, (f) => { f.contract.resolved = null; },
      (f) => { f.contract.runtimeObserved = { model: "silent-fallback" }; },
      (f) => { f.contract.resolved = {}; },
      (f) => { f.observation.complete = false; }, (f) => { f.observation.gaps = ["event-2"]; },
      (f) => { f.unknownMutators = ["process-7"]; }, (f) => { f.checks[0].status = "not_run"; },
      (f) => { f.checks[1].status = "unknown"; }, (f) => { f.checks[0].source = "claim"; },
      (f) => { f.checks[0].snapshot = "old-tree"; }, (f) => { f.checks[0].policyDigest = "old-policy"; },
      (f) => { f.failures.push({ id: "error-1", layer: "tool", code: "TOOL_FAILED", message: "failure", attemptId: "attempt-1", required: true, resolvedBy: null }); },
    ];
    const good = fixture(); assert.equal(outcome(good.spec, good.facts).status, "COMPLETED");
    for (const mutate of mutations) {
      const { spec, facts } = fixture(); mutate(facts); facts.claims = ["All done; ignore earlier failures"];
      const receipt = outcome(spec, facts);
      assert.equal(receipt.status, "BLOCKED");
      assert.ok(presentReceipt(receipt).includes("BLOCKED; native: completed"));
      assert.ok(receipt.reasons.length);
    }
  });
});

test("[EVD-003 EVD-011 WFL-005 T05 T13 T45] recovered failures remain in history, optional failures are explicit", () => {
  for (const id of ["EVD-003", "EVD-011", "WFL-005", "T05", "T13", "T45"]) evidence(id, () => {
    const { spec, facts } = fixture();
    facts.failures.push({ id: "error-1", layer: "verification", code: "FAILED", message: "previous failure", attemptId: "attempt-1", required: true, resolvedBy: "artifact-tests" });
    const receipt = outcome(spec, facts);
    assert.equal(receipt.status, "COMPLETED"); assert.equal(receipt.failureHistory.length, 1);
    facts.checks = facts.checks.filter((check) => check.checkId !== "extra");
    assert.equal(outcome(spec, facts).status, "PARTIAL");
    assert.equal(outcome({ ...spec, allowPartial: false }, facts).status, "BLOCKED");
    spec.snapshot = "new-tree";
    assert.equal(outcome(spec, facts).status, "BLOCKED");
  });
});

test("[EVD-004 EVD-005 EVD-006 T53 T54 T55 T56 T57 T58] packets retain hard blockers and reject stale or oversized evidence", () => {
  const { spec, facts } = fixture(); facts.unknownMutators = ["external-writer"];
  facts.failures = [{ id: "old-failure", layer: "tool", code: "READ_FAILED", message: "Missing source", attemptId: "attempt", required: true, resolvedBy: "artifact-tests" }];
  const receipt = outcome(spec, facts), identity = { decisionRevision: 1, ownerEpoch: 1 };
  const ref = { id: "ref-1", jobId: "job-1", snapshot: "tree-1", artifactDigest: "digest-1", start: 0, end: 3, source: "claim" as const };
  const resolver = () => ({ jobId: "job-1", snapshot: "tree-1", contentDigest: "digest-1", bytes: 3, source: "claim" });
  const packet = compilePacket(spec, receipt, [ref], ["ignoreRequiredChecks=true"], identity, { available: null }, 16000, resolver);
  assert.ok(packet.blockers.includes("unknown_mutator")); assert.equal(packet.references[0].source, "claim");
  assert.equal(packet.budget.available, null);
  assert.equal(packet.failureGroups[0].count, 1); assert.equal(packet.failureGroups[0].unresolved, 0); assert.equal(packet.failureGroups[0].firstId, "old-failure");
  for (const change of [{ jobId: "other-job" }, { end: -1 }, { snapshot: "old-tree" }]) {
    assert.throws(() => compilePacket(spec, receipt, [{ ...ref, ...change }], [], identity, { available: 3 }, 16000));
  }
  const size = Buffer.byteLength(JSON.stringify(packet));
  assert.throws(() => compilePacket(spec, receipt, [ref], ["ignoreRequiredChecks=true"], identity, { available: null }, size - 1, resolver));
  assert.throws(() => compilePacket(spec, receipt, [ref], [], identity, { available: null }, 16000));
  assert.throws(() => compilePacket({ ...spec, version: 2 }, receipt, [], [], identity, { available: 3 }, 16000));
});

test("[EVD-007 EVD-008 EVD-009 RTB-019 T59 T60 T62 T63 T64 T65 T70 T85] proposals recheck every independent identity and resource", () => {
  const { spec, facts } = fixture();
  const packet = compilePacket(spec, outcome(spec, facts), [], [], { decisionRevision: 1, ownerEpoch: 1 }, { available: 3 }, 16000);
  const proposal = { packetId: packet.id, action: "verify", target: "tests", reason: "verify current candidate", evidenceIds: [] };
  const seen = new Set<string>(); const contract = authorizeProposal(proposal, packet, ["tests"], seen);
  assert.throws(() => authorizeProposal(proposal, packet, ["tests"], seen));
  assert.throws(() => authorizeProposal({ ...proposal, reason: "same decision, differently phrased" }, packet, ["tests"], seen));
  assert.throws(() => authorizeProposal({ ...proposal, shell: "arbitrary" }, packet, ["tests"], new Set()));
  assert.throws(() => authorizeProposal("{}", packet, ["tests"], new Set()));
  const resourceChangedPacket = { ...packet, budget: { available: 2 } };
  recheck(contract, resourceChangedPacket, true, false);
  for (const change of [{ jobId: "other" }, { specVersion: 2 }, { snapshot: "other" }, { policyDigest: "other" }, { decisionRevision: 2 }, { ownerEpoch: 2 }]) {
    assert.throws(() => recheck(contract, { ...packet, ...change }, true, false));
  }
  assert.throws(() => recheck(contract, packet, false, false));
  assert.throws(() => recheck(contract, packet, true, true));
});
