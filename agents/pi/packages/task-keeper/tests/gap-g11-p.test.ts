import { test, assert } from "./recorded-test.ts";
import { fork } from "node:child_process";
import { once } from "node:events";
import { join } from "node:path";
import { readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { migrateStore, recoverMaintenance, businessDigest } from "../src/store/maintenance.ts";
import { processIdentity } from "../src/adapters/process-identity.ts";
import { isolatedDirectory } from "./helpers.ts";
function oldStore(root: string, filename = "runtime.db") {
  const store = new Store(root, filename), owner = store.claimOwner("scope", "owner");
  store.prepare(owner, "unknown-intent", "write", { workspace: "/retained/workspace" }, [{ id: "writer", capacity: 1, units: 1 }]);
  store.reserveRequest(owner, "unknown-intent", "request", [{ id: "work", ceiling: 12 }]);
  store.settleRequest("request", "unknown"); store.settle("unknown-intent", "unknown");
  store.put("receipts", "job", { status: "BLOCKED", snapshot: "original", failures: ["preserved"] });
  store.revokeOwner(owner);
  store.db.exec("DROP TABLE maintenance_history; PRAGMA user_version=1");
  return store;
}
function verify(root: string, expected: string, version: number, filename = "runtime.db") {
  const db = new DatabaseSync(join(root, filename));
  try {
    assert.equal(businessDigest(db), expected);
    assert.equal(db.prepare("PRAGMA user_version").get()!.user_version, version);
    assert.equal(db.prepare("SELECT status FROM intents").get()!.status, "unknown");
    assert.equal(db.prepare("SELECT reserved FROM buckets").get()!.reserved, 1);
    assert.equal(db.prepare("SELECT count(*) n FROM claims").get()!.n, 1);
  } finally { db.close(); }
}
for (const filename of ["runtime.db", "custom.db"]) for (const cut of ["fenced", "backed-up", "schema-written", "committed", "before-release"] as const) {
  test(`[P T76] ${filename} migration process killed at ${cut} preserves all intent and unknown facts`, { timeout: 15000 }, async t => {
    const root = isolatedDirectory(t), original = oldStore(root, filename), before = businessDigest(original.db); original.close();
    assert.throws(() => new Store(root, filename), { code: "DATABASE_MIGRATION_REQUIRED" });
    const child = fork(fileURLToPath(new URL("./fixtures/maintenance-worker.ts", import.meta.url)), [root, cut], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] });
    t.after(() => child.kill("SIGKILL"));
    assert.equal((await once(child, "message"))[0].type, "ready");
    const reached = once(child, "message"); child.send("go"); assert.equal((await reached)[0].type, "cut");
    assert.throws(() => new Store(root, filename), { code: "STORE_MAINTENANCE_REQUIRED" });
    const stopped = once(child, "exit"); child.kill("SIGKILL"); await stopped;
    const committed = ["committed", "before-release"].includes(cut);
    const result = recoverMaintenance(root, committed ? "finish" : "rollback");
    assert.equal(result.version, committed ? 3 : 1); verify(root, before, committed ? 3 : 1, filename);
    assert.equal(existsSync(join(root, `${filename}.maintenance`)), false);
    if (!committed) migrateStore(root);
    const current = new Store(root, filename); assert.equal(current.claims().length, 1); current.close();
    verify(root, before, 3, filename);
  });
}
test("[P T76] migration rejects live owners and unsafe rollback, backup corruption never resets a store", t => {
  const root = isolatedDirectory(t), old = oldStore(root), baseline = businessDigest(old.db);
  // Simulate the pre-upgrade connection: every writer still observes the durable fence.
  assert.throws(() => migrateStore(root, point => {
    if (point === "backed-up") { assert.throws(() => old.put("probe", "blocked", {}), { code: "STORE_MAINTENANCE_REQUIRED" }); throw new Error("injected failure"); }
  }), /injected failure/);
  const journal = JSON.parse(readFileSync(join(root, "runtime.db.maintenance"), "utf8"));
  const backup = join(root, journal.backup), saved = readFileSync(backup);
  writeFileSync(backup, "corrupt"); assert.throws(() => recoverMaintenance(root, "rollback"), { code: "BACKUP_HASH_MISMATCH" });
  verify(root, baseline, 1); assert.equal(existsSync(join(root, "runtime.db.maintenance")), true);
  writeFileSync(backup, saved); recoverMaintenance(root, "rollback");
  assert.throws(() => old.put("probe", "after-replace", {}), { code: "DATABASE_REPLACED_REOPEN_REQUIRED" }); old.close();
  migrateStore(root); verify(root, baseline, 3); assert.equal(statSync(backup).mode & 0o777, 0o600);
  const liveRoot = isolatedDirectory(t), live = oldStore(liveRoot);
  live.db.prepare("UPDATE owners SET active=1").run();
  const owner = live.owner("scope")!;
  live.put("owner-process", "scope", { token: owner.token, epoch: owner.epoch, identity: processIdentity() });
  assert.throws(() => migrateStore(liveRoot), { code: "MAINTENANCE_OWNER_NOT_STOPPED" });
  assert.equal(existsSync(join(liveRoot, "runtime.db.maintenance")), false); live.close();
});
test("[P T76] an out-of-band business change blocks rollback rather than losing newer budget", t => {
  const root = isolatedDirectory(t), old = oldStore(root); old.close();
  assert.throws(() => migrateStore(root, point => { if (point === "committed") throw new Error("hold"); }), /hold/);
  const db = new DatabaseSync(join(root, "runtime.db")); db.prepare("UPDATE buckets SET used=1").run(); db.close();
  assert.throws(() => recoverMaintenance(root, "rollback"), { code: "MAINTENANCE_SOURCE_CHANGED" });
  assert.throws(() => recoverMaintenance(root, "finish"), { code: "MAINTENANCE_SOURCE_CHANGED" });
  assert.equal(existsSync(join(root, "runtime.db.maintenance")), true);
});
