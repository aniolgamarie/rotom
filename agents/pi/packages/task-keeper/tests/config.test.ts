import { test, assert, evidence } from "./recorded-test.ts";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import { parseConfig, applyProjectPolicy, initializeConfig, readConfig, DEFAULT_CONFIG, CONFIG_SCHEMA } from "../src/config.ts";
import { classify, retryAfter, scrub, terminalError } from "../src/reliability/classifier.ts";
import { capabilityStatus, executionRequirements } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";
import { isolatedDirectory } from "./helpers.ts";

import { configured } from "./fixtures/config.ts";

test("[CFG-004 CFG-005 CFG-006 CFG-008 CFG-009 T87] safe defaults, strict schema and idempotent monotonic restrictions", () => {
  assert.deepEqual(parseConfig({}), DEFAULT_CONFIG);
  for (const value of [{ ignoreRequiredChecks: true }, { budget: { protectedAttemptsPerWorkScope: -1 } }, { limits: { parallelReaders: NaN } },
    { recovery: { positiveJitterRatio: 2 } }, { advisor: { mode: "on-demand" } }]) {
    assert.throws(() => parseConfig(value));
  }
  assert.equal(parseConfig({ enabled: true, features: { interactiveRecovery: true } }).recovery.primaryRoute, null);
  const user = configured();
  const patch = { budget: { protectedAttemptsPerWorkScope: 100 }, limits: { parallelReaders: 0 }, allowedRoutes: [], workflow: { requiredChecks: { fix: [] } } };
  const restricted = applyProjectPolicy(user, patch);
  assert.equal(restricted.budget.protectedAttemptsPerWorkScope, 12);
  assert.equal(restricted.limits.parallelReaders, 0); assert.deepEqual(restricted.allowedRoutes, []);
  assert.deepEqual(restricted.workflow.requiredChecks.fix, user.workflow.requiredChecks.fix);
  assert.deepEqual(applyProjectPolicy(restricted, patch), restricted);
  for (const value of [{ routes: {} }, { network: {} }, { workflow: { requiredChecks: { fix: ["arbitrary-shell"] } } }]) {
    assert.throws(() => applyProjectPolicy(user, value));
  }
});

test("[CFG-003 CFG-010] initialization never overwrites policy and does not need local executor dependencies", (t) => {
  const path = join(isolatedDirectory(t), "task-keeper.json"); initializeConfig(path);
  const before = readFileSync(path, "utf8"); assert.equal(readConfig(path).enabled, false);
  assert.throws(() => initializeConfig(path)); assert.equal(readFileSync(path, "utf8"), before);
  assert.equal(configured().features.interactiveRecovery, true);
});

test("[CFG-003] shipped symbolic configuration and published schema match the executable contract", () => {
  const example = JSON.parse(readFileSync(new URL("../config.example.json", import.meta.url), "utf8"));
  const parsed = parseConfig(example);
  assert.deepEqual(JSON.parse(readFileSync(new URL("../config.schema.json", import.meta.url), "utf8")), CONFIG_SCHEMA);
  assert.equal(parsed.enabled, false); assert.equal(parsed.features.managedWorkflows, false);
  assert.equal(parsed.routes.primary.provider, "YOUR_PROVIDER"); assert.equal(parsed.advisor.mode, "off");
});

test("[REC-002 REC-003 REC-004 REC-008 T20 T21 T26 TK10] classifications use configured rules, permanent errors cannot become retryable", () => {
  const rules = [{ code: "UsageAllocated", category: "resource_pressure" as const }];
  assert.equal(classify({ status: 429, code: "UsageAllocated", message: "pressure", stream: "error" }, rules, 1000).category, "resource_pressure");
  assert.equal(classify({ status: 401, code: "UsageAllocated", message: "denied", stream: "error" }, rules, 1000).category, "auth_billing_policy");
  assert.equal(classify({ status: 200, message: "closed", stream: "incomplete" }, [], 1000).category, "network_overload");
  assert.equal(classify({ status: 200, message: "unknown error", stream: "error" }, [], 1000).category, "other");
  assert.equal(retryAfter("10", 1000), 11000); assert.equal(retryAfter("-1", 1000), null);
  assert.equal(retryAfter("broken", 1000), null); assert.equal(retryAfter("1.2", 1000), null);
  assert.equal(retryAfter("Thu, 01 Jan 1970 00:00:30 GMT", 1000), 30000);
  assert.equal(classify({ status: 429, message: "wait", stream: "error", headers: { "Retry-After": "10" }, resetAt: 50000 }, [], 1000).retryAt, 50000);
  assert.equal(scrub("Bearer SECRET api_key=KEY", ["SECRET", "KEY"]).includes("SECRET"), false);
  const error = terminalError('429: {"code":"UsageAllocated"}', { status: 200, headers: { "retry-after": "9999" } });
  assert.equal(error.status, 429); assert.equal(error.headers, undefined);
  assert.equal(classify(error, rules, 1000).category, "resource_pressure");
  assert.equal(terminalError("unstructured network error", null).status, undefined);
});

test("[EXE-001 EXE-002 RTB-007 T33 T48] only actual matching adapter evidence enables protected capabilities", () => {
  for (const id of ["T48"]) evidence(id, () => {
    const identity = { adapter: "fixture", version: "1", runtime: "24", profileDigest: "p", transportDigest: "t", mode: "foreground" };
    assert.equal(capabilityStatus(identity, null, ["settled"]).eligible, false);
    const cert = { identityDigest: digest(identity), capabilities: { settled: { supported: true, testEvidence: ["observed-test"], level: "A" as const } } };
    assert.equal(capabilityStatus(identity, cert, ["settled"]).eligible, true);
    assert.equal(capabilityStatus({ ...identity, mode: "background" }, cert, ["settled"]).eligible, false);
    assert.equal(capabilityStatus(identity, cert, executionRequirements("interactive", true)).eligible, false);
  });
});
