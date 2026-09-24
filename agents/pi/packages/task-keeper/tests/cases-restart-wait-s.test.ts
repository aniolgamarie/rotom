import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";
import { configured } from "./fixtures/config.ts";

for (const variant of ["confirmed-stopped", "unknown", "still-running", "changed-policy", "changed-leaf", "unresolved-intent"] as const)
test(`[S TK11] persistent quota wait restart ${variant} retains deadline, cooldown and original authority limits`, async t => {
  const store = new Store(isolatedDirectory(t)), reader = new Store(store.root), config = configured(), clock = new FakeClock(); config.recovery.maxWaitMs = 5000;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const oldIdentity = { pid: 10, bootId: "fixture-boot", startTicks: "1", pidNamespace: "fixture-ns" };
  let oldActions = 0, newActions = 0;
  const first = new RecoveryController(store, config, { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => { oldActions++; return { nativeId: "old" }; } },
    clock, () => 0, () => {}, { current: () => oldIdentity, stopped: () => null });
  let restored: RecoveryController | undefined;
  t.after(() => { first.dispose(); restored?.dispose(); reader.close(); store.close(); });
  first.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(variant === "unresolved-intent" ? 100 : 50); await flush();
  const before = first.state(), owner = store.owner(before.scopeId)!, prior = reader.get("recovery", before.scopeId), nextConfig = structuredClone(config);
  if (variant === "changed-policy") nextConfig.recovery.requestTimeoutMs++;
  if (variant === "changed-leaf") snapshot.leafId = "different-leaf";
  const reopen = () => new RecoveryController(reader, nextConfig, { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => { newActions++; return { nativeId: "new" }; } },
    clock, () => 0, () => {}, { current: () => ({ ...oldIdentity, pid: 11, startTicks: "2" }),
      stopped: identity => { assert.deepEqual(identity, oldIdentity); return variant === "unknown" ? null : variant === "still-running" ? false : true; } });
  if (variant === "unknown" || variant === "still-running") {
    assert.throws(reopen, { code: "OWNER_CONFLICT" }); assert.deepEqual(store.owner(before.scopeId), owner);
    assert.deepEqual(reader.get("recovery", before.scopeId), prior); assert.equal(newActions, 0);
    return;
  }
  restored = reopen(); const after = restored.state();
  if (variant !== "confirmed-stopped") {
    assert.equal(after.status, "PAUSED"); assert.ok(after.ownerEpoch > before.ownerEpoch);
    assert.equal(after.deadlineAt, before.deadlineAt); assert.equal(after.notBefore, before.notBefore);
    assert.equal(after.intentId, before.intentId); assert.deepEqual(after.history, before.history);
    clock.advance(10000); await flush(); assert.equal(newActions, 0);
    if (variant === "unresolved-intent") {
      assert.ok(before.intentId); assert.ok(store.claims().length > 0); assert.equal(oldActions, 1);
      assert.throws(() => restored!.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
    }
    return;
  }
  assert.equal(after.status, "WAITING_QUOTA"); assert.equal(after.reason, "restored_wait_reconciled");
  assert.equal(after.notBefore, before.notBefore); assert.equal(after.deadlineAt, before.deadlineAt); assert.equal(after.incidentId, before.incidentId);
  assert.deepEqual(after.history, before.history); assert.equal(after.attempts, 0); assert.ok(after.ownerEpoch > before.ownerEpoch);
  clock.advance(49); await flush(); assert.equal(oldActions, 0); assert.equal(newActions, 0);
  clock.advance(1); await flush(); assert.equal(oldActions, 0); assert.equal(newActions, 1);
  assert.equal(restored.state().attempts, 1); assert.equal(restored.state().deadlineAt, before.deadlineAt);
});
