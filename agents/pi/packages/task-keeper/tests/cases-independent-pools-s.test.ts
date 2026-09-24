import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { parseConfig } from "../src/config.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";

test("[S REC-022] a long quota wait in one pool leaves another pool runnable and separately cancellable", async t => {
  const root = isolatedDirectory(t), store = new Store(root), peer = new Store(root), clock = new FakeClock(), actions: string[] = [];
  const setup = (id: string, database: Store) => {
    const config = configured(); config.routes.primary.provider = `provider-${id}`; config.routes.primary.model = `model-${id}`;
    config.routes.primary.accountBinding = `provider:provider-${id}`; config.routes.primary.quotaGroup = `pool-${id}`;
    config.quotaGroups[`pool-${id}`] = structuredClone(config.quotaGroups.pool);
    const snapshot: InteractiveSnapshot = { sessionId: `session-${id}`, leafId: "leaf", provider: `provider-${id}`, model: `model-${id}`, idle: true,
      pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
    const controller = new RecoveryController(database, parseConfig(config), { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => {
      actions.push(id); snapshot.idle = false; return { nativeId: `native-${id}` };
    } }, clock, () => 0);
    return { controller, snapshot };
  };
  const a = setup("a", store), b = setup("b", peer); t.after(() => { a.controller.dispose(); b.controller.dispose(); peer.close(); store.close(); });
  a.controller.settled({ status: 429, message: "long wait", headers: { "retry-after": "100" }, stream: "error" });
  b.controller.settled({ status: 429, message: "short wait", stream: "error" }); const original = a.controller.state();
  clock.advance(100); await flush();
  assert.deepEqual(actions, ["b"]); assert.equal(a.controller.state().status, "WAITING_QUOTA"); assert.equal(a.controller.state().notBefore, original.notBefore);
  assert.equal(a.controller.state().intentId, null); assert.equal(b.controller.state().status, "RUNNING");
  assert.notEqual(a.controller.state().scopeId, b.controller.state().scopeId); assert.notEqual(a.controller.state().incidentId, b.controller.state().incidentId);
  assert.equal(store.get<{status:string}>("incidents", "pool-a")!.status, "OPEN");
  a.controller.pause(); assert.equal(b.controller.state().status, "RUNNING"); assert.ok(peer.owner(b.controller.scopeId)!.active);
  b.snapshot.idle = true; b.snapshot.leafId = "completed"; b.controller.settled(null);
  assert.equal(b.controller.state().status, "DONE"); assert.equal(store.get<{status:string}>("incidents", "pool-b")!.status, "CLOSED");
  assert.equal(store.get<{status:string}>("incidents", "pool-a")!.status, "OPEN"); assert.equal(a.controller.state().status, "PAUSED");
  assert.deepEqual(a.controller.state().history, original.history); assert.equal(a.controller.state().attempts, 0); assert.equal(b.controller.state().attempts, 1);
});
