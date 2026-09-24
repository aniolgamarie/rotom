import { test, assert, evidence } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";

test("[S SCH-014 T42 TK14] elapsed lease time and replacement ownership never release an unresolved writer", t => {
  const root = isolatedDirectory(t), original = new Store(root), observer = new Store(root), clock = new FakeClock();
  t.after(() => { observer.close(); original.close(); });
  const old = original.claimOwner("scope", "original"), resource = [{ id: "shared-writer", capacity: 1, units: 1 }];
  original.prepare(old, "old-write", "write", { workspace: "candidate" }, resource);
  original.markSent(old, "old-write"); original.acknowledge("old-write", "native-original");
  original.reserveRequest(old, "old-write", "unknown-request", [{ id: "scope-budget", ceiling: 1 }]);
  original.settleRequest("unknown-request", "unknown");
  original.settle("old-write", "unknown");
  const accounting = observer.bucket("scope-budget"), trace: unknown[] = [];
  // State model: expiry is an elapsed-time observation, never physical process evidence.
  // The real writer/OS proof is separately covered by the P campaign.
  for (const elapsed of [1, 60_000, 86_400_000]) {
    clock.advance(elapsed);
    for (const id of ["SCH-014", "T42", "TK14"]) evidence(id, () => {
      assert.throws(() => observer.claimOwner("scope", "replacement"), { code: "OWNER_CONFLICT" });
      assert.equal(observer.intent("old-write")!.status, "unknown");
      assert.equal(observer.claims()[0].intent_id, "old-write");
      assert.deepEqual(observer.bucket("scope-budget"), accounting);
    });
    trace.push({ at: clock.now(), intent: observer.intent("old-write"), claims: observer.claims() });
  }
  original.revokeOwner(old); const replacement = observer.claimOwner("scope", "replacement");
  for (const id of ["SCH-014", "T42", "TK14"]) evidence(id, () => {
    assert.ok(replacement.epoch > old.epoch);
    assert.throws(() => observer.prepare(replacement, "replacement-write", "write", {}, resource), { code: "RESOURCE_DENIED" });
    assert.equal(observer.intent("replacement-write"), null);
    assert.equal(observer.intent("old-write")!.nativeId, "native-original");
    assert.deepEqual(observer.bucket("scope-budget"), accounting);
    assert.equal(trace.length, 3);
  });
  // Positive transition requires an explicit terminal fact about the original execution.
  observer.settle("old-write", "terminated");
  observer.prepare(replacement, "replacement-write", "write", {}, resource);
  for (const id of ["SCH-014", "T42", "TK14"]) evidence(id, () => {
    assert.equal(observer.intent("old-write")!.status, "settled");
    assert.deepEqual(observer.claims().map(c => c.intent_id), ["replacement-write"]);
    assert.deepEqual(observer.bucket("scope-budget"), accounting);
    assert.equal(observer.db.prepare("SELECT state FROM requests WHERE id=?").get("unknown-request")!.state, "unknown");
  });
});

test("[S TK07] either owner can win the last slot while the losing state transition leaves no intent or partial claim", t => {
  for (const id of ["TK07"]) evidence(id, () => {
    for (const order of [["a", "b"], ["b", "a"]]) {
      const first = new Store(isolatedDirectory(t)), second = new Store(first.root);
      t.after(() => { second.close(); first.close(); });
      const owners = order.map(id => first.claimOwner(id, id)), demand = [{ id: "host-child", capacity: 1, units: 1 }];
      first.prepare(owners[0], order[0], "write", {}, demand); first.markSent(owners[0], order[0]);
      assert.throws(() => second.prepare(owners[1], order[1], "write", {}, demand), { code: "RESOURCE_DENIED" });
      assert.equal(second.intent(order[1]), null); assert.equal(second.claims().length, 1);
      assert.equal(second.claims()[0].intent_id, order[0]);
      first.settle(order[0], "unknown");
      assert.throws(() => second.prepare(owners[1], order[1], "write", {}, demand), { code: "RESOURCE_DENIED" });
      first.settle(order[0], "terminated");
      assert.equal(second.prepare(owners[1], order[1], "write", {}, demand).status, "prepared");
      assert.equal(second.claims().length, 1); assert.equal(second.claims()[0].intent_id, order[1]);
    }
  });
});
