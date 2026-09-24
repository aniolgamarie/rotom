import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { classify } from "../src/reliability/classifier.ts";
import { closeRouteIncidents, recordIncident } from "../src/reliability/incidents.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

for (const sharedPool of [false, true])
test(`[S RTB-005] backup success with ${sharedPool ? "shared" : "separate"} quota grouping preserves original pressure and uncertain charges`, t => {
  const store = new Store(isolatedDirectory(t)), observer = new Store(store.root); t.after(() => { observer.close(); store.close(); });
  const owner = store.claimOwner("scope", "owner"), config = configured(), primary = config.routes.primary;
  const backup = { ...primary, model: "backup-model", quotaGroup: sharedPool ? "pool" : "backup-pool" };
  config.quotaGroups[backup.quotaGroup] = structuredClone(config.quotaGroups.pool);
  const original = recordIncident(store, owner, config, "pool", classify({ status: 429, message: "primary quota", headers: {"retry-after":"9"}, stream: "error" }, [], 1000), 1000, 0);
  if (!sharedPool) recordIncident(store, owner, config, "backup-pool", classify({ status: 429, message: "backup prior failure", stream: "error" }, [], 1000), 1000, 0);
  recordIncident(store, owner, config, "pool", classify({ status: 503, message: "prior overload", stream: "error" }, [], 1000), 1000, 0, { kind: "transport", id: primary.transportDomain });
  store.prepare(owner, "backup", "model", { originalIncidentId: original.id });
  for (const id of ["charged", "uncertain"]) store.reserveRequest(owner, "backup", id, [{ id: `incident-${original.id}`, ceiling: 4 }, { id: "work", ceiling: 12 }]);
  store.markSent(owner, "backup"); store.settleRequest("charged", "sent"); store.settleRequest("uncertain", "unknown"); store.settle("backup", "terminated");
  const incidentBudget = store.bucket(`incident-${original.id}`), workBudget = store.bucket("work");
  closeRouteIncidents(store, backup, original.id);
  assert.deepEqual(observer.get("incidents", "pool"), original); assert.equal(observer.get<{status:string}>("transport-incidents", primary.transportDomain)!.status, "CLOSED");
  if (!sharedPool) assert.equal(observer.get<{status:string}>("incidents", "backup-pool")!.status, "CLOSED");
  assert.deepEqual(observer.bucket(`incident-${original.id}`), incidentBudget); assert.deepEqual(observer.bucket("work"), workBudget);
  assert.equal(observer.request("charged")!.state, "sent"); assert.equal(observer.request("uncertain")!.state, "unknown");
  closeRouteIncidents(store, primary);
  assert.equal(observer.get<{status:string}>("incidents", "pool")!.status, "CLOSED");
  assert.deepEqual(observer.bucket(`incident-${original.id}`), incidentBudget); assert.deepEqual(observer.bucket("work"), workBudget);
  assert.equal(observer.bucket("work")!.used, 1); assert.equal(observer.bucket("work")!.reserved, 1);
});
