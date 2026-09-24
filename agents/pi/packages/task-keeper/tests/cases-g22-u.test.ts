import { test, assert } from "./recorded-test.ts";
import { quotaTelemetry } from "../src/orchestration/policy.ts";
for (const id of ["RTB-014", "T32"]) test(`[U ${id}] TC-${id}-U telemetry provenance and freshness are independent required conditions`, () => {
  const expected = { account: "account", bucket: "pool", source: "source", now: 2000, freshnessMs: 1000 };
  const observation = { account: "account", bucket: "pool", source: "source", observedAt: 1000, remaining: 4, resetAt: null };
  for (const [observedAt, status] of [[1001, "observed"], [1000, "observed"], [999, "unknown"], [2001, "unknown"]] as const)
    assert.equal(quotaTelemetry({ ...observation, observedAt }, expected).status, status);
  for (const change of [{ account: "another" }, { bucket: "another" }, { source: "another" }, { remaining: -1 }, { remaining: NaN }, { observedAt: NaN }])
    assert.equal(quotaTelemetry({ ...observation, ...change }, expected).status, "unknown");
  assert.equal(quotaTelemetry(null, expected).status, "unknown");
  assert.equal(quotaTelemetry(observation, expected).reservation, false);
  assert.equal(quotaTelemetry({ ...observation, remaining: 0 }, expected).remaining, 0);
  assert.throws(() => quotaTelemetry({ ...observation, resetAt: 999 }, expected), { code: "INVALID_TELEMETRY_RESET" });
});
