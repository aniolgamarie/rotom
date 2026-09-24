import { test, assert } from "./recorded-test.ts";
import { compileContextEvidence } from "../src/evidence/context.ts";
import { applyProjectPolicy, configurationPolicyDigest, DEFAULT_CONFIG } from "../src/config.ts";
import { digest } from "../src/contracts/primitives.ts";
import { classify } from "../src/reliability/classifier.ts";

test("[U EVD-005] context evidence uses exact UTF-8 byte boundaries without truncating a Unicode fact", () => {
  const body = { text: "汉🙂" }, exact = compileContextEvidence(body, 18);
  assert.equal(exact.bytes, 18); assert.equal(exact.content, '{"text":"汉🙂"}');
  assert.throws(() => compileContextEvidence(body, 17), { code: "PACKET_TOO_LARGE" });
  assert.deepEqual(compileContextEvidence(body, 19), exact);
  for (const limit of [0, -1, 1.5, Infinity]) assert.throws(() => compileContextEvidence(body, limit));
  const policy = applyProjectPolicy(DEFAULT_CONFIG, { evidence: { packetByteBudget: 1024 } });
  assert.equal(policy.evidence.packetByteBudget, 1024);
  assert.equal(applyProjectPolicy(policy, { evidence: { packetByteBudget: 65536 } }).evidence.packetByteBudget, 1024);
});

test("[U] an SDK connection-error wrapper cannot reclassify an explicit context-limit rejection as retryable network load", () => {
  const result = classify({ message: "Connection error", stream: "error", admission: "context-limit" }, [], 1);
  assert.equal(result.category, "context_contract"); assert.equal(result.evidence!.categorySource, "admission");
});

test("[U] presentation byte capacity preserves legacy execution authority while actual budgets remain part of its identity", () => {
  const legacy: Partial<typeof DEFAULT_CONFIG> = structuredClone(DEFAULT_CONFIG); delete legacy.evidence; delete legacy.scheduling; delete legacy.usage; delete legacy.timePolicy;
  assert.equal(configurationPolicyDigest(DEFAULT_CONFIG), digest(legacy));
  const changed = structuredClone(DEFAULT_CONFIG); changed.evidence.packetByteBudget++;
  assert.equal(configurationPolicyDigest(changed), configurationPolicyDigest(DEFAULT_CONFIG));
  changed.budget.backupAttemptsPerIncident++;
  assert.notEqual(configurationPolicyDigest(changed), configurationPolicyDigest(DEFAULT_CONFIG));
});
