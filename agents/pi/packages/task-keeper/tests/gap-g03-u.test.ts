import { test, assert } from "./recorded-test.ts";
import { readFileSync } from "node:fs";
import { classify, terminalError, isTemporaryQuota } from "../src/reliability/classifier.ts";
import type { Rule } from "../src/config.ts";
const samples = JSON.parse(readFileSync(new URL("./fixtures/qwen-service-errors.json", import.meta.url), "utf8")) as {
  sources: Record<string, string>; cases: Array<{ id: string; source: string; status: number; body: unknown; rules: Rule[]; expected: string }> };
for (const id of ["CFG-002", "REC-002", "TK10"]) test(`[U ${id}] source-tagged service envelopes normalize through configured rules without model-name branches`, () => {
  for (const sample of samples.cases) {
    assert.ok(samples.sources[sample.source].startsWith("https://"));
    const text = `${sample.status} ${JSON.stringify(sample.body)}`;
    const signal = terminalError(text, { status: sample.status, headers: { "retry-after": "1" } });
    const result = classify(signal, sample.rules, 1000);
    assert.equal(result.category, sample.expected, sample.id); assert.equal(result.retryAt, 2000);
    for (const changedName of ["qwen-symbolic", "other-family-symbolic"]) {
      assert.equal(classify({ ...signal, message: `${changedName}: ${signal.message}` }, sample.rules, 1000).category, sample.expected);
    }
    if ([401,403].includes(sample.status)) assert.equal(isTemporaryQuota(result.category), false);
  }
  assert.equal(terminalError('429 {"code":429002,"message":"TPM"}', null).code, "429002");
  assert.equal(classify({ message: "unknown", stream: "error" }, [], 1000).category, "other");
});
