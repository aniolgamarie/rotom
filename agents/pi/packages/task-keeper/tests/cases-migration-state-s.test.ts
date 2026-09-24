import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { migrateStore, recoverMaintenance } from "../src/store/maintenance.ts";
import { DatabaseSync } from "node:sqlite";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { isolatedDirectory } from "./helpers.ts";

function legacy(root: string) {
  const store = new Store(root), owner = store.claimOwner("scope", "old-owner");
  store.prepare(owner, "writer", "write", { workspace: "retained" }, [{ id: "source", capacity: 1, units: 1 }]);
  store.markSent(owner, "writer"); store.acknowledge("writer", "native-writer");
  for (const state of ["sent", "unknown"] as const) {
    store.reserveRequest(owner, "writer", state, [{ id: "work-scope", ceiling: 2 }]); store.settleRequest(state, state);
  }
  store.settle("writer", "unknown");
  store.put("receipts", "job", { status: "BLOCKED", missing: ["independent-review"] });
  store.revokeOwner(owner); store.db.exec("DROP TABLE maintenance_history; PRAGMA user_version=1"); store.close();
}
function facts(path: string) {
  const db = new DatabaseSync(path);
  try {
    return Object.fromEntries(["owners", "intents", "claims", "buckets", "requests", "records"].map(table =>
      [table, db.prepare(`SELECT * FROM ${table} ORDER BY rowid`).all()]));
  } finally { db.close(); }
}

for (const cut of ["backed-up", "schema-written", "committed"] as const)
test(`[S T76] interrupted migration at ${cut} preserves spent and unknown requests through explicit recovery`, t => {
  const root = isolatedDirectory(t), path = join(root, "runtime.db"); legacy(root); const before = facts(path);
  assert.throws(() => new Store(root), { code: "DATABASE_MIGRATION_REQUIRED" });
  assert.throws(() => migrateStore(root, point => { if (point === cut) throw new Error("declared-cut"); }), /declared-cut/);
  assert.deepEqual(facts(path), before);
  assert.throws(() => new Store(root), { code: "STORE_MAINTENANCE_REQUIRED" });
  const recovered = recoverMaintenance(root, cut === "committed" ? "finish" : "rollback");
  assert.equal(recovered.version, cut === "committed" ? 3 : 1); assert.deepEqual(facts(path), before);
  assert.equal(existsSync(join(root, "runtime.db.maintenance")), false);
  if (cut !== "committed") migrateStore(root);
  const current = new Store(root); t.after(() => current.close());
  assert.deepEqual(facts(path), before); assert.equal(current.intent("writer")!.status, "unknown");
  assert.equal(current.bucket("work-scope")!.used, 1); assert.equal(current.bucket("work-scope")!.reserved, 1);
  const next = current.claimOwner("scope", "new-owner");
  assert.throws(() => current.prepare(next, "replacement", "write", {}, [{ id: "source", capacity: 1, units: 1 }]), { code: "RESOURCE_DENIED" });
  assert.equal(current.intent("replacement"), null);
});

for (const damage of ["intent", "budget"] as const)
test(`[S T76] ${damage} loss during migration cannot be accepted as a fresh zero-budget state`, t => {
  const root = isolatedDirectory(t), path = join(root, "runtime.db"); legacy(root);
  assert.throws(() => migrateStore(root, point => { if (point === "committed") throw new Error("declared-cut"); }), /declared-cut/);
  const db = new DatabaseSync(path);
  if (damage === "intent") db.exec("PRAGMA foreign_keys=OFF; DELETE FROM intents WHERE id='writer'");
  else db.exec("UPDATE buckets SET used=0,reserved=0");
  db.close(); const damaged = facts(path);
  for (const action of ["finish", "rollback"] as const) {
    assert.throws(() => recoverMaintenance(root, action)); assert.deepEqual(facts(path), damaged);
    assert.equal(existsSync(join(root, "runtime.db.maintenance")), true);
    assert.throws(() => new Store(root), { code: "STORE_MAINTENANCE_REQUIRED" });
  }
});
