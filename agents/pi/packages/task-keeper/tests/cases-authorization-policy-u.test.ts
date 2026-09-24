import { test, assert } from "./recorded-test.ts";
import { configurationPolicyDigest } from "../src/config.ts";
import { compilePacket, authorizeProposal, recheck } from "../src/evidence/packet.ts";
import { outcome } from "../src/contracts/task.ts";
import { configured } from "./fixtures/config.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U CFG-007] a changed user execution policy invalidates old authorization and requires fresh acceptance evidence", () => {
  const config = configured(), { spec, facts } = acceptedCandidate(); spec.policyDigest = configurationPolicyDigest(config);
  facts.checks = facts.checks.map(check => ({ ...check, policyDigest: spec.policyDigest }));
  const receipt = outcome(spec, facts), identity = { ownerEpoch: 1, decisionRevision: 1 };
  const packet = compilePacket(spec, receipt, [], [], identity, { available: 1 }, 10000);
  const contract = authorizeProposal({ packetId: packet.id, action: "verify", target: "tests", reason: "check the current candidate", evidenceIds: [] }, packet, ["tests"], new Set());
  assert.equal(receipt.status, "COMPLETED"); assert.doesNotThrow(() => recheck(contract, packet, true, false));
  const before = structuredClone({ config, spec, facts, contract });
  for (const field of ["model", "profile", "budget"] as const) {
    const changed = structuredClone(config);
    if (field === "model") changed.routes.primary.model = "new-user-bound-model";
    else if (field === "profile") changed.executionProfiles.interactive.timeoutMs++;
    else changed.budget.protectedAttemptsPerWorkScope++;
    const policyDigest = configurationPolicyDigest(changed);
    assert.notEqual(policyDigest, spec.policyDigest);
    assert.throws(() => recheck(contract, { ...packet, policyDigest }, true, false), { code: "STALE_PROPOSAL" });
    const revisedSpec = { ...spec, version: 2, policyDigest }, currentReceipt = outcome(revisedSpec, facts);
    assert.equal(currentReceipt.status, "BLOCKED"); assert.ok(currentReceipt.reasons.includes("required:tests")); assert.ok(currentReceipt.reasons.includes("required:review"));
    const currentPacket = compilePacket(revisedSpec, currentReceipt, [], [], { ...identity, decisionRevision: 2 }, { available: 1 }, 10000);
    const fresh = authorizeProposal({ packetId: currentPacket.id, action: "verify", target: "tests", reason: "recheck after authorization changed", evidenceIds: [] }, currentPacket, ["tests"], new Set());
    assert.doesNotThrow(() => recheck(fresh, currentPacket, true, false)); assert.equal(outcome(revisedSpec, facts).status, "BLOCKED");
  }
  const presentation = structuredClone(config); presentation.evidence.packetByteBudget++;
  assert.equal(configurationPolicyDigest(presentation), spec.policyDigest);
  assert.doesNotThrow(() => recheck(contract, { ...packet, policyDigest: configurationPolicyDigest(presentation) }, true, false));
  assert.deepEqual({ config, spec, facts, contract }, before);
});
