import { test, assert } from "./recorded-test.ts";
import { readFileSync } from "node:fs";
import { classify, terminalError, isTemporaryQuota } from "../src/reliability/classifier.ts";
import type { Rule } from "../src/config.ts";
const sample = JSON.parse(readFileSync(new URL("./fixtures/qwen-observed-error.json", import.meta.url), "utf8")) as { terminalError: string; rules: Rule[] };
for (const id of ["REC-003", "T20"]) test(`[U ${id}] TC-${id}-U observed usage pressure is a configured temporary classification, not monthly exhaustion`, () => {
  const error = terminalError(sample.terminalError, null), result = classify(error, sample.rules, 1000);
  assert.equal(error.code, "throttling"); assert.equal(error.status, 429); assert.equal(result.category, "resource_pressure");
  assert.equal(isTemporaryQuota(result.category), true); assert.equal(result.retryAt, null);
  // A different service may give the same words a different documented meaning; the binding owns the rule.
  assert.equal(classify(error, [{ ...sample.rules[0], category: "frequency_limit" }], 1000).category, "frequency_limit");
  assert.equal(classify({ ...error, status: 401 }, sample.rules, 1000).category, "auth_billing_policy");
});
for (const id of ["REC-004", "T26"]) test(`[U ${id}] TC-${id}-U permanent failures cannot be promoted into quota retry by a matching temporary rule`, () => {
  for (const status of [401, 402, 403]) {
    const result = classify({ status, code: "throttling", message: "usage allocated quota exceeded", stream: "error" }, sample.rules, 1000);
    assert.equal(result.category, "auth_billing_policy"); assert.equal(isTemporaryQuota(result.category), false);
  }
  for (const category of ["context_contract", "auth_billing_policy", "execution_unknown", "other"] as const) {
    const result = classify({ status: 400, code: "configured-error", message: "synthetic", stream: "error" }, [{ code: "configured-error", category }], 1000);
    assert.equal(result.category, category); assert.equal(isTemporaryQuota(result.category), false);
  }
  assert.equal(classify({ status: 429, message: "temporary", stream: "error" }, [], 1000).category, "frequency_limit");
});
