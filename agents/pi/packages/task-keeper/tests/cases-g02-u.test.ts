import { test, assert } from "./recorded-test.ts";
import { applyProjectPolicy, parseConfig, configurationPolicyDigest, type Config } from "../src/config.ts";
import { configured } from "./fixtures/config.ts";

type Restrict = typeof applyProjectPolicy;
const userPolicy = () => {
  const user = configured();
  user.verificationBindings.extra = { executable: "fixture-check", args: ["literal;$(not-a-command)"], environment: {}, timeoutMs: 1000,
    kind: "tests", parser: "json", minimumTests: 1 };
  return user;
};
const cases: Record<string, (restrict: Restrict) => void> = {
  "CFG-004": restrict => {
    const user = userPolicy(), before = structuredClone(user);
    assert.equal(restrict(user, { features: { semanticReplanning: true } }).features.semanticReplanning, false);
    const enabled = { ...user, features: { ...user.features, semanticReplanning: true } };
    assert.equal(restrict(enabled, { features: { semanticReplanning: false } }).features.semanticReplanning, false);
    assert.equal(configurationPolicyDigest({ ...user, features: { ...user.features, semanticReplanning: false } }), configurationPolicyDigest(user));
    assert.notEqual(configurationPolicyDigest(enabled), configurationPolicyDigest(user));
    for (const cap of [24, 12, 6, 1, 0]) {
      const result = restrict(user, { budget: { protectedAttemptsPerWorkScope: cap }, workflow: { requiredChecks: { fix: [] } } });
      assert.equal(result.budget.protectedAttemptsPerWorkScope, Math.min(12, cap));
      assert.deepEqual(result.workflow.requiredChecks.fix, user.workflow.requiredChecks.fix);
      assert.deepEqual(user, before);
    }
  },
  "CFG-005": restrict => {
    const user = userPolicy();
    for (const patch of [{ ignoreRequiredChecks: true }, { cancelMayResume: true }, { workflow: { ignoreRequiredChecks: true } },
      { features: { cancelMayResume: true } }]) assert.throws(() => restrict(user, patch));
    assert.equal(restrict(user, { enabled: false }).enabled, false);
    assert.deepEqual(restrict(user, {}).workflow.requiredChecks, user.workflow.requiredChecks);
  },
  "CFG-006": restrict => {
    const user = userPolicy(), before = structuredClone(user);
    assert.throws(() => restrict(user, { verificationBindings: { untrusted: user.verificationBindings.extra } }));
    assert.throws(() => restrict(user, { workflow: { requiredChecks: { fix: ["untrusted"] } } }));
    for (const key of ["routes", "roles", "network", "telemetryBindings"]) assert.throws(() => restrict(user, { [key]: {} }));
    const result = restrict(user, { workflow: { requiredChecks: { fix: ["extra"] } } });
    assert.deepEqual(result.workflow.requiredChecks.fix, [...user.workflow.requiredChecks.fix, "extra"]);
    assert.deepEqual(result.verificationBindings, user.verificationBindings); assert.deepEqual(user, before);
  },
  "CFG-008": restrict => {
    const user = userPolicy();
    const patch = { budget: { protectedAttemptsPerWorkScope: 0 }, allowedRoutes: [], workflow: { recipes: [] }, limits: { parallelReaders: 0 } };
    const result = restrict(user, patch);
    assert.equal(result.budget.protectedAttemptsPerWorkScope, 0); assert.deepEqual(result.allowedRoutes, []);
    assert.deepEqual(result.workflow.recipes, []); assert.equal(result.limits.parallelReaders, 0);
    assert.deepEqual(restrict(result, patch), result); assert.deepEqual(restrict(user, {}), user);
    for (const input of [null, -1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      assert.throws(() => restrict(user, { budget: { protectedAttemptsPerWorkScope: input } }));
    }
    assert.throws(() => restrict(user, { allowedRoutes: null }));
    for (const ratio of [-0.01, 1.01, NaN, Infinity]) assert.throws(() => parseConfig({ recovery: { positiveJitterRatio: ratio } }));
    for (const ratio of [0, 0.5, 1]) assert.equal(parseConfig({ recovery: { positiveJitterRatio: ratio } }).recovery.positiveJitterRatio, ratio);
  },
  "CFG-009": restrict => {
    for (const mode of ["on-demand", "shadow", "always", null]) assert.throws(() => parseConfig({ advisor: { mode } }));
    const user = userPolicy(); assert.throws(() => restrict(user, { advisor: { mode: "off" } }));
    assert.equal(parseConfig({ advisor: { mode: "off" } }).advisor.mode, "off");
    assert.equal(restrict(user, {}).advisor.mode, "off");
  },
  "T87": restrict => {
    const user = userPolicy();
    for (const patch of [{ ignoreRequiredChecks: true }, { cancelMayResume: true }, { enabled: true, allowedRoutes: ["unbound"] },
      { budget: { unknownReservationIsFree: true } }, { workflow: { optionalChecks: { fix: ["untrusted"] } } }]) assert.throws(() => restrict(user, patch));
    const disabled = { ...user, enabled: false, features: { ...user.features, crossProviderFailover: false } };
    const result = restrict(disabled, { enabled: true, features: { crossProviderFailover: true }, budget: { protectedAttemptsPerWorkScope: 999 } });
    assert.equal(result.enabled, false); assert.equal(result.features.crossProviderFailover, false);
    assert.equal(result.budget.protectedAttemptsPerWorkScope, 12);
  },
};
for (const [id, check] of Object.entries(cases)) test(`[U ${id}] TC-${id}-U project restrictions preserve authority with independent boundary expectations`, () => check(applyProjectPolicy));

test("[U] G02 negative control detects a merger that accepts an expanded budget", () => {
  const bad: Restrict = (user, input) => {
    const result = applyProjectPolicy(user, input), budget = (input as Partial<Config>).budget;
    if (budget?.protectedAttemptsPerWorkScope !== undefined) result.budget.protectedAttemptsPerWorkScope = budget.protectedAttemptsPerWorkScope;
    return result;
  };
  assert.throws(() => cases["CFG-004"](bad), { name: "AssertionError" });
  cases["CFG-004"](applyProjectPolicy);
});
