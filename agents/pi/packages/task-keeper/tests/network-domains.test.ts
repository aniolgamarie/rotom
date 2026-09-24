import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveAdapter, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { failureDomain, recordIncident, routeNotBefore, routeIncidents, closeRouteIncidents, recoveryResources, ensureExecutionTransportLease, settleExecutionTransportLeases } from "../src/reliability/incidents.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";
const overload = { status: 503, message: "temporary network overload", stream: "error" as const };
const quota = { status: 429, message: "quota", stream: "error" as const };
function session(t: TestContext, root: string, sessionId: string, pool: string, transport: string) {
  const config = configured(); config.quotaGroups[pool] = config.quotaGroups.pool;
  config.routes.primary.quotaGroup = pool; config.routes.primary.transportDomain = transport;
  const store = new Store(root), clock = new FakeClock();
  const snapshot: InteractiveSnapshot = { sessionId, leafId: "leaf-1", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, certified: true, terminationKnown: true, blockedReasons: [] };
  let sends = 0;
  const adapter: InteractiveAdapter = { snapshot: () => ({ ...snapshot }), continue: async () => ({ nativeId: `request-${sessionId}-${++sends}` }), abort() {} };
  const controller = new RecoveryController(store, config, adapter, clock, () => 0);
  t.after(() => { controller.dispose(); store.close(); });
  return { controller, store, config, clock, snapshot, sends: () => sends };
}

test("[U] failure category selects a transport domain independently of the quota pool name", () => {
  const route = configured().routes.primary;
  assert.deepEqual(failureDomain(route, { category: "network_overload", retryAt: null, code: "503", message: "network" }), { kind: "transport", id: route.transportDomain });
  for (const category of ["frequency_limit", "resource_pressure", "window_quota"] as const)
    assert.deepEqual(failureDomain(route, { category, retryAt: null, code: "429", message: "quota" }), { kind: "quota", id: route.quotaGroup });
});

test("[S] network waiting does not write a quota incident or block an independent transport domain", async t => {
  const root = isolatedDirectory(t), a = session(t, root, "a", "pool", "network-a"), b = session(t, root, "b", "pool", "network-b");
  a.controller.settled(overload);
  assert.equal(a.store.list("incidents").length, 0); assert.equal(a.store.list("transport-incidents").length, 1);
  assert.deepEqual(a.controller.state().incidentDomain, { kind: "transport", id: "network-a" });
  assert.equal(routeNotBefore(b.store, b.config.routes.primary), 0);
  assert.equal(routeNotBefore(a.store, a.config.routes.primary), 0);
  assert.equal(a.controller.state().localRetryAt,a.clock.now()+100);
  assert.equal(a.controller.state().networkAttempts, 1);
  a.clock.advance(100); await flush(); a.snapshot.leafId = "leaf-2"; a.controller.settled(null);
  assert.equal(a.controller.state().status, "DONE"); assert.equal(a.store.list("incidents").length, 0);
  assert.equal(a.store.get<{ status: string }>("transport-incidents", "network-a")?.status, "CLOSED");
});

test("[S] different quota pools share one recovery permit when their transport domain is failing", async t => {
  const root = isolatedDirectory(t), a = session(t, root, "a", "pool-a", "network"), b = session(t, root, "b", "pool-b", "network");
  a.controller.settled(overload); b.controller.settled(overload);
  assert.equal(a.controller.state().incidentId, b.controller.state().incidentId); assert.equal(a.store.list("incidents").length, 0);
  a.clock.advance(100); b.clock.advance(100); await flush(); assert.equal(a.sends() + b.sends(), 1);
  assert.equal(a.store.claims().length, 2); // quota + transport; no partial claim for the losing pool.
  a.snapshot.leafId = "leaf-complete"; a.controller.settled(null);
  b.clock.advance(100); await flush(); assert.equal(b.sends(), 1); assert.equal(a.sends(), 1);
});

test("[S] quota failures in independent pools do not create a transport outage or serialize those pools", async t => {
  const root = isolatedDirectory(t), a = session(t, root, "a", "pool-a", "network"), b = session(t, root, "b", "pool-b", "network");
  a.controller.settled(quota); b.controller.settled(quota);
  assert.notEqual(a.controller.state().incidentId, b.controller.state().incidentId);
  assert.equal(a.store.list("transport-incidents").length, 0);
  a.clock.advance(100); b.clock.advance(100); await flush(); assert.equal(a.sends(), 1); assert.equal(b.sends(), 1);
});

