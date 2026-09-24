import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";
import { resolveWorkScope, rememberWorkScope } from "../src/orchestration/work-scope.ts";

test("[S SCH-001 SCH-002 T30] a fork before the branch marker still inherits its parent's budget scope", (t) => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const parent = { id: "parent", file: "/fixture/parent.jsonl" }, scopeId = resolveWorkScope(store, parent);
  const owner = store.claimOwner(scopeId, "owner"); rememberWorkScope(store, parent.id, parent.file, scopeId);
  store.prepare(owner, "request", "model", {}); store.reserveRequest(owner, "request", "request", [{ id: `work-${scopeId}`, ceiling: 12 }]); store.settleRequest("request", "sent");
  const fork = resolveWorkScope(store, { id: "fork", file: "/fixture/fork.jsonl", parentFile: parent.file });
  assert.equal(fork, scopeId); assert.equal(store.bucket(`work-${fork}`)?.used, 1);
  assert.throws(() => resolveWorkScope(store, { id: "fork", file: null, parentFile: parent.file, branchScope: "invented" }));
  assert.throws(() => resolveWorkScope(store, { id: "unknown-fork", file: null, parentFile: "/unmapped/parent.jsonl" }));
});
