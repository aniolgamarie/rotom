import { test, assert, evidence } from "./recorded-test.ts";
import { writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { workScopeIdentity, resolveWorkScope, rememberWorkScope } from "../src/orchestration/work-scope.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[U SCH-001 T30] scope identity is inherited across runtime IDs and rejects conflicting or missing fork authority", () => {
  const initial = workScopeIdentity("parent", [], false);
  for (const id of ["SCH-001", "T30"]) evidence(id, () => {
    assert.equal(initial.reused, false); assert.match(initial.scopeId, /^managed-[a-f0-9]{64}$/);
    for (const runtimeId of ["parent", "resumed", "fork"]) {
      assert.deepEqual(workScopeIdentity(runtimeId, [initial.scopeId, undefined, initial.scopeId], runtimeId === "fork"), { scopeId: initial.scopeId, reused: true });
    }
    assert.notEqual(workScopeIdentity("independent", [], false).scopeId, initial.scopeId);
    assert.throws(() => workScopeIdentity("fork", [], true), { code: "FORK_SCOPE_UNAVAILABLE" });
    assert.throws(() => workScopeIdentity("fork", ["scope-a", "scope-b"], true), { code: "WORK_SCOPE_IDENTITY_CONFLICT" });
    for (const invalid of ["", null, false, [], {}, 0]) assert.throws(() => workScopeIdentity("resume", [invalid], false), { code: "WORK_SCOPE_REFERENCE_INVALID" });
  });
});

test("[S SCH-001 T30] reopening the same canonical session file under a different runtime ID retains its spent budget", t => {
  const root = isolatedDirectory(t), file = join(root, "parent.jsonl"), alias = join(root, "alias.jsonl");
  writeFileSync(file, '{"type":"session","id":"parent"}\n'); symlinkSync(file, alias);
  const store = new Store(join(root, "state")); t.after(() => store.close());
  const scopeId = resolveWorkScope(store, { id: "parent", file }), owner = store.claimOwner(scopeId, "owner");
  rememberWorkScope(store, "parent", file, scopeId);
  store.prepare(owner, "original", "model", {}); store.reserveRequest(owner, "original", "spent", [{ id: `work-${scopeId}`, ceiling: 1 }]); store.settleRequest("spent", "sent");
  for (const id of ["SCH-001", "T30"]) evidence(id, () => {
    const restored = resolveWorkScope(store, { id: "new-runtime-id", file: alias }); assert.equal(restored, scopeId);
    assert.equal(store.bucket(`work-${restored}`)!.used, 1); assert.equal(store.bucket(`work-${restored}`)!.reserved, 0);
    assert.throws(() => store.reserveRequest(owner, "original", "another", [{ id: `work-${restored}`, ceiling: 1 }]), { code: "BUDGET_DENIED" });
  });
});

test("[S EVD-013 T30] malformed persisted scope references or a missing known branch marker never create a fresh budget scope", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  for (const value of [null, {}, { scopeId: "" }, { scopeId: false }, { scopeId: [] }]) {
    store.put("session-scopes", "resume", value);
    for (const id of ["EVD-013", "T30"]) evidence(id, () => {
      assert.throws(() => resolveWorkScope(store, { id: "resume", file: null }), { code: "WORK_SCOPE_REFERENCE_INVALID" });
      assert.equal(store.db.prepare("SELECT count(*) n FROM owners").get()!.n, 0); assert.equal(store.db.prepare("SELECT count(*) n FROM buckets").get()!.n, 0);
    });
  }
  assert.throws(() => resolveWorkScope(store, { id: "branch", file: null, branchScopeExpected: true }), { code: "WORK_SCOPE_REFERENCE_INVALID" });
  assert.throws(() => resolveWorkScope(store, { id: "memory-fork", file: null, forkExpected: true }), { code: "FORK_SCOPE_UNAVAILABLE" });
  store.put("session-scopes", "missing-owner", { scopeId: "lost-ledger" });
  assert.throws(() => resolveWorkScope(store, { id: "missing-owner", file: null }), { code: "SCOPE_LEDGER_UNAVAILABLE" });
  store.db.prepare("UPDATE records SET value=? WHERE namespace='session-scopes' AND id='resume'").run("{");
  assert.throws(() => resolveWorkScope(store, { id: "resume", file: null }), { code: "WORK_SCOPE_REFERENCE_INVALID" });
});

test("[S T30] trusted fork origin and header references must agree before selecting any budget", t => {
  const root = isolatedDirectory(t), store = new Store(join(root, "state")); t.after(() => store.close());
  const parent = join(root, "parent.jsonl"), foreign = join(root, "foreign.jsonl");
  store.claimOwner("scope-a", "owner-a"); store.claimOwner("scope-b", "owner-b");
  rememberWorkScope(store, "a", parent, "scope-a"); rememberWorkScope(store, "b", foreign, "scope-b");
  assert.equal(resolveWorkScope(store, { id: "fork", file: null, forkExpected: true, originParentFile: parent }), "scope-a");
  assert.throws(() => resolveWorkScope(store, { id: "fork", file: null, forkExpected: true, originParentFile: parent, parentFile: foreign }), { code: "WORK_SCOPE_IDENTITY_CONFLICT" });
  assert.equal(store.db.prepare("SELECT count(*) n FROM owners").get()!.n, 2);
});
