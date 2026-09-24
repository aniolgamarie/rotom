import { test, assert } from "./recorded-test.ts";
import { resourceClaimPlan } from "../src/contracts/resources.ts";

test("[U TK07] the last host slot admits one unit and rejects every later claim until occupancy is released", () => {
  for (const capacity of [0, 1, 2, 32]) {
    const demands = [{ id: "host-child", capacity, units: 1 }];
    for (let used = 0; used <= capacity + 1; used++) {
      const observations = [{ id: "host-child", capacity, used }], before = structuredClone(observations);
      if (used < capacity) assert.deepEqual(resourceClaimPlan(demands, observations), demands);
      else assert.throws(() => resourceClaimPlan(demands, observations), { code: "RESOURCE_DENIED" });
      assert.deepEqual(observations, before);
    }
  }
});

test("[U TK06] a frozen canonical source excludes a second writer independently of the host slot", () => {
  const demands = [{ id: "source-canonical", capacity: 1, units: 1 }, { id: "host-child", capacity: 4, units: 1 }];
  const observations = [{ id: "source-canonical", capacity: 1, used: 1 }, { id: "host-child", capacity: 4, used: 0 }];
  const before = structuredClone(observations);
  assert.throws(() => resourceClaimPlan(demands, observations), { code: "RESOURCE_DENIED", message: "source-canonical" });
  assert.deepEqual(observations, before);
  assert.deepEqual(resourceClaimPlan(demands, [{ ...observations[0], used: 0 }, observations[1]]), demands);
});

test("[U TK04] reverse resource order cannot yield a partial plan when any required resource is unavailable", () => {
  const demands = [{ id: "a", capacity: 1, units: 1 }, { id: "b", capacity: 1, units: 1 }];
  for (const order of [demands, [...demands].reverse()]) for (const busy of ["a", "b"]) {
    const observations = [{ id: "a", capacity: 1, used: busy === "a" ? 1 : 0 }, { id: "b", capacity: 1, used: busy === "b" ? 1 : 0 }];
    const before = structuredClone({ order, observations }); let plan: unknown = null;
    assert.throws(() => { plan = resourceClaimPlan(order, observations); }, { code: "RESOURCE_DENIED", message: busy });
    assert.equal(plan, null); assert.deepEqual({ order, observations }, before);
    const free = observations.map(observation => ({ ...observation, used: 0 }));
    assert.deepEqual(resourceClaimPlan(order, free), order); assert.deepEqual(observations, before.observations);
  }
});

test("[U] resource claim plans preserve stricter capacities, safe arithmetic and explicit observation completeness", () => {
  const demand = { id: "source", capacity: 12, units: 1 };
  assert.deepEqual(resourceClaimPlan([demand], [{ id: "source", capacity: 2, used: 1 }]), [{ ...demand, capacity: 2 }]);
  assert.deepEqual(resourceClaimPlan([{ ...demand, capacity: 2 }], [{ id: "source", capacity: 12, used: 1 }]), [{ ...demand, capacity: 2 }]);
  assert.throws(() => resourceClaimPlan([demand], [{ id: "source", capacity: 2, used: 2 }]), { code: "RESOURCE_DENIED" });
  assert.throws(() => resourceClaimPlan([{ ...demand, capacity: 0 }], [{ id: "source", capacity: null, used: 0 }]), { code: "RESOURCE_DENIED" });
  assert.deepEqual(resourceClaimPlan([demand], [{ id: "source", capacity: null, used: 0 }]), [demand]);
  const max = Number.MAX_SAFE_INTEGER;
  assert.deepEqual(resourceClaimPlan([{ ...demand, capacity: max }], [{ id: "source", capacity: max, used: max - 1 }]), [{ ...demand, capacity: max }]);
  assert.throws(() => resourceClaimPlan([{ ...demand, capacity: max, units: 2 }], [{ id: "source", capacity: max, used: max - 1 }]), { code: "RESOURCE_DENIED" });
  assert.throws(() => resourceClaimPlan([demand], []), { code: "RESOURCE_OBSERVATION_MISSING" });
  assert.throws(() => resourceClaimPlan([demand, demand], []), { code: "DUPLICATE_RESOURCE" });
  assert.throws(() => resourceClaimPlan([demand], [{ id: "source", capacity: 12, used: 0 }, { id: "source", capacity: 12, used: 0 }]), { code: "DUPLICATE_RESOURCE_OBSERVATION" });
  for (const used of [-1, 0.5, NaN, Infinity, max + 1]) assert.throws(() => resourceClaimPlan([demand], [{ id: "source", capacity: 12, used }]), { code: "INVALID_INTEGER" });
});

import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { workspaceResource } from "../src/workspace/worktree.ts";

test("[U TK05] resource admission uses resolved workspace identity across job aliases", t => {
  const resolution: Record<string, string> = { "/job-a/alias": "/shared/source", "/job-b/alias": "/shared/source", "/independent": "/other/source" };
  // U supplies the filesystem boundary's canonicalization results; actual
  // symlinks and cross-process exclusion are checked by the existing S/P/E cases.
  t.mock.method(fs, "realpathSync", ((path: unknown) => {
    if (typeof path !== "string" || !resolution[path]) throw new Error("Unexpected canonicalization input");
    return resolution[path];
  }) as typeof fs.realpathSync);
  syncBuiltinESMExports();
  try {
    const first = workspaceResource("/job-a/alias"), second = workspaceResource("/job-b/alias"), independent = workspaceResource("/independent");
    assert.equal(first, second); assert.notEqual(first, independent);
    assert.deepEqual(resourceClaimPlan([{id:first,capacity:1,units:1}], [{id:first,capacity:1,used:0}]), [{id:first,capacity:1,units:1}]);
    assert.throws(() => resourceClaimPlan([{id:second,capacity:1,units:1}], [{id:first,capacity:1,used:1}]), {code:"RESOURCE_DENIED"});
    assert.deepEqual(resourceClaimPlan([{id:independent,capacity:1,units:1}], [{id:independent,capacity:1,used:0}]), [{id:independent,capacity:1,units:1}]);
  } finally { t.mock.restoreAll(); syncBuiltinESMExports(); }
});
