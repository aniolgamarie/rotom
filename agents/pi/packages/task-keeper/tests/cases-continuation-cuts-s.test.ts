import { test, assert, matrixCase } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

for (const cut of ["C0", "C1", "C2", "C3", "C4", "C5"] as const)
test(`[S ${["C2", "C3"].includes(cut) ? "T40" : ""}] continuation journal interruption at ${cut} preserves the original action identity`, async t =>
matrixCase("crash-cuts", `continue.${cut}`, async () => {
  const store = new Store(isolatedDirectory(t)), observer = new Store(store.root), clock = new FakeClock();
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "original-leaf", provider: "fixture-provider", model: "fixture-model",
    idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const actions: Array<{ id: string; leafId: string }> = [], notifications: string[] = [];
  const original = { prepare: store.prepare.bind(store), markSent: store.markSent.bind(store), acknowledge: store.acknowledge.bind(store), settle: store.settle.bind(store) };
  // These are declared interruptions at production method boundaries. No OS crash or
  // real receiver is claimed at S; A/P/E must exercise the native call separately.
  if (cut === "C0") store.prepare = (owner, id, kind, payload, demands, guard) =>
    original.prepare(owner, id, kind, payload, demands, () => { guard?.(); throw new Error("cut-before-commit"); });
  if (cut === "C1") store.markSent = () => { throw new Error("cut-before-dispatch"); };
  if (cut === "C3") store.acknowledge = () => { throw new Error("cut-before-ack-commit"); };
  const controller = new RecoveryController(store, configured(), { snapshot: () => ({ ...snapshot }), abort() {}, continue: async intent => {
    actions.push({ id: intent.id, leafId: intent.leafId });
    if (cut === "C2") throw new Error("cut-after-effect-before-ack");
    return { nativeId: "same-native-action" };
  } }, clock, () => 0, record => {
    if (cut === "C5" && record.status === "DONE") throw new Error("notification-lost-after-commit");
    notifications.push(record.status);
  });
  t.after(() => { Object.assign(store, original); controller.dispose(); observer.close(); store.close(); });
  controller.settled({ status: 429, message: "original quota", stream: "error" });
  const waiting = controller.state(); clock.advance(100); await flush();
  const interrupted = controller.state(); const id = interrupted.intentId;
  if (cut === "C0") {
    assert.equal(actions.length, 0); assert.equal(id, null); assert.equal(observer.claims().length, 0);
    assert.equal(observer.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
    store.prepare = original.prepare; controller.resume(); clock.advance(1); await flush();
    assert.equal(actions.length, 1); assert.equal(controller.state().attempts, 1);
    snapshot.leafId = "completed"; controller.settled(null);
  } else if (cut === "C1") {
    assert.equal(actions.length, 0); assert.ok(id); assert.equal(observer.intent(id)!.status, "unknown");
    assert.equal(observer.intent(id)!.nativeId, null); assert.equal(observer.claims().length, 1);
    assert.throws(() => controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
    clock.advance(10000); await controller.tick(); assert.equal(actions.length, 0);
    assert.equal(observer.intent(id)!.status, "unknown");
  } else {
    assert.ok(id); assert.deepEqual(actions, [{ id, leafId: "original-leaf" }]);
    if (cut === "C2" || cut === "C3") {
      assert.equal(observer.intent(id)!.status, "unknown"); assert.equal(observer.intent(id)!.nativeId, null);
      assert.equal(observer.claims().length, 1); assert.throws(() => controller.resume(), { code: "INTENT_RECONCILIATION_REQUIRED" });
      await controller.tick(); assert.equal(actions.length, 1);
      store.acknowledge = original.acknowledge; store.acknowledge(id, "same-native-action");
      assert.equal(observer.intent(id)!.nativeId, "same-native-action");
    }
    snapshot.leafId = "completed";
    if (cut === "C4") {
      store.settle = () => { throw new Error("cut-before-terminal-commit"); };
      assert.throws(() => controller.settled(null), /cut-before-terminal-commit/);
      assert.equal(observer.intent(id)!.status, "acked"); assert.equal(observer.claims().length, 1);
      store.settle = original.settle;
    }
    controller.settled(null); controller.settled(null); clock.advance(10000); await controller.tick();
    assert.equal(observer.intent(id)!.status, "settled"); assert.equal(observer.intent(id)!.nativeId, "same-native-action");
    assert.equal(observer.claims().length, 0); assert.equal(actions.length, 1);
    assert.equal(controller.state().status, "DONE"); assert.equal(controller.state().attempts, 1);
    assert.equal(observer.get<{status:string}>("recovery", waiting.scopeId)!.status, "DONE");
    if (cut === "C5") assert.equal(notifications.includes("DONE"), false);
  }
  assert.equal(controller.state().incidentId, waiting.incidentId);
  assert.equal(observer.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0); // Non-protected P1, no fabricated request charges.
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const root = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "continuation-state-cuts"); mkdirSync(root, { recursive: true });
    writeFileSync(join(root, `${cut}.json`), JSON.stringify({ kind: "state-simulation", cut, waiting, interrupted, final: controller.state(), actions, notifications,
      intents: observer.db.prepare("SELECT * FROM intents").all(), claims: observer.claims() }, null, 2));
  }
}));
