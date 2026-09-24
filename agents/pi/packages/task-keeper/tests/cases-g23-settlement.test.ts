import { test, assert, evidence } from "./recorded-test.ts";
import { requestSettlement, type RequestState, type RequestFact } from "../src/contracts/budget.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[U RTB-013] request settlement truth table keeps unknown reserved and rejects terminal contradictions", () => {
  const expected: Record<string, [number, number, boolean] | null> = {
    "reserved:unknown": [0, 0, true], "reserved:sent": [1, -1, true], "reserved:not_sent": [0, -1, true],
    "unknown:unknown": [0, 0, false], "unknown:sent": [1, -1, true], "unknown:not_sent": [0, -1, true],
    "sent:unknown": null, "sent:sent": [0, 0, false], "sent:not_sent": null,
    "not_sent:unknown": null, "not_sent:sent": null, "not_sent:not_sent": [0, 0, false],
  };
  for (const [key, wanted] of Object.entries(expected)) {
    const [state, fact] = key.split(":") as [RequestState, RequestFact];
    if (!wanted) assert.throws(() => requestSettlement(state, fact), { code: "CONFLICTING_REQUEST_FACT" });
    else { const result = requestSettlement(state, fact); assert.deepEqual([result.usedDelta, result.reservedDelta, result.changed], wanted); assert.equal(result.state, fact); }
  }
  assert.throws(() => requestSettlement("invalid" as RequestState, "sent"), { code: "INVALID_REQUEST_STATE" });
});

test("[S RTB-011 T31] unknown reservations survive a new incident and owner without becoming zero-cost", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); let owner = store.claimOwner("scope", "owner");
  store.prepare(owner, "first", "model", {}); store.reserveRequest(owner, "first", "unknown", [{ id: "work", ceiling: 2 }, { id: "incident-a", ceiling: 1 }]);
  store.settleRequest("unknown", "unknown"); store.revokeOwner(owner); owner = store.claimOwner("scope", "replacement"); store.prepare(owner, "second", "model", {});
  store.reserveRequest(owner, "second", "retry", [{ id: "work", ceiling: 2 }, { id: "incident-b", ceiling: 1 }]); store.settleRequest("retry", "sent");
  for (const id of ["RTB-011", "T31"]) evidence(id, () => {
    assert.equal(store.bucket("work")!.used, 1); assert.equal(store.bucket("work")!.reserved, 1); assert.equal(store.request("unknown")!.state, "unknown");
    assert.throws(() => store.reserveRequest(owner, "second", "replacement-attempt", [{ id: "work", ceiling: 999 }, { id: "fresh-incident", ceiling: 999 }]), { code: "BUDGET_DENIED" });
    assert.equal(store.request("replacement-attempt"), null); assert.equal(store.bucket("work")!.ceiling, 2); assert.equal(store.bucket("fresh-incident"), null);
  });
});

test("[S RTB-013 T29] independent retry and auxiliary attempts are charged once each, even with duplicate completion", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner");
  for (const purpose of ["primary", "native-retry", "summary", "compaction"]) {
    store.prepare(owner, purpose, purpose, {}); store.reserveRequest(owner, purpose, `request-${purpose}`, [{ id: "shared-work", ceiling: 4 }]);
    store.settleRequest(`request-${purpose}`, "unknown"); store.settleRequest(`request-${purpose}`, "sent"); store.settleRequest(`request-${purpose}`, "sent");
  }
  for (const id of ["RTB-013", "T29"]) evidence(id, () => {
    assert.equal(store.bucket("shared-work")!.used, 4); assert.equal(store.bucket("shared-work")!.reserved, 0);
    assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 4);
    assert.throws(() => store.reserveRequest(owner, "primary", "request-primary", [{ id: "shared-work", ceiling: 4 }]), { code: "DUPLICATE_REQUEST" });
    assert.throws(() => store.settleRequest("request-summary", "not_sent"), { code: "CONFLICTING_REQUEST_FACT" });
    assert.equal(store.bucket("shared-work")!.used, 4);
  });
});
