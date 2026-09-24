import { test, assert, evidence } from "./recorded-test.ts";
import { chmodSync, statSync, writeFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

test("private SQLite reopens durable intents, unknown reservations and monotonic ownership", (t) => {
  const root = isolatedDirectory(t); let store = new Store(root);
  const owner = store.claimOwner("scope-1", "owner-1");
  store.prepare(owner, "intent-1", "continue", { leaf: "leaf-1" }, [{ id: "writer", capacity: 1, units: 1 }]);
  store.reserveRequest(owner, "intent-1", "request-1", [{ id: "budget", ceiling: 1 }]);
  store.markSent(owner, "intent-1"); store.settleRequest("request-1", "unknown"); store.revokeOwner(owner);
  store.close(); store = new Store(root);
  assert.equal(store.intent("intent-1")!.status, "sent");
  assert.equal(store.bucket("budget")!.reserved, 1);
  assert.equal(store.claims().length, 1);
  assert.throws(() => store.markSent(owner, "intent-1"));
  const next = store.claimOwner("scope-1", "owner-2"); assert.ok(next.epoch > owner.epoch);
  assert.throws(() => store.prepare(next, "intent-2", "start", {}, [{ id: "writer", capacity: 1, units: 1 }]));
  assert.equal(store.intent("intent-2"), null);
  store.acknowledge("intent-1", "native-1"); store.settle("intent-1", "terminated");
  assert.equal(store.claims().length, 0);
  store.settleRequest("request-1", "sent"); store.settleRequest("request-1", "sent");
  assert.equal(store.bucket("budget")!.used, 1); assert.equal(store.bucket("budget")!.reserved, 0);
  assert.equal(statSync(store.path).mode & 0o777, 0o600);
  store.close();
});

test("[S EVD-001 EVD-002 T14 T15] independent connections see deduplication, gaps and conflicting identities", (t) => {
  for (const id of ["T14", "T15"]) evidence(id, () => {
    const root = isolatedDirectory(t), a = new Store(root), b = new Store(root);
    t.after(() => { a.close(); b.close(); });
    const fact = { id: "event-1", producer: "producer-1", seq: 1, scopeId: "scope-1", kind: "failed", payload: { error: "ERROR" } };
    assert.equal(a.append(fact), "inserted"); assert.equal(b.append(fact), "duplicate");
    a.append({ ...fact, id: "event-3", seq: 3 });
    assert.deepEqual(b.sequenceGaps("scope-1"), [{ producer: "producer-1", expected: 2, actual: 3 }]);
    a.append({ ...fact, id: "event-2", seq: 2 }); assert.deepEqual(b.sequenceGaps("scope-1"), []);
    assert.equal(a.append({ ...fact, payload: { error: "hidden" } }), "conflict");
    assert.equal(b.events("scope-1")[0].payload.error, "ERROR"); assert.equal(b.issues("scope-1").length, 1);
    const owner = b.claimOwner("scope-1", "owner-1");
    assert.throws(() => b.prepare(owner, "intent-1", "continue", {}));
  });
});

test("[S TK04] multi-resource denial rolls back all new claims and preserves the winner", (t) => {
  const root = isolatedDirectory(t), store = new Store(root); t.after(() => store.close());
  const a = store.claimOwner("scope-a", "owner-a"), b = store.claimOwner("scope-b", "owner-b");
  store.prepare(a, "intent-a", "write", {}, [{ id: "b", capacity: 1, units: 1 }]);
  assert.throws(() => store.prepare(b, "intent-b", "write", {}, [{ id: "a", capacity: 1, units: 1 }, { id: "b", capacity: 1, units: 1 }]));
  assert.deepEqual(store.claims().map((c) => c.resource_id), ["b"]);
  store.settle("intent-a", "unknown"); assert.equal(store.claims().length, 1);
  store.settle("intent-a", "terminated");
  store.prepare(b, "intent-b", "write", {}, [{ id: "a", capacity: 1, units: 1 }, { id: "b", capacity: 1, units: 1 }]);
  assert.equal(store.claims().length, 2);
});

test("[S RTB-010 RTB-011 RTB-013 T28 T30 T31] budget reservations survive scope changes and duplicated settlement", (t) => {
  for (const id of ["T31"]) evidence(id, () => {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
    const owner = store.claimOwner("scope-1", "owner-1"); store.prepare(owner, "intent-1", "start", {});
    for (let i = 1; i <= 4; i++) {
      store.reserveRequest(owner, "intent-1", `request-${i}`, [{ id: "incident", ceiling: 4 }, { id: "work-scope", ceiling: 12 }]);
      store.settleRequest(`request-${i}`, "sent");
    }
    assert.throws(() => store.reserveRequest(owner, "intent-1", "request-5", [{ id: "incident", ceiling: 4 }]));
    assert.equal(store.bucket("incident")!.used, 4);
    assert.throws(() => store.reserveRequest(owner, "intent-1", "request-1", [{ id: "new-incident", ceiling: 100 }]));
    store.reserveRequest(owner, "intent-1", "unknown-request", [{ id: "work-scope", ceiling: 12 }]);
    store.settleRequest("unknown-request", "unknown"); assert.equal(store.bucket("work-scope")!.reserved, 1);
    store.settleRequest("unknown-request", "not_sent"); assert.equal(store.bucket("work-scope")!.reserved, 0);
    assert.throws(() => store.settleRequest("unknown-request", "sent"));
    assert.throws(() => store.reserveRequest(owner, "intent-1", "zero-request", [{ id: "zero", ceiling: 0 }]));
  });
});

test("[S EVD-013 T47 T76] snapshot backup preserves facts, newer/corrupt stores are not reset", (t) => {
  for (const id of ["T76"]) evidence(id, () => {
    const root = isolatedDirectory(t), store = new Store(root);
    store.put("receipts", "job-1", { status: "BLOCKED", unknown: true });
    const owner = store.claimOwner("scope", "owner");
    store.prepare(owner, "unsettled", "write", {}, [{ id: "writer", capacity: 1, units: 1 }]);
    store.reserveRequest(owner, "unsettled", "unknown-request", [{ id: "work", ceiling: 12 }]);
    store.settleRequest("unknown-request", "unknown"); store.settle("unsettled", "unknown");
    const backup = store.backup(); assert.equal(statSync(backup).mode & 0o777, 0o600);
    const copy = new DatabaseSync(backup); assert.equal(copy.prepare("SELECT count(*) AS n FROM records").get()!.n, 1);
    assert.equal(copy.prepare("SELECT status FROM intents WHERE id='unsettled'").get()!.status, "unknown");
    assert.equal(copy.prepare("SELECT reserved FROM buckets WHERE id='work'").get()!.reserved, 1);
    assert.equal(copy.prepare("SELECT count(*) AS n FROM claims").get()!.n, 1); copy.close();
    store.db.exec("PRAGMA user_version=99"); store.close();
    assert.throws(() => new Store(root));
    const existing = new DatabaseSync(join(root, "runtime.db")); assert.equal(existing.prepare("PRAGMA user_version").get()!.user_version, 99); existing.close();
    const badRoot = isolatedDirectory(t); writeFileSync(join(badRoot, "runtime.db"), "not a database", { mode: 0o600 });
    assert.throws(() => new Store(badRoot));
    const openRoot = isolatedDirectory(t); chmodSync(openRoot, 0o755); assert.throws(() => new Store(openRoot));
  });
});

test("[S EVD-013 T47 T76] a missing or truncated initialized database cannot silently reset budgets", (t) => {
  for (const id of ["T76"]) evidence(id, () => {
    for (const mode of ["remove", "truncate"] as const) {
      const root = isolatedDirectory(t), store = new Store(root); store.close();
      const path = join(root, "runtime.db");
      if (mode === "remove") unlinkSync(path); else writeFileSync(path, "");
      assert.throws(() => new Store(root), /DATABASE_LOST_NOT_FRESH/);
    }
  });
});
