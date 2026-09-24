import { test, assert, evidence, matrixCase } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { DecisionLedger } from "../src/evidence/decision-ledger.ts";
import type { Packet } from "../src/evidence/packet.ts";
import { isolatedDirectory } from "./helpers.ts";

for (const kind of ["start", "proposal"] as const)
test(`[S ${kind === "start" ? "EXE-008 T39" : "T71"}] an unacknowledged ${kind} retains its original durable identity across owner replacement and late settlement`, t => {
  const store = new Store(isolatedDirectory(t)), reader = new Store(store.root); t.after(() => { reader.close(); store.close(); });
  const owner = store.claimOwner("scope", "owner"), resources = [{ id: "writer", units: 1, capacity: 1 }];
  const packet: Packet = { id: "packet", jobId: "job", specVersion: 1, snapshot: "original-tree", policyDigest: "policy", decisionRevision: 1,
    ownerEpoch: owner.epoch, blockers: [], required: ["tests"], budget: { available: 1 }, references: [], claims: [], failureGroups: [], digest: "packet-digest" };
  const ledger = new DecisionLedger(store, owner);
  const contract = kind === "proposal" ? ledger.authorize({ packetId: packet.id, action: "advance", target: "implementation", reason: "bounded advance", evidenceIds: [] }, packet, ["implementation"]) : null;
  const intent = contract ? ledger.admit(contract, packet, resources, () => true) : store.prepare(owner, "original-start", "start", { jobId: "job", snapshot: "original-tree" }, resources);
  store.reserveRequest(owner, intent.id, "original-request", [{ id: "work-scope", ceiling: 1 }]); store.markSent(owner, intent.id);
  // Declared C2 state: the external action may have taken effect; its native acknowledgement is unavailable.
  store.settle(intent.id, "unknown"); store.settleRequest("original-request", "unknown"); const payload = structuredClone(store.intent(intent.id)!.payload);
  store.revokeOwner(owner); const next = reader.claimOwner("scope", "replacement");
  const ids = kind === "start" ? ["EXE-008", "T39"] : ["T71"];
  for (const id of ids) evidence(id, () => {
    assert.equal(reader.intent(intent.id)!.status, "unknown"); assert.equal(reader.intent(intent.id)!.nativeId, null);
    assert.throws(() => store.markSent(owner, intent.id), { code: "CONTROL_REVOKED" });
    assert.throws(() => reader.prepare(next, intent.id, kind, {}, resources), { code: "DUPLICATE_INTENT" });
    assert.throws(() => reader.prepare(next, "replacement-start", kind, {}, resources), { code: "RESOURCE_DENIED" });
    assert.equal(reader.intent("replacement-start"), null); assert.equal(reader.claims().length, 1);
    assert.equal(reader.bucket("work-scope")!.reserved, 1); assert.deepEqual(reader.intent(intent.id)!.payload, payload);
  });
  if (contract) assert.throws(() => new DecisionLedger(reader, next).admit(contract, { ...packet, ownerEpoch: next.epoch }, resources, () => true), { code: "STALE_PROPOSAL" });
  reader.acknowledge(intent.id, "original-native");
  assert.equal(reader.intent(intent.id)!.status, "acked"); assert.equal(reader.claims().length, 1);
  assert.throws(() => reader.acknowledge(intent.id, "different-native"), { code: "ACK_IDENTITY_CONFLICT" });
  reader.settle(intent.id, "terminated"); reader.settleRequest("original-request", "sent"); reader.settleRequest("original-request", "sent");
  reader.prepare(next, "new-model", kind, {}, resources);
  assert.throws(() => reader.reserveRequest(next, "new-model", "new-request", [{ id: "work-scope", ceiling: 1 }]), { code: "BUDGET_DENIED" });
  assert.equal(reader.request("new-request"), null); reader.settle("new-model", "not_sent");
  const finalAssertions = () => {
    assert.equal(reader.intent(intent.id)!.nativeId, "original-native"); assert.equal(reader.intent(intent.id)!.status, "settled");
    assert.equal(reader.bucket("work-scope")!.used, 1); assert.equal(reader.bucket("work-scope")!.reserved, 0); assert.equal(reader.claims().length, 0);
    assert.equal(reader.intent("new-model")!.status, "not_sent"); assert.equal(reader.intent("new-model")!.nativeId, null);
    assert.equal(reader.claims().length, 0); assert.equal(reader.db.prepare("SELECT count(*) n FROM intents WHERE native_id IS NOT NULL").get()!.n, 1);
    assert.deepEqual(reader.intent(intent.id)!.payload, payload);
  };
  for (const id of ids) evidence(id, finalAssertions);
  if (kind === "start") matrixCase("crash-cuts", "start.C2", finalAssertions);
});
