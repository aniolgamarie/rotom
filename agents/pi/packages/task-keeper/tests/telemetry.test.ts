import { test, assert, evidence } from "./recorded-test.ts";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";
import { readQuotaTelemetry } from "../src/adapters/telemetry.ts";

test("[A RTB-014 T32] configured telemetry adapter requires exact account/bucket/source, fresh private evidence and sufficient remainder", (t) => {
  const config = configured(), route = config.routes.primary, path = join(isolatedDirectory(t), "observation.json");
  route.telemetry = "snapshot";
  config.telemetryBindings.snapshot = { path, accountBinding: route.accountBinding, bucket: route.quotaGroup, source: "fixture", freshnessMs: 100, minimumRemaining: 2 };
  const write = (value: object) => writeFileSync(path, JSON.stringify(value), { mode: 0o600 });
  const observation = { account: route.accountBinding, bucket: route.quotaGroup, source: "fixture", observedAt: 1000, remaining: 3, resetAt: 2000 };
  assert.equal(readQuotaTelemetry(config, route, 1050).eligible, false);
  write(observation);
  for (const id of ["RTB-014", "T32"]) evidence(id, () => {
    const valid = readQuotaTelemetry(config, route, 1050); assert.equal(valid.eligible, true); assert.equal(valid.status, "observed"); assert.equal(valid.remaining, 3);
    assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), observation);
    const expired = readQuotaTelemetry(config, route, 1101); assert.equal(expired.eligible, false); assert.equal(expired.status, "unknown"); assert.equal(expired.remaining, null);
  });
  assert.equal(readQuotaTelemetry(config, route, 1101).eligible, false);
  for (const changed of [{ account: "other" }, { bucket: "other" }, { source: "other" }, { observedAt: 1200 }, { remaining: 1 }]) {
    const input = { ...observation, ...changed }; write(input);
    for (const id of ["RTB-014", "T32"]) evidence(id, () => {
      const actual = readQuotaTelemetry(config, route, 1050); assert.equal(actual.eligible, false);
      assert.equal(actual.status, "remaining" in changed ? "observed" : "unknown");
      assert.equal(actual.remaining, "remaining" in changed ? 1 : null);
      assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), input);
    });
  }
});
