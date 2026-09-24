import { test, assert } from "./recorded-test.ts";
import { DEFAULT_CONFIG, parseConfig, applyProjectPolicy, configurationPolicyDigest } from "../src/config.ts";
import { digest } from "../src/contracts/primitives.ts";

test("[U SCH-006] user scheduling settings are bounded while project policies cannot replace the shared ordering policy", () => {
  const user = parseConfig({ scheduling: { agingMs: 25, priorities: { inspect: 70, fix: 10 } } });
  assert.deepEqual(user.scheduling, { agingMs: 25, priorities: { inspect: 70, fix: 10 } });
  assert.throws(() => applyProjectPolicy(user, { scheduling: { agingMs: 1, priorities: { inspect: 100, fix: 100 } } }), { code: "UNKNOWN_FIELD" });
  assert.deepEqual(applyProjectPolicy(user, {}).scheduling, user.scheduling);
  for (const priorities of [{ inspect: -1 }, { fix: 101 }, { inspect: "10" }, { unrelated: 1 }]) assert.throws(() => parseConfig({ scheduling: { priorities } }));
  for (const agingMs of [0, -1, 0.5, 2147483648, "100"]) assert.throws(() => parseConfig({ scheduling: { agingMs } }));
});

test("[U] default scheduling preserves legacy policy identity and customized ordering participates in authorization", () => {
  const legacy: Partial<typeof DEFAULT_CONFIG> = structuredClone(DEFAULT_CONFIG); delete legacy.evidence; delete legacy.scheduling; delete legacy.usage; delete legacy.timePolicy;
  assert.equal(configurationPolicyDigest(parseConfig({})), digest(legacy));
  assert.equal(configurationPolicyDigest(parseConfig({ scheduling: { agingMs: 60000, priorities: { inspect: 0, fix: 0 } } })), digest(legacy));
  assert.notEqual(configurationPolicyDigest(parseConfig({ scheduling: { agingMs: 1 } })), digest(legacy));
  assert.notEqual(configurationPolicyDigest(parseConfig({ scheduling: { priorities: { inspect: 1 } } })), digest(legacy));
});
