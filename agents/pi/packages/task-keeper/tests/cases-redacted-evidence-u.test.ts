import { test, assert } from "./recorded-test.ts";
import { scrub } from "../src/reliability/classifier.ts";
import { compilePacket } from "../src/evidence/packet.ts";
import { outcome } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U T84] complete redaction of an error body retains failure identity, required blockers and grouped counts", () => {
  const { spec, facts } = acceptedCandidate(), secretBody = "Fixture confidential service response";
  facts.failures = [0, 1].map(n => ({ id: `required-${n}`, code: "REQUIRED_TEST_ERROR", layer: "verification", required: true,
    message: scrub(secretBody, [secretBody]), attemptId: `attempt-${n}`, resolvedBy: null }));
  const before = structuredClone(facts), receipt = outcome(spec, facts);
  const packet = compilePacket(spec, receipt, [], ["A redacted message does not mean success"], { ownerEpoch: 1, decisionRevision: 1 }, { available: 1 }, 10000);
  assert.equal(JSON.stringify(packet).includes(secretBody), false); assert.equal(packet.failureGroups[0].sample, "[redacted]");
  assert.equal(receipt.status, "BLOCKED"); assert.deepEqual(packet.blockers, ["unresolved:required-0", "unresolved:required-1"]);
  assert.equal(packet.failureGroups.length, 1); assert.equal(packet.failureGroups[0].code, "REQUIRED_TEST_ERROR");
  assert.equal(packet.failureGroups[0].layer, "verification"); assert.equal(packet.failureGroups[0].count, 2); assert.equal(packet.failureGroups[0].unresolved, 2);
  assert.deepEqual(packet.failureGroups[0].ids, ["required-0", "required-1"]); assert.deepEqual(packet.failureGroups[0].unresolvedIds, ["required-0", "required-1"]);
  assert.deepEqual(facts, before);
  facts.failures = []; assert.equal(outcome(spec, facts).status, "COMPLETED");
});
