import { test, assert } from "./recorded-test.ts";
import { recordIncident, type Incident } from "../src/reliability/incidents.ts";
import { selectStage } from "../src/reliability/stages.ts";
import { configured } from "./fixtures/config.ts";
import type { Store } from "../src/store/database.ts";

test("[U REC-010] independent server, local and persisted floors determine exact admission boundaries", () => {
  const config = configured(), owner = { scopeId: "scope", token: "owner", epoch: 1 };
  for (const [server, previousFloor, expected] of [[1050, 0, 1100], [1150, 0, 1150], [1050, 1300, 1300]]) {
    const previous: Incident | null = previousFloor ? { id: "original", status: "OPEN", failures: 1, notBefore: previousFloor } : null;
    let stored: Incident | undefined;
    const store = { transaction: (fn: () => unknown) => fn(), assertOwner() {}, get: () => previous,
      put: (_namespace: string, _id: string, value: Incident) => { stored = value; } } as unknown as Store;
    const incident = recordIncident(store, owner, config, "pool", { category: "frequency_limit", retryAt: server, code: "429", message: "limit" }, 1000, 0);
    assert.equal(incident.notBefore, expected); assert.deepEqual(stored, incident);
    const chain = [{ id: "same-route", route: "primary", wait: { mode: "forever" as const } }];
    const input = { incidentId: incident.id, approved: ["primary"], safeBoundary: true, primaryRoute: "primary", primaryRecovered: false,
      backupExhausted: false, notBefore: { primary: incident.notBefore } };
    assert.equal(selectStage(chain, null, { ...input, now: expected - 1 }).route, null);
    assert.equal(selectStage(chain, null, { ...input, now: expected }).route, "primary");
    assert.equal(selectStage(chain, null, { ...input, now: expected + 1 }).route, "primary");
    assert.equal(selectStage(chain, null, { ...input, now: expected, safeBoundary: false }).route, null);
    assert.equal(selectStage(chain, null, { ...input, now: expected, approved: [] }).route, null);
  }
});
