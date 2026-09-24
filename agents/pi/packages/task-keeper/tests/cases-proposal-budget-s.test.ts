import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { DecisionLedger } from "../src/evidence/decision-ledger.ts";
import { compilePacket } from "../src/evidence/packet.ts";
import { outcome } from "../src/contracts/task.ts";
import { requestBudgetAvailable } from "../src/contracts/budget.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S RTB-019] accounting updates preserve a proposal identity while the dispatcher rechecks the remaining budget", t => {
  for (const expenses of [1, 4]) {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner"), ledger = new DecisionLedger(store, owner);
    const { spec, facts } = acceptedCandidate(); facts.checks = [];
    const receipt = outcome(spec, facts), identity = { ownerEpoch: owner.epoch, decisionRevision: 1 };
    const packet = compilePacket(spec, receipt, [], [], identity, { available: 4 }, 10000);
    const contract = ledger.authorize({ packetId: packet.id, action: "advance", target: "worker", reason: "continue the permitted implementation", evidenceIds: [] }, packet, ["worker"]);
    store.prepare(owner, "prior", "model", {});
    for (let i = 0; i < expenses; i++) { store.reserveRequest(owner, "prior", `spent-${i}`, [{ id: "budget", ceiling: 4 }]); store.settleRequest(`spent-${i}`, "sent"); }
    const current = compilePacket(spec, receipt, [], [], identity, { available: 4 - expenses }, 10000);
    assert.equal(current.id, packet.id); assert.equal(current.decisionRevision, contract.decisionRevision);
    const admit = () => ledger.admit(contract, current, [{ id: "slot", capacity: 1, units: 1 }], () => {
      const row = store.bucket("budget")!; return requestBudgetAvailable({ used: Number(row.used), reserved: Number(row.reserved), ceiling: Number(row.ceiling) });
    });
    if (expenses === 1) { assert.equal(admit().status, "prepared"); assert.equal(store.claims().length, 1); }
    else { assert.throws(admit, { code: "RESOURCE_DENIED" }); assert.equal(store.claims().length, 0); assert.equal(store.intent(`proposal-${contract.fingerprint}`), null); }
    assert.equal(store.bucket("budget")!.used, expenses); assert.equal(store.bucket("budget")!.reserved, 0);
    assert.deepEqual(spec.required, ["tests", "review"]); assert.equal(store.list("proposals").length, 1);
  }
});
