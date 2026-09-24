import { test, assert, evidence } from "./recorded-test.ts";
import { classify, type FailureSignal } from "../src/reliability/classifier.ts";
const signal: FailureSignal = { status: 429, code: "window", message: "fixture window", stream: "error" };
test("[U REC-008 T21] server reset and Retry-After keep separate provenance and the later floor", () => {
  for (const id of ["REC-008", "T21"]) evidence(id, () => {
    for (const [header, reset, expected] of [["1", 4000, 4000], ["5", 4000, 6000], ["3", 4000, 4000]] as const) {
      const result = classify({ ...signal, headers: { "Retry-After": header }, resetAt: reset }, [{ code: "window", category: "window_quota" }], 1000);
      assert.equal(result.retryAt, expected); assert.equal(result.evidence!.retryAfterAt, 1000 + Number(header) * 1000);
      assert.equal(result.evidence!.resetAt, reset); assert.equal(result.evidence!.categorySource, "binding-rule");
      assert.equal(result.evidence!.uncertain, false); assert.equal(result.code, "window");
    }
    const unknown = classify(signal, [{ code: "window", category: "window_quota" }], 1000);
    assert.equal(unknown.retryAt, null); assert.equal(unknown.evidence!.uncertain, true);
    assert.equal(unknown.evidence!.retryAfterAt, null); assert.equal(unknown.evidence!.resetAt, null);
    const invalid = classify({ ...signal, headers: { "retry-after": "-1" }, resetAt: NaN }, [], 1000);
    assert.equal(invalid.retryAt, null);
  });
});

test("[U REC-002] configured error interpretation records its rule and preserves explicit uncertainty", () => {
  const rules = [{ code: "unmatched", category: "other" as const }, { code: "window", category: "resource_pressure" as const }];
  const matched = classify(signal, rules, 1000);
  assert.equal(matched.evidence!.ruleIndex, 1); assert.equal(matched.evidence!.categorySource, "binding-rule");
  assert.equal(matched.category, "resource_pressure"); assert.equal(matched.retryAt, null); assert.equal(matched.evidence!.uncertain, false);
  const permanent = classify({ ...signal, status: 403 }, rules, 1000);
  assert.equal(permanent.evidence!.ruleIndex, null); assert.equal(permanent.evidence!.categorySource, "http-status");
  assert.equal(permanent.category, "auth_billing_policy");
  const unknown = classify({ message: "unrecognized", stream: "error" }, [], 1000);
  assert.equal(unknown.category, "other"); assert.equal(unknown.evidence!.uncertain, true); assert.equal(unknown.evidence!.categorySource, "unclassified");
  const transport = classify({ message: "ECONNRESET", stream: "error" }, [], 1000);
  assert.equal(transport.evidence!.categorySource, "transport-signal"); assert.equal(transport.category, "network_overload");
  assert.equal(classify({ ...signal, admission: "retry-after" }, [], 1000).evidence!.categorySource, "admission");
  const secret = "fixture-sensitive-value", redacted = classify({ ...signal, code: secret, message: secret }, [], 1000, [secret]);
  assert.equal(JSON.stringify(redacted).includes(secret), false);
});
