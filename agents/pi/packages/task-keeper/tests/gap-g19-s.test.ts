import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { isolatedDirectory } from "./helpers.ts";
import type { TaskSpec } from "../src/contracts/task.ts";

test("[S TK13] a higher priority job blocked on its runtime quota pool cannot starve an independent ready job", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const owner = store.claimOwner("scope", "owner"), peer = store.claimOwner("peer", "peer-owner"), scheduler = new Scheduler(store, owner);
  store.prepare(peer, "pool-a-held", "permit", {}, [{ id: "quota-a", capacity: 1, units: 1 }]);
  const spec = (id: string): TaskSpec => ({ id, workScope: "scope", version: 1, objective: "bounded", workflow: "inspect", required: ["read"], optional: [], allowPartial: false,
    snapshot: "snapshot", policyDigest: "policy", maxSteps: 16, maxSemanticAttempts: 3 });
  const steps = [{ id: "read", kind: "read" as const, role: "scout", dependencies: [], allowedSkippedDependencies: [], optional: false, resources: [] }];
  scheduler.submit(spec("a"), steps, 10, 0); scheduler.submit(spec("b"), steps, 0, 0);
  const demands = (spec: TaskSpec) => [{ id: `quota-${spec.id}`, capacity: 1, units: 1 }];
  assert.equal(scheduler.next(1, demands)?.jobId, "b");
  const run = scheduler.dispatch("b", "read", "snapshot", demands(spec("b")));
  assert.equal(store.intent(run.id)?.status, "prepared"); assert.equal(scheduler.next(2, demands), null);
  assert.equal(store.claims().filter(claim => claim.resource_id === "quota-a").length, 1);
  scheduler.finish("b", "read", { terminated: true, passed: false, artifactId: null, notSent: true }, 3);
  assert.equal(scheduler.next(4, demands), null);
  store.settle("pool-a-held", "not_sent"); assert.equal(scheduler.next(5, demands)?.jobId, "a");
});
