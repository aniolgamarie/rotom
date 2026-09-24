import { test, assert, evidence } from "./recorded-test.ts";
import { recipePolicy, type RecipeInput } from "../src/orchestration/policy.ts";
import { selectStage } from "../src/reliability/stages.ts";
const recipe = (): RecipeInput => ({ enabled: ["direct", "critique"], qualityFailure: false, environmentFailure: false,
  upgradeEligible: true, criticEligible: true, upgradesUsed: 0, critiquesUsed: 1, semanticAttempts: 1,
  maxSemanticAttempts: 3, stepsUsed: 4, maxSteps: 16, remainingRequests: 4, requiredReserve: 2, finding: null });

test("[U RTB-015 T80] critique revision and later same-model repair consume the same finite recipe allowance", () => {
  const state = recipe(); state.finding = { actionable: true, evidenceVerified: true };
  assert.equal(recipePolicy(state).action, "revise");
  state.semanticAttempts++; state.stepsUsed++; state.finding = null; state.qualityFailure = true;
  const repair = recipePolicy(state); assert.equal(repair.action, "direct");
  state.semanticAttempts++; state.stepsUsed++;
  for (const id of ["RTB-015", "T80"]) evidence(id, () => {
    assert.equal(state.semanticAttempts, 3); assert.equal(state.critiquesUsed, 1); assert.equal(state.upgradesUsed, 0);
    assert.equal(recipePolicy({ ...state, finding: { actionable: true, evidenceVerified: true } }).reason, "semantic_attempt_limit");
    assert.equal(recipePolicy({ ...state, finding: { actionable: true, evidenceVerified: true } }).reason, "semantic_attempt_limit");
    assert.equal(recipePolicy({ ...state, semanticAttempts: 2, stepsUsed: 16 }).reason, "step_limit");
    assert.equal(recipePolicy({ ...state, semanticAttempts: 2, critiquesUsed: 0, remainingRequests: 2 }).reason, "required_reserve");
  });
});

test("[U RTB-016] an ungrounded or unactionable critique cannot force another writer attempt", () => {
  for (const id of ["RTB-016"]) evidence(id, () => {
    const state = recipe(), before = structuredClone(state);
    for (const finding of [null, { actionable: false, evidenceVerified: true }, { actionable: true, evidenceVerified: false }, { actionable: false, evidenceVerified: false }]) {
      const input = { ...state, finding }, saved = structuredClone(input), decision = recipePolicy(input);
      assert.equal(decision.action, "direct"); assert.deepEqual(input, saved);
    }
    assert.equal(recipePolicy({ ...state, finding: { actionable: true, evidenceVerified: true } }).action, "revise");
    assert.deepEqual(state, before);
  });
});

test("[U WFL-006 T79] environment failures take precedence over repair, critique and supported revision", () => {
  for (const id of ["WFL-006", "T79"]) evidence(id, () => {
    for (const overrides of [{ qualityFailure: true }, { critiquesUsed: 0 }, { finding: { actionable: true, evidenceVerified: true } }]) {
      const input = { ...recipe(), ...overrides, environmentFailure: true }, before = structuredClone(input);
      assert.equal(recipePolicy(input).reason, "environment_failure_is_not_quality_failure");
      assert.equal(recipePolicy(input).action, "block"); assert.deepEqual(input, before);
    }
    assert.equal(recipePolicy({ ...recipe(), qualityFailure: true }).action, "direct");
    assert.equal(recipePolicy({ ...recipe(), finding: { actionable: true, evidenceVerified: true } }).action, "revise");
  });
});

test("[U WFL-007 T72] step ceiling blocks every proposed recipe without changing the original counters", () => {
  for (const id of ["WFL-007", "T72"]) evidence(id, () => {
    for (const stepsUsed of [16, 17]) for (const changes of [{}, { qualityFailure: true }, { critiquesUsed: 0 }, { finding: { actionable: true, evidenceVerified: true } }]) {
      const input = { ...recipe(), ...changes, stepsUsed }, before = structuredClone(input), result = recipePolicy(input);
      assert.equal(result.action, "block"); assert.equal(result.reason, "step_limit"); assert.deepEqual(input, before);
    }
    assert.equal(recipePolicy({ ...recipe(), stepsUsed: 15, qualityFailure: true }).action, "direct");
  });
});

const chain = [{ id: "primary-short", route: "primary", wait: { mode: "bounded" as const, maxMs: 100 } },
  { id: "backup", route: "backup", wait: { mode: "bounded" as const, maxMs: 200 } },
  { id: "primary-tail", route: "primary", wait: { mode: "forever" as const } }];
const admission = () => ({ now: 100, incidentId: "incident", approved: ["primary", "backup"], safeBoundary: true,
  primaryRoute: "primary", primaryRecovered: false, backupExhausted: false, notBefore: {} });

test("[U RTB-003 T50] an early primary candidate waits for termination and its own server floor", () => {
  const first = selectStage(chain, null, admission()), backup = selectStage(chain, first.state, { ...admission(), now: 200 });
  for (const id of ["RTB-003", "T50"]) evidence(id, () => {
    const busy = selectStage(chain, backup.state, { ...admission(), now: 220, primaryRecovered: true, safeBoundary: false });
    assert.equal(busy.route, null); assert.deepEqual(busy.state, backup.state);
    const cooldown = selectStage(chain, backup.state, { ...admission(), now: 220, primaryRecovered: true, notBefore: { primary: 221 } });
    assert.equal(cooldown.route, null); assert.equal(cooldown.reason, "route_not_before");
    const early = selectStage(chain, backup.state, { ...admission(), now: 221, primaryRecovered: true, notBefore: { primary: 221 } });
    assert.equal(early.route, "primary"); assert.ok(221 < backup.state!.deadline!); assert.equal(early.state!.incidentId, "incident");
    const unauthorized = selectStage(chain, backup.state, { ...admission(), now: 220, primaryRecovered: true, approved: ["backup"] });
    assert.equal(unauthorized.route, "backup");
  });
});

test("[U RTB-004] serialized stage restart cannot renew the deadline or bypass a server wait", () => {
  for (const id of ["RTB-004"]) evidence(id, () => {
    const first = selectStage(chain, null, admission());
    for (const now of [101, 150, 199]) {
      const restored = JSON.parse(JSON.stringify(first.state));
      const result = selectStage(chain, restored, { ...admission(), now, notBefore: { primary: 300 } });
      assert.equal(result.state!.stageEnteredAt, 100); assert.equal(result.state!.deadline, 200); assert.equal(result.route, null);
    }
    const at = selectStage(chain, first.state, { ...admission(), now: 200, notBefore: { backup: 250 } });
    assert.equal(at.state!.stageId, "backup"); assert.equal(at.state!.deadline, 400); assert.equal(at.route, null);
    const later = selectStage(chain, JSON.parse(JSON.stringify(at.state)), { ...admission(), now: 250, notBefore: { backup: 250 } });
    assert.equal(later.route, "backup"); assert.equal(later.state!.deadline, 400);
    assert.throws(() => selectStage(chain, later.state, { ...admission(), incidentId: "replacement" }), { code: "STAGE_RECONCILIATION_REQUIRED" });
  });
});
