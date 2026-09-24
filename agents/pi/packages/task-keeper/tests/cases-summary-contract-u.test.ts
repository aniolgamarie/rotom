import { test, assert } from "./recorded-test.ts";
import { compilePacket } from "../src/evidence/packet.ts";
import { outcome } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U T11] a lossy summary cannot hide failure classes, counts or the current receipt identity", () => {
  const { spec, facts } = acceptedCandidate(); spec.version = 2; spec.snapshot = "current-tree";
  facts.failures = ["tool", "provider", "verification"].flatMap((layer, index) => [0, 1].map(n => ({ id: `failure-${index}-${n}`,
    layer: layer as "tool" | "provider" | "verification", code: `CODE_${index}`, message: "Earlier detailed failure", attemptId: `attempt-${index}`,
    required: true, resolvedBy: "artifact-tests" })));
  const receipt = outcome(spec, facts);
  for (const summary of ["Everything passed", "Earlier errors were omitted", ""]) {
    const packet = compilePacket(spec, receipt, [], [summary], { ownerEpoch: 1, decisionRevision: 2 }, { available: 1 }, 20000);
    assert.equal(receipt.status, "BLOCKED"); assert.equal(packet.jobId, receipt.jobId); assert.equal(packet.specVersion, 2); assert.equal(packet.snapshot, "current-tree");
    assert.deepEqual(packet.failureGroups.map(group => group.code).sort(), ["CODE_0", "CODE_1", "CODE_2"]);
    assert.equal(packet.failureGroups.reduce((n, group) => n + group.count, 0), 6);
    assert.equal(packet.failureGroups.reduce((n, group) => n + group.unresolved, 0), 6);
    assert.deepEqual(packet.failureGroups.flatMap(group => group.unresolvedIds).sort(), facts.failures.map(failure => failure.id).sort());
    assert.deepEqual(packet.blockers, receipt.reasons);
  }
});
