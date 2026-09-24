import { test, assert } from "./recorded-test.ts";
import { closeRouteIncidents } from "../src/reliability/incidents.ts";
import { configured } from "./fixtures/config.ts";
import type { Store } from "../src/store/database.ts";

test("[U RTB-005] backup success closes its own failure domains but preserves the original quota incident and accounting", () => {
  const config = configured(), primary = config.routes.primary, backup = { ...primary, quotaGroup: "backup-pool" };
  const records = new Map<string, unknown>([
    ["incidents:pool", { id: "primary-incident", status: "OPEN", notBefore: 10000, failures: 4 }],
    ["incidents:backup-pool", { id: "backup-incident", status: "OPEN", notBefore: 2000, failures: 1 }],
    [`transport-incidents:${primary.transportDomain}`, { id: "network-incident", status: "OPEN", notBefore: 1000, failures: 1 }],
    ["buckets:incident-primary-incident", { used: 3, reserved: 1, ceiling: 4 }],
  ]);
  const original = structuredClone(records.get("incidents:pool")), budget = structuredClone(records.get("buckets:incident-primary-incident"));
  const store = { claims:()=>[], intent:()=>null, get: (namespace: string, id: string) => records.get(`${namespace}:${id}`) ?? null,
    put: (namespace: string, id: string, value: unknown) => { assert.notEqual(namespace, "buckets"); records.set(`${namespace}:${id}`, value); } } as unknown as Store;
  closeRouteIncidents(store, backup, "primary-incident");
  assert.deepEqual(records.get("incidents:pool"), original);
  assert.equal((records.get("incidents:backup-pool") as {status:string}).status, "CLOSED");
  assert.equal((records.get(`transport-incidents:${primary.transportDomain}`) as {status:string}).status, "CLOSED");
  closeRouteIncidents(store, primary, "primary-incident"); assert.deepEqual(records.get("incidents:pool"), original);
  closeRouteIncidents(store, primary); assert.equal((records.get("incidents:pool") as {status:string}).status, "CLOSED");
  assert.deepEqual(records.get("buckets:incident-primary-incident"), budget);
});
