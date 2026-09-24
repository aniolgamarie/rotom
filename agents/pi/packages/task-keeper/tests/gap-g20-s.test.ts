import { test, assert } from "./recorded-test.ts";
import { chooseRoute, type RouteCandidate } from "../src/orchestration/policy.ts";
const good: RouteCandidate = { id: "cheap", preference: 0, approved: true, accountResolved: true, toolsSatisfied: true,
  contextSatisfied: true, profileVerified: true, observationsVerified: true, resourcesAvailable: true, budgetAvailable: true, networkVerified: true, riskKnown: true };
const hard = ["approved", "accountResolved", "toolsSatisfied", "contextSatisfied", "profileVerified", "observationsVerified", "resourcesAvailable", "budgetAvailable", "networkVerified", "riskKnown"] as const;
for (const id of ["RTB-001", "T27", "T78"]) test(`[U S ${id}] eligibility transitions retain every independent hard prerequisite before preference`, () => {
  const backup = { ...good, id: "backup", preference: 100 };
  const log: string[] = [];
  for (const key of hard) {
    for (const value of [false, undefined, null, 0, "true"]) {
      const candidate = { ...good, [key]: value } as unknown as RouteCandidate;
      if (value === undefined) delete (candidate as unknown as Record<string, unknown>)[key];
      const blocked = chooseRoute([candidate, backup]);
      assert.equal(blocked.route, "backup"); assert.deepEqual(blocked.rejected, [{ id: "cheap", reasons: [key] }]);
      assert.equal(chooseRoute([candidate]).route, null);
      log.push(`${key}:blocked`);
      const recovered = chooseRoute([good, backup]); assert.equal(recovered.route, "cheap"); log.push(`${key}:recovered`);
    }
  }
  assert.equal(log.length, hard.length * 10);
  assert.equal(chooseRoute([]).route, null);
  for (const order of [[good, { ...good, id: "z" }], [{ ...good, id: "z" }, good]]) assert.equal(chooseRoute(order).route, "cheap");
  assert.throws(() => chooseRoute([good, good]), /DUPLICATE_ROUTE_CANDIDATE/);
  assert.throws(() => chooseRoute([{ ...good, arbitraryScore: 1000 } as RouteCandidate]), /UNKNOWN_FIELD/);
  assert.throws(() => chooseRoute([{ ...good, preference: NaN }]));
});
