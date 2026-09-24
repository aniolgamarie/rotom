import { test, assert } from "./recorded-test.ts";
import { configurationBindingGaps, DEFAULT_CONFIG, parseConfig } from "../src/config.ts";
import { configured } from "./fixtures/config.ts";

test("[U CFG-003] static binding diagnostics separate recovery, inspect and fix prerequisites", () => {
  const original = structuredClone(DEFAULT_CONFIG), gaps = configurationBindingGaps(DEFAULT_CONFIG);
  assert.deepEqual(gaps.interactiveRecovery, []);
  assert.deepEqual(gaps.inspect, ["roles.scout", "roles.reviewer"]);
  assert.deepEqual(gaps.fix, ["roles.worker", "roles.reviewer", "verificationBindings.build", "verificationBindings.focused-tests"]);
  const config = configured();
  for (const role of ["scout", "worker", "reviewer"]) config.roles[role] = { route: "primary", profileRef: "interactive" };
  for (const id of ["build", "focused-tests"]) config.verificationBindings[id] = { executable: "trusted-check", args: [], environment: {}, timeoutMs: 1000,
    kind: id === "build" ? "build" : "tests", parser: "json", minimumTests: 1, inputs: [] };
  assert.deepEqual(configurationBindingGaps(parseConfig(config)), { interactiveRecovery: [], inspect: [], fix: [] });
  config.limits.writersPerJob = 0;
  assert.deepEqual(configurationBindingGaps(config).fix, ["limits.writersPerJob"]);
  assert.deepEqual(configurationBindingGaps(config).inspect, []);
  config.workflow.requiredChecks.inspect.push("extra");
  assert.deepEqual(configurationBindingGaps(config).inspect, ["verificationBindings.extra"]);
  assert.deepEqual(DEFAULT_CONFIG, original);
});

test("[U CFG-009] unsupported Advisor modes report the unimplemented capability while malformed values remain configuration errors", () => {
  for (const mode of ["on-demand", "shadow", "always"]) assert.throws(() => parseConfig({ advisor: { mode } }), { code: "ADVISOR_NOT_IMPLEMENTED" });
  for (const mode of [null, 0, "invalid-mode"]) assert.throws(() => parseConfig({ advisor: { mode } }), { code: "INVALID_CONFIG" });
  assert.equal(parseConfig({ advisor: { mode: "off" } }).advisor.mode, "off");
});
