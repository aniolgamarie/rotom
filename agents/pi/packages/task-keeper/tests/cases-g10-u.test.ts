import { test, assert } from "./recorded-test.ts";
import { compilePacket, authorizeProposal, recheck } from "../src/evidence/packet.ts";
import { outcome } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";
function proposalFixture() {
  const { spec, facts } = acceptedCandidate();
  const packet = compilePacket(spec, outcome(spec, facts), [], [], { decisionRevision: 1, ownerEpoch: 1 }, { available: 3 }, 16000);
  const proposal = { packetId: packet.id, action: "verify", target: "tests", reason: "verify current inputs", evidenceIds: [] };
  return { spec, facts, packet, proposal };
}
for (const id of ["EVD-007", "T59", "T70"]) test(`[U ${id}] TC-${id}-U every changed decision identity or revoked admission invalidates dispatch`, () => {
  const x = proposalFixture(), contract = authorizeProposal(x.proposal, x.packet, ["tests"], new Set());
  assert.doesNotThrow(() => recheck(contract, x.packet, true, false));
  for (const change of [{ jobId: "other" }, { specVersion: 2 }, { snapshot: "new-tree" }, { policyDigest: "new-policy" }, { decisionRevision: 2 }, { ownerEpoch: 2 }])
    assert.throws(() => recheck(contract, { ...x.packet, ...change }, true, false), { code: "STALE_PROPOSAL" });
  assert.throws(() => recheck(contract, x.packet, true, true), { code: "CONTROL_REVOKED" });
  assert.throws(() => recheck(contract, x.packet, false, false), { code: "RESOURCE_DENIED" });
});
for (const id of ["EVD-008", "RTB-019", "T60", "T85"]) test(`[U ${id}] TC-${id}-U resource observations are rechecked without mechanically expiring the semantic proposal`, () => {
  const x = proposalFixture(), contract = authorizeProposal(x.proposal, x.packet, ["tests"], new Set());
  for (const remaining of [3, 2, 1, 0]) {
    const now = compilePacket(x.spec, outcome(x.spec, x.facts), [], [], { decisionRevision: 1, ownerEpoch: 1 }, { available: remaining }, 16000);
    assert.equal(now.decisionRevision, contract.decisionRevision); assert.equal(now.id, x.packet.id);
    if (remaining) assert.doesNotThrow(() => recheck(contract, now, true, false));
    else assert.throws(() => recheck(contract, now, false, false), { code: "RESOURCE_DENIED" });
  }
});
for (const id of ["EVD-009", "T63", "T64"]) test(`[U ${id}] TC-${id}-U untrusted proposal syntax or commands cannot become a default advance`, () => {
  const x = proposalFixture(), before = structuredClone(x.spec);
  for (const input of [null, [], "", "{}", '{"action":', '{}{}', { ...x.proposal, shell: "arbitrary" }, { ...x.proposal, provider: "unapproved" },
    { ...x.proposal, action: "finish-now" }, { ...x.proposal, target: "tests; arbitrary" }, { ...x.proposal, evidenceIds: ["invented"] }]) {
    const seen = new Set<string>(); assert.throws(() => authorizeProposal(input, x.packet, ["tests"], seen)); assert.equal(seen.size, 0);
  }
  assert.deepEqual(x.spec, before); assert.equal(authorizeProposal(x.proposal, x.packet, ["tests"], new Set()).proposal.action, "verify");
});
test("[U T62] TC-T62-U a proposal cannot delete required checks or change the root TaskSpec", () => {
  const x = proposalFixture(), before = structuredClone(x.spec);
  for (const extra of [{ required: [] }, { optional: ["tests"] }, { allowPartial: true }, { policyDigest: "new" }, { resetBudget: true }])
    assert.throws(() => authorizeProposal({ ...x.proposal, ...extra }, x.packet, ["tests"], new Set()), { code: "UNKNOWN_FIELD" });
  assert.deepEqual(x.spec, before); assert.deepEqual(x.packet.required, ["tests", "review"]);
});
test("[U T65] TC-T65-U duplicate decisions remain duplicates when the explanation or resource observation changes", () => {
  const x = proposalFixture(), seen = new Set<string>();
  const first = authorizeProposal(x.proposal, x.packet, ["tests"], seen); assert.equal(seen.size, 1);
  for (const reason of [x.proposal.reason, "same decision in different wording"]) {
    assert.throws(() => authorizeProposal({ ...x.proposal, reason }, { ...x.packet, budget: { available: 2 } }, ["tests"], seen), { code: "DUPLICATE_PROPOSAL" });
    assert.equal(seen.size, 1);
  }
  assert.doesNotThrow(() => recheck(first, x.packet, true, false));
});
