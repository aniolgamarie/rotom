import { test, assert } from "./recorded-test.ts";
import { routeRequirements } from "../src/adapters/route-requirements.ts";
import type { Profile } from "../src/config.ts";

test("[U WFL-001] a requested reader cannot obtain write, edit or unrestricted shell through its profile", () => {
  const model = { api: "openai-completions", provider: "fixture", id: "model", baseUrl: "http://fixture.invalid", reasoning: false, contextWindow: 32000, maxTokens: 1000 };
  const profile: Profile = { tools: ["read", "grep", "find", "ls"], requiredCapabilities: ["readonly"], thinking: "off", timeoutMs: 1000, maxModelTurns: 2, toolTimeoutMs: 1000 };
  assert.equal(routeRequirements(model, profile, "scout", false).eligible, true);
  for (const extra of ["write", "edit", "bash"]) {
    const input = { ...profile, tools: [...profile.tools, extra] }, before = structuredClone(input);
    const decision = routeRequirements(model, input, "scout", false);
    assert.equal(decision.eligible, false); assert.ok(decision.reasons.includes("tool_profile_mismatch")); assert.deepEqual(input, before);
  }
  const writer = { ...profile, tools: ["read", "grep", "find", "ls", "write", "edit"], requiredCapabilities: [] };
  assert.equal(routeRequirements(model, writer, "worker", false).eligible, true);
  assert.equal(routeRequirements(model, writer, "scout", false).eligible, false);
});