test("[S] an unknown transport recovery keeps its permit and counters through pause and recreation", async t => {
  const root = isolatedDirectory(t), a = session(t, root, "a", "pool-a", "network"), b = session(t, root, "b", "pool-b", "network");
  a.controller.settled(overload); b.controller.settled(overload); a.clock.advance(100); await flush();
  a.controller.stop(); const before = a.controller.state(); a.controller.dispose();
  const replacement = new RecoveryController(a.store, a.config, { snapshot: () => ({ ...a.snapshot }), continue: async () => ({ nativeId: "unexpected" }), abort() {} }, a.clock, () => 0);
  try {
    assert.equal(replacement.state().incidentId, before.incidentId); assert.equal(replacement.state().networkAttempts, before.networkAttempts);
    assert.deepEqual(replacement.state().incidentDomain, before.incidentDomain); assert.throws(() => replacement.resume());
    b.clock.advance(1000); await flush(); assert.equal(b.sends(), 0); assert.equal(a.store.claims().length, 2);
  } finally { replacement.dispose(); }
});

test("[S] equal domain names remain separate and the later quota/network deadline governs admission", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner"), config = configured();
  const route = { ...config.routes.primary, transportDomain: "pool" };
  const q = { category: "frequency_limit" as const, retryAt: 1000, code: "429", message: "quota" };
  const n = { category: "network_overload" as const, retryAt: 2000, code: "503", message: "network" };
  const quotaIncident = recordIncident(store, owner, config, "pool", q, 0, 0, failureDomain(route, q));
  const networkIncident = recordIncident(store, owner, config, "pool", n, 0, 0, failureDomain(route, n));
  assert.notEqual(quotaIncident.id, networkIncident.id); assert.equal(routeNotBefore(store, route), 2000);
  assert.equal(routeIncidents(store, route).length, 2); assert.equal(recoveryResources(store, route).length, 2);
  closeRouteIncidents(store, route, quotaIncident.id);
  assert.equal(store.get<{ status: string }>("incidents", "pool")?.status, "OPEN");
  assert.equal(store.get<{ status: string }>("transport-incidents", "pool")?.status, "CLOSED");
  assert.equal(routeNotBefore(store, route), 1000);
});


test("[S] a child started before a network outage acquires one domain lease and cannot duplicate it", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const first = store.claimOwner("scope-a", "a"), second = store.claimOwner("scope-b", "b"), config = configured(), route = config.routes.primary;
  assert.equal(ensureExecutionTransportLease(store, first, "child-a", "job-a", null, route), null);
  const failure = { category: "network_overload" as const, retryAt: 100, code: "503", message: "network" };
  recordIncident(store, first, config, route.quotaGroup, failure, 0, 0, failureDomain(route, failure));
  const lease = ensureExecutionTransportLease(store, first, "child-a", "job-a", null, route);
  assert.ok(lease); assert.equal(ensureExecutionTransportLease(store, first, "child-a", "job-a", null, route), lease);
  assert.equal(store.claims().length, 1); assert.equal(store.get<string[]>("execution-domain-leases", "child-a")?.length, 1);
  assert.throws(() => ensureExecutionTransportLease(store, second, "child-b", "job-b", null, route), { code: "SHARED_DOMAIN_BUSY" });
  assert.equal(store.get("execution-domain-leases", "child-b"), null);
  settleExecutionTransportLeases(store, "child-a");
  assert.ok(ensureExecutionTransportLease(store, second, "child-b", "job-b", null, route));
  assert.equal(store.claims().length, 1);
});

test("[S] a parent-held domain permit is inherited only by its current owned child scope", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const owner = store.claimOwner("scope", "owner"), other = store.claimOwner("other", "other-owner"), config = configured(), route = config.routes.primary;
  const failure = { category: "network_overload" as const, retryAt: 100, code: "503", message: "network" };
  recordIncident(store, owner, config, route.quotaGroup, failure, 0, 0, failureDomain(route, failure));
  store.prepare(owner, "parent-intent", "model", {}, recoveryResources(store, route));
  assert.equal(ensureExecutionTransportLease(store, owner, "child", "job", "parent-intent", route), null);
  assert.equal(store.claims().length, 2);
  assert.throws(() => ensureExecutionTransportLease(store, other, "foreign-child", "foreign-job", "parent-intent", route), { code: "SHARED_DOMAIN_BUSY" });
});
