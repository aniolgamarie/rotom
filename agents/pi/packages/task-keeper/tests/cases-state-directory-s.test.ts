import { test, assert } from "./recorded-test.ts";
import { existsSync, unlinkSync, copyFileSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { migrateStore } from "../src/store/maintenance.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S SCH-011] changing database filename cannot allocate a second last-slot ledger in one state directory", t => {
  const root = isolatedDirectory(t), first = new Store(root, "custom.db"); t.after(() => first.close());
  const owner = first.claimOwner("scope", "owner"); first.prepare(owner, "running", "write", {}, [{ id: "host-child", capacity: 1, units: 1 }]);
  assert.throws(() => { const duplicate = new Store(root, "other.db"); duplicate.close(); }, { code: "STATE_DATABASE_CONFLICT" });
  assert.equal(existsSync(join(root, "other.db")), false); assert.equal(first.claims().length, 1);
  const same = new Store(root, "custom.db"); t.after(() => same.close()); assert.deepEqual(same.claims(), first.claims());
});

test("[S] maintenance resolves the configured database instead of assuming runtime.db", t => {
  const root = isolatedDirectory(t), store = new Store(root, "custom.db"); store.put("test", "preserved", { value: 1 }); store.close();
  assert.equal(migrateStore(root).changed, false); assert.equal(existsSync(join(root, "runtime.db")), false);
  const reopened = new Store(root, "custom.db"); t.after(() => reopened.close()); assert.deepEqual(reopened.get("test", "preserved"), { value: 1 });
});


test("[S] legacy adoption retains the existing budget and refuses a different ledger", t => {
  const root = isolatedDirectory(t), first = new Store(root, "legacy.db"), owner = first.claimOwner("scope", "owner");
  first.prepare(owner, "intent", "write", {}); first.reserveRequest(owner, "intent", "unknown", [{id:"work",ceiling:1}]);
  first.settleRequest("unknown", "unknown"); first.close(); unlinkSync(join(root, ".task-keeper-database.json"));
  assert.throws(() => { const other = new Store(root, "runtime.db"); other.close(); }, {code:"STATE_DATABASE_CONFLICT"});
  assert.equal(existsSync(join(root, "runtime.db")), false);
  const original = new Store(root, "legacy.db"); t.after(() => original.close());
  assert.equal(original.bucket("work")!.reserved, 1); assert.equal(original.bucket("work")!.used, 0);
  assert.equal(original.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
});

test("[S] ambiguous legacy databases are preserved and require explicit reconciliation", t => {
  const root = isolatedDirectory(t), other = isolatedDirectory(t);
  new Store(root, "one.db").close(); new Store(other, "two.db").close(); unlinkSync(join(root, ".task-keeper-database.json"));
  for (const name of ["two.db", "two.db.identity"]) copyFileSync(join(other, name), join(root, name));
  const before = ["one.db", "two.db"].map(name => readFileSync(join(root, name)));
  assert.throws(() => new Store(root, "one.db"), {code:"STATE_DATABASE_CONFLICT"});
  assert.equal(existsSync(join(root, ".task-keeper-database.json")), false);
  for (const [index, name] of ["one.db", "two.db"].entries()) assert.deepEqual(readFileSync(join(root, name)), before[index]);
});

test("[S] malformed or public directory bindings cannot silently select a fresh database", t => {
  const root = isolatedDirectory(t); new Store(root).close(); const marker = join(root, ".task-keeper-database.json"), saved = readFileSync(marker);
  writeFileSync(marker, "broken"); assert.throws(() => new Store(root), {code:"INVALID_STATE_DATABASE_BINDING"});
  writeFileSync(marker, saved); chmodSync(marker, 0o644); assert.throws(() => new Store(root), {code:"STATE_DATABASE_BINDING_NOT_PRIVATE"});
  chmodSync(marker, 0o600); const restored = new Store(root); t.after(() => restored.close()); assert.equal(restored.path, join(root, "runtime.db"));
});
