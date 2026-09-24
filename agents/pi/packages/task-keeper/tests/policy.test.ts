import { test, assert, evidence } from "./recorded-test.ts";
import { chooseRoute, recipePolicy, quotaTelemetry, type RouteCandidate } from "../src/orchestration/policy.ts";
import { selectStage } from "../src/reliability/stages.ts";

test("[RTB-001 RTB-002 T27 T78] each independent eligibility failure beats route preference", () => {
  for (const id of ["T27", "T78"]) evidence(id, () => {
    const good: RouteCandidate = { id: "a", preference: 0, approved: true, accountResolved: true, toolsSatisfied: true, contextSatisfied: true,
      profileVerified: true, observationsVerified: true, resourcesAvailable: true, budgetAvailable: true, networkVerified: true, riskKnown: true };
    for (const field of Object.keys(good).filter((key) => !["id", "preference"].includes(key))) {
      const result = chooseRoute([{ ...good, [field]: false }, { ...good, id: "b", preference: 100 }]);
      assert.equal(result.route, "b"); assert.deepEqual(result.rejected[0].reasons, [field]);
    }
    assert.equal(chooseRoute([good, { ...good, id: "b" }]).route, "a");
  });
});

test("[RTB-015 RTB-016 RTB-017 RTB-018 RTB-019 T79 T80 T82 T85 T88] bounded recipes retain shared limits and skip unsupported findings", () => {
  for (const id of ["RTB-017", "T80", "T82", "T88"]) evidence(id, () => {
    const input = { enabled: ["direct", "critique"], qualityFailure: false, environmentFailure: false, upgradeEligible: true, criticEligible: true,
      upgradesUsed: 0, critiquesUsed: 0, semanticAttempts: 1, maxSemanticAttempts: 3, stepsUsed: 1, maxSteps: 16, remainingRequests: 4, requiredReserve: 2, finding: null };
    assert.equal(recipePolicy(input).action, "critic");
    assert.equal(recipePolicy({ ...input, remainingRequests: 2 }).action, "skip");
    assert.equal(recipePolicy({ ...input, environmentFailure: true, qualityFailure: true }).action, "block");
    assert.equal(recipePolicy({ ...input, qualityFailure: true }).action, "critic");
    assert.equal(recipePolicy({ ...input, qualityFailure: true, upgradesUsed: 1, critiquesUsed: 1 }).action, "direct");
    assert.equal(recipePolicy({ ...input, critiquesUsed: 1, finding: { actionable: true, evidenceVerified: false } }).action, "direct");
    assert.equal(recipePolicy({ ...input, semanticAttempts: 3, finding: { actionable: true, evidenceVerified: true } }).action, "block");
    assert.deepEqual(recipePolicy(input), recipePolicy(structuredClone(input)));
  });
});

test("[RTB-014 T32] stale/wrong-account quota telemetry stays unknown and never constitutes a reservation", () => {
  for (const id of ["T32"]) evidence(id, () => {
    const expected = { account: "a", bucket: "b", source: "s", now: 1000, freshnessMs: 10 };
    const observation = { account: "a", bucket: "b", source: "s", observedAt: 990, remaining: 5, resetAt: null };
    assert.equal(quotaTelemetry(observation, expected).status, "observed");
    for (const change of [{ account: "other" }, { bucket: "other" }, { source: "other" }, { observedAt: 989 }, { observedAt: 1001 }, { remaining: -1 }])
      assert.equal(quotaTelemetry({ ...observation, ...change }, expected).status, "unknown");
    assert.equal(quotaTelemetry(observation, expected).reservation, false);
  });
});

test("[RTB-003 RTB-004 RTB-005 RTB-010 T28 T30 T50] stage deadlines survive restart, backup exhaustion returns primary, active writers prevent switching", () => {
  for (const id of ["RTB-003", "RTB-004", "T30", "T50"]) evidence(id, () => {
    const chain = [{ id: "primary-short", route: "primary", wait: { mode: "bounded" as const, maxMs: 100 } },
      { id: "backup", route: "backup", wait: { mode: "bounded" as const, maxMs: 200 } }, { id: "primary-tail", route: "primary", wait: { mode: "forever" as const } }];
    const input = { now: 100, incidentId: "incident", approved: ["primary", "backup"], safeBoundary: true, primaryRoute: "primary", primaryRecovered: false, backupExhausted: false, notBefore: {} };
    const first = selectStage(chain, null, input);
    assert.equal(first.state?.deadline, 200);
    assert.equal(selectStage(chain, first.state, { ...input, now: 150 }).state?.deadline, 200);
    const backup = selectStage(chain, first.state, { ...input, now: 200 }); assert.equal(backup.route, "backup");
    assert.equal(selectStage(chain, backup.state, { ...input, now: 250, primaryRecovered: true, safeBoundary: false }).route, null);
    const exhausted = selectStage(chain, backup.state, { ...input, now: 250, backupExhausted: true, notBefore: { primary: 500 } });
    assert.equal(exhausted.state?.stageId, "primary-tail"); assert.equal(exhausted.route, null); assert.equal(exhausted.state?.incidentId, "incident");
    assert.equal(selectStage(chain, exhausted.state, { ...input, now: 500, backupExhausted: true }).route, "primary");
  });
});
