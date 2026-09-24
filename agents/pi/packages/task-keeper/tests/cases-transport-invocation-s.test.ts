import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { admitTransportRequest } from "../src/reliability/incidents.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, FakeClock } from "./helpers.ts";

test("[S] final dispatch admission commits permits and authority but is never a send receipt", t => {
  const store = new Store(isolatedDirectory(t)), reader = new Store(store.root); t.after(() => { reader.close(); store.close(); });
  const owner = store.claimOwner("scope", "owner"), route = configured().routes.primary;
  store.put("transport-incidents", route.transportDomain, { id: "outage", status: "OPEN", failures: 1, notBefore: 0, domain: { kind: "transport", id: route.transportDomain } });
  store.prepare(owner, "execution", "child-lease", {}); store.reserveRequest(owner, "execution", "request", [{ id: "budget", ceiling: 1 }]);
  admitTransportRequest(store, owner, "descriptor", "job", "execution", route, "request", () => {
    assert.equal(reader.get("request-admissions", "request"), null); assert.equal(reader.claims().length, 0);
  });
  const admission = reader.get<{ provesSend: boolean; ownerEpoch: number }>("request-admissions", "request")!;
  assert.equal(admission.provesSend, false); assert.equal(admission.ownerEpoch, owner.epoch); assert.equal(reader.claims().length, 1);
  assert.equal(reader.request("request")!.state, "reserved"); assert.equal(reader.bucket("budget")!.used, 0); assert.equal(reader.bucket("budget")!.reserved, 1);
  assert.throws(() => admitTransportRequest(store, owner, "descriptor", "job", "execution", route, "request", () => {}), { code: "DUPLICATE_REQUEST_ADMISSION" });
  assert.throws(() => admitTransportRequest(store, owner, "descriptor", "job", "execution", route, "async", async () => {}), { code: "ASYNC_ADMISSION_CHECK" });
  assert.throws(() => admitTransportRequest(store, owner, "descriptor", "job", "execution", route, "promise", () => Promise.resolve()), { code: "ASYNC_ADMISSION_CHECK" });
  assert.equal(reader.list("request-admissions").length, 1); assert.equal(reader.claims().length, 1);
});

for (const canary of [false, true]) test(`[S] ${canary ? "canary" : "main"} recovery commits final authority before invoking the caller outside the transaction`, async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), config = configured(); config.recovery.lightCanaryEnabled = canary;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  let invoked = 0;
  const invoke = () => { store.transaction(() => { assert.ok(store.get("request-admissions", "actual-request")); }); invoked++; };
  const controller = new RecoveryController(store, config, { snapshot: () => ({ ...snapshot }), abort() {}, continue: async () => ({ nativeId: "native" }),
    canary: async (_signal, guard) => { guard(); guard(invoke, "actual-request"); return { nativeId: "canary", failure: null, terminated: true }; } }, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); }); controller.settled({ status: 429, message: "quota", stream: "error" }); clock.advance(100); await flush();
  if (!canary) { const state = controller.state(); controller.requestGuard(state.intentId!, state.ownerEpoch)(invoke, "actual-request"); }
  assert.equal(invoked, 1); assert.equal(store.list("request-admissions").length, 1);
  assert.equal(store.get<{ provesSend: boolean }>("request-admissions", "actual-request")!.provesSend, false);
});
