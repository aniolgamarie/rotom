import { test, assert, evidence } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S EVD-001 T14] a missing event blocks new admission and repairing its sequence does not invent writer termination", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner");
  store.prepare(owner, "original", "write", {}, [{ id: "writer", capacity: 1, units: 1 }]); store.markSent(owner, "original");
  store.settle("original", "unknown");
  const event = { id: "event-1", producer: "producer", seq: 1, scopeId: "scope", kind: "observation", payload: { nativeStatus: "running" } };
  store.append(event); store.append({ ...event, id: "event-3", seq: 3, payload: { nativeStatus: "ended" } });
  for (const id of ["EVD-001", "T14"]) evidence(id, () => {
    assert.deepEqual(store.sequenceGaps("scope"), [{ producer: "producer", expected: 2, actual: 3 }]);
    assert.throws(() => store.prepare(owner, "unsafe", "continue", {}), { code: "EVIDENCE_GAP" }); assert.equal(store.intent("unsafe"), null);
    assert.equal(store.intent("original")!.status, "unknown"); assert.equal(store.claims().length, 1);
  });
  store.append({ ...event, id: "event-2", seq: 2 });
  for (const id of ["EVD-001", "T14"]) evidence(id, () => {
    assert.deepEqual(store.sequenceGaps("scope"), []); assert.equal(store.intent("original")!.status, "unknown");
    assert.throws(() => store.prepare(owner, "second-writer", "write", {}, [{ id: "writer", capacity: 1, units: 1 }]), { code: "RESOURCE_DENIED" });
    assert.equal(store.intent("second-writer"), null);
  });
  store.acknowledge("original", "observed-native"); store.settle("original", "terminated");
  store.prepare(owner, "second-writer", "write", {}, [{ id: "writer", capacity: 1, units: 1 }]);
  assert.equal(store.intent("second-writer")!.status, "prepared"); assert.equal(store.claims().length, 1);
});

test("[S EVD-001 T15] replayed completion retains one intent, one native identity and one budget charge", t => {
  const root = isolatedDirectory(t), store = new Store(root), observer = new Store(root);
  t.after(() => { observer.close(); store.close(); }); const owner = store.claimOwner("scope", "owner");
  store.prepare(owner, "original", "continue", {}); store.reserveRequest(owner, "original", "request", [{ id: "budget", ceiling: 1 }]); store.markSent(owner, "original");
  const event = { id: "completed", producer: "native", seq: 1, scopeId: "scope", kind: "completed", payload: { intentId: "original", nativeId: "native-run" } };
  assert.equal(store.append(event), "inserted");
  for (let delivery = 0; delivery < 3; delivery++) {
    store.acknowledge("original", "native-run"); store.settle("original", "terminated"); store.settleRequest("request", "sent");
    for (const id of ["EVD-001", "T15"]) evidence(id, () => {
      assert.equal(observer.append(structuredClone(event)), "duplicate"); assert.equal(observer.events("scope").length, 1);
      assert.equal(observer.intent("original")!.nativeId, "native-run"); assert.equal(observer.intent("original")!.status, "settled");
      assert.equal(observer.bucket("budget")!.used, 1); assert.equal(observer.bucket("budget")!.reserved, 0);
      assert.throws(() => store.prepare(owner, "original", "continue", {}), { code: "DUPLICATE_INTENT" });
      assert.equal(observer.db.prepare("SELECT count(*) n FROM intents").get()!.n, 1); assert.equal(observer.issues("scope").length, 0);
    });
  }
});

test("[S EVD-002] event ID and producer-sequence collisions preserve prior payloads and fence every implicated scope", t => {
  for (const collision of ["event-id", "sequence", "payload", "two-records"]) {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const first = { id: "event-a", producer: "producer-a", seq: 1, scopeId: "scope-a", kind: "failed", payload: { error: "required failure" } };
    store.append(first);
    if (collision === "two-records") store.append({ ...first, id: "event-b", producer: "producer-b", scopeId: "scope-b" });
    const incoming = { ...first, scopeId: "scope-new", ...(collision === "event-id" ? { producer: "foreign" }
      : collision === "sequence" ? { id: "new-id" } : collision === "two-records" ? { producer: "producer-b" } : { payload: { error: "hidden failure" } }) };
    assert.equal(store.append(incoming), "conflict"); assert.deepEqual(store.events("scope-a"), [first]);
    for (const scope of ["scope-a", "scope-new", ...(collision === "two-records" ? ["scope-b"] : [])]) {
      const owner = store.claimOwner(scope, `owner-${scope}`); assert.ok(store.issues(scope).some(issue => issue.kind === "event_conflict"));
      assert.throws(() => store.prepare(owner, `blocked-${scope}`, "write", {}), { code: "EVIDENCE_CONFLICT" });
    }
    const other = store.claimOwner("independent", "independent-owner");
    assert.equal(store.prepare(other, "independent-work", "read", {}).status, "prepared");
  }
});
