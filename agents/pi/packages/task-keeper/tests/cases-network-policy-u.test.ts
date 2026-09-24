import { test, assert, evidence } from "./recorded-test.ts";
import { classify, isTemporaryQuota } from "../src/reliability/classifier.ts";
import { chooseRoute, type RouteCandidate } from "../src/orchestration/policy.ts";

test("[U RTB-006 T34] failed proxy policy stays a network failure and cannot silently authorize direct transport", () => {
  const proxy: RouteCandidate = { id: "bound-proxy", preference: 0, approved: true, accountResolved: true, toolsSatisfied: true,
    contextSatisfied: true, profileVerified: true, observationsVerified: true, resourcesAvailable: true, budgetAvailable: true, networkVerified: false, riskKnown: true };
  const direct = { ...proxy, id: "unapproved-direct", networkVerified: true, approved: false, preference: 1 };
  for (const id of ["RTB-006", "T34"]) evidence(id, () => {
    for (const message of ["SOCKS5 ECONNREFUSED", "HTTPS proxy Connection timed out", "EAI_AGAIN proxy hostname"]) {
      const failure = classify({ message, stream: "error" }, [], 1000);
      assert.equal(failure.category, "network_overload"); assert.equal(isTemporaryQuota(failure.category), false);
    }
    const denied = chooseRoute([proxy, direct]); assert.equal(denied.route, null);
    assert.deepEqual(denied.rejected.find(row => row.id === proxy.id)!.reasons, ["networkVerified"]);
    assert.deepEqual(denied.rejected.find(row => row.id === direct.id)!.reasons, ["approved"]);
    assert.equal(chooseRoute([{ ...proxy, networkVerified: true }, direct]).route, proxy.id);
    assert.equal(chooseRoute([proxy, { ...direct, approved: true }]).route, direct.id);
    assert.equal(direct.approved, false);
  });
});
