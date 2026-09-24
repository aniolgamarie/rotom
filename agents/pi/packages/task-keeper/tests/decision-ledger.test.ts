import { test, assert } from "./recorded-test.ts";
import { DecisionLedger } from "../src/evidence/decision-ledger.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";
import type { Packet } from "../src/evidence/packet.ts";

test("[S EVD-007 EVD-008 EVD-009 T59 T60 T62 T63 T64 T65 T70 T85] durable proposal identity survives adapter recreation and rechecks final resources", (t) => {
  const root = isolatedDirectory(t), store = new Store(root), owner = store.claimOwner("scope", "owner"); t.after(() => store.close());
  const packet: Packet = { id: "packet", jobId: "job", specVersion: 1, snapshot: "snapshot", policyDigest: "policy", decisionRevision: 1, ownerEpoch: owner.epoch,
    blockers: [], required: ["test"], budget: { available: 2 }, references: [], claims: [], failureGroups: [], digest: "packet-digest" };
  const input = { packetId: "packet", action: "verify", target: "tests", reason: "check", evidenceIds: [] };
  const first = new DecisionLedger(store, owner).authorize(input, packet, ["tests"]);
  const reopened = new Store(root); t.after(() => reopened.close()); const ledger = new DecisionLedger(reopened, owner);
  assert.throws(() => ledger.authorize({ ...input, reason: "different wording" }, packet, ["tests"]));
  assert.throws(() => ledger.admit({ ...first, proposal: { ...first.proposal, target: "unauthorized" } }, packet, [], () => true));
  assert.throws(() => ledger.admit(first, { ...packet, snapshot: "changed" }, [], () => true));
  assert.throws(() => ledger.admit(first, packet, [], () => false));
  assert.equal(store.claims().length, 0);
  const admitted = ledger.admit(first, { ...packet, budget: { available: 1 } }, [{ id: "resource", capacity: 1, units: 1 }], () => true);
  assert.equal(admitted.status, "prepared"); assert.equal(store.claims().length, 1);
  assert.throws(() => ledger.admit(first, packet, [], () => true));
});
