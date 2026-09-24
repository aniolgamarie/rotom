import assert from "node:assert/strict";
import { test } from "node:test";
import { discoverRules, loadRuleConfig } from "../../packages/rules-vendor/dist/discovery.js";
import { ruleMatchesTarget, ruleMatchesToolCallEvent } from "../../packages/rules-vendor/dist/matching.js";
import { readDeclaredSkill } from "../service-bindings.ts";

const key = Symbol.for("agentcfg.pi.runtime.v1");
test("rules use the supervisor snapshot and keep upstream path/event matching", async () => {
  const calls = [];
  globalThis[key] = { owner: { role: "manager" }, manifest: { plugins: ["pi-rules"], options: { rules: { root_refs: ["rules"], after_commit_nudge: false } } },
    supervisor: { async call(method) { calls.push(method); return { rules: [{ id: "rules/cpp.md", body: "---\npaths: ['src/**/*.cpp']\nevents:\n  tool_call: [edit, write]\n---\nUse project style.\n" }] }; } } };
  try {
    assert.deepEqual((await loadRuleConfig("/unselected")).sources, []);
    await assert.rejects(discoverRules("/unselected", { home: "/must-not-read", sources: [{ scope: "user", kind: "claude" }] }), /RULES_SOURCE_OVERRIDE/);
    const result = await discoverRules("/unselected", { sources: [] });
    assert.deepEqual(calls, ["ordinary_rules_read"]);
    assert.equal(result.rules[0].body, "Use project style.\n");
    assert.equal(ruleMatchesTarget(result.rules[0], "src/module/main.cpp"), true);
    assert.equal(ruleMatchesTarget(result.rules[0], "README.md"), false);
    assert.equal(ruleMatchesToolCallEvent(result.rules[0], "edit"), true);
    assert.equal(ruleMatchesToolCallEvent(result.rules[0], "read"), false);
    globalThis[key].supervisor.call = async () => ({ rules: [{ id: "rules/bad.md", body: "---\nunknown: true\n---\nprivate raw body" }] });
    await assert.rejects(discoverRules("/unselected"), /RULES_FIELD_UNKNOWN/);
  } finally { delete globalThis[key]; }
});

test("rule-referenced skills cannot open unselected files or use managed scope", async () => {
  const calls = [];
  globalThis[key] = { owner: { role: "manager" }, cwd: "/project", resources: { skills: [{ path: "/selected/skill" }] },
    supervisor: { async call(method) { calls.push(method); return { operation_id: "read" }; } },
    ordinaryOperations: { async read() { return { bytes: Buffer.from("selected skill") }; } } };
  try {
    await assert.rejects(readDeclaredSkill("/unselected/auth.json"), /RULE_SKILL_UNSELECTED/);
    assert.deepEqual(calls, []);
    assert.equal(await readDeclaredSkill("/selected/skill/SKILL.md"), "selected skill");
    assert.deepEqual(calls, ["ordinary_prepare", "ordinary_finish"]);
    globalThis[key].managedRequestScope = { getStore: () => ({ task: true }) };
    await assert.rejects(readDeclaredSkill("/selected/skill/SKILL.md"), /RULE_SKILL_UNSELECTED/);
  } finally { delete globalThis[key]; }
});
