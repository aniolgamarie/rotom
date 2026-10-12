import assert from "node:assert/strict";
import { readFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { createOfficialDelegate } from "../../../agents/pi/runtime/official-delegate.ts";
import { createOfficialTaskKeeper } from "../../../agents/pi/runtime/official-task-keeper.ts";
import { captureOperationInput } from "../../../agents/pi/runtime/private-operation-input.ts";
import { selectResources } from "../../../agents/pi/runtime/resource-selection.ts";

const skill = (pkg, name) => readFileSync(new URL("../../../agents/pi/packages/" + pkg + "/skills/" + name + "/SKILL.md", import.meta.url), "utf8");
const examples = text => [...text.matchAll(/\x60\x60\x60json\n([\s\S]*?)\n\x60\x60\x60/g)].map(match => JSON.parse(match[1]));

test("modern delegation Skill examples traverse the actual factory capture with no SDK or sender", async () => {
  const calls = [];
  const factory = createOfficialDelegate({
    manifest: { profile_id: "pi-full", plugins: ["model-delegate"], plugin_capabilities: { "model-delegate": { capability_id: "unified-delegate" } } },
    sessionManager: { getSessionId: () => "owned-example-session" }, configurationSnapshot: async () => ({ configIdentity: "fixed" }), policySnapshot() {},
    supervisor: { async call(method, input) {
      calls.push({ method, input: structuredClone(input) });
      return method === "delegate_source_open_v3" ? { source_ref: "synthetic-example-ref" } : { status: "unknown" };
    } },
  });
  const values = examples(skill("model-delegate-modern", "managed-delegation"));
  assert.deepEqual(values.map(row => row.action), factory.tool.parameters.properties.action.enum);
  for (const value of values) {
    const result = await factory.tool.execute("example", value);
    assert.equal(result.isError, true); // 合成unknown不得被文档示例当成功。
  }
  assert.deepEqual(calls.filter(row => row.method === "delegate_action_v3").map(row => row.input.action), values);
  assert.equal(calls.filter(row => row.method === "delegate_source_open_v3").length, 1);
  factory.retire(); await factory.drain();
});

test("modern workflow Skill JSON uses the actual closed public tool schema and pure input capture", async () => {
  const factory = createOfficialTaskKeeper({
    manifest: { profile_id: "pi-full", plugins: ["task-keeper"], plugin_capabilities: { "task-keeper": { capability_id: "task-workflow" } }, options: { task_keeper: { enabled: true } } },
    installed: {}, sessionManager: { getSessionId: () => "owned-example-session" },
    issuer: { open() { throw Error("not executed"); }, retire() {} }, configurationSnapshot: async () => ({}), policySnapshot() {},
  });
  const values = examples(skill("task-keeper-modern", "managed-workflow"));
  assert.deepEqual(values.map(row => row.action), factory.tool.parameters.properties.action.enum);
  for (const value of values) {
    const captured = captureOperationInput(value).value;
    assert.deepEqual(captured, value);
    assert.ok(Object.keys(value).every(key => Object.hasOwn(factory.tool.parameters.properties, key)));
    if (value.action === "submit") assert.deepEqual(Object.keys(value).sort(), ["action", "goal"]);
    else assert.deepEqual(Object.keys(value).sort(), ["action", "job_id"]);
  }
  await factory.close();
});

test("scheduler package Skills follow each selected Full capability and never Base selection", () => {
  const root = mkdtempSync(join(tmpdir(), "scheduler-skills-"));
  const instanceRoot = join(root, "instance"), runtimeRoot = join(root, "runtime"), cwd = join(root, "project");
  for (const path of [instanceRoot, runtimeRoot, cwd]) mkdirSync(path);
  mkdirSync(join(instanceRoot, "pi-home"));
  for (const name of ["AGENTS.md", "APPEND_SYSTEM.md"]) writeFileSync(join(instanceRoot, "pi-home", name), "owned fixture\n");
  const rows = [];
  for (const [source, name, cap] of [["model-delegate-modern", "managed-delegation", "unified-delegate"], ["task-keeper-modern", "managed-workflow", "task-workflow"]]) {
    const path = source + "/skills/" + name;
    mkdirSync(join(runtimeRoot, path), { recursive: true });
    writeFileSync(join(runtimeRoot, path, "SKILL.md"), skill(source, name));
    rows.push({ id: source + "-skill", capability_id: cap, path });
  }
  const groups = ["extensions", "skills", "prompts", "themes", "roles"];
  for (const [profile, selected, ids] of [["pi-base", [], []], ["pi-full", ["model-delegate"], ["model-delegate-modern-skill"]],
    ["pi-full", ["model-delegate", "task-keeper"], ["model-delegate-modern-skill", "task-keeper-modern-skill"]]]) {
    const mapping = Object.fromEntries(selected.map(name => [name, { capability_id: name === "model-delegate" ? "unified-delegate" : "task-workflow", model_tools: [] }]));
    const manifest = { schema_version: 1, profile_id: profile, engine: "node", bootstrap: false, plugins: selected, plugin_capabilities: mapping,
      resources: Object.fromEntries(groups.map(group => [group, []])), resource_ids: Object.fromEntries(groups.map(group => [group, {}])),
      options: { discovery: { project_resources: false } }, project_resources: [], external_skills: [] };
    const installed = Object.fromEntries(groups.map(group => [group, group === "skills" ? rows : []]));
    assert.deepEqual(selectResources({ manifest, installed, instanceRoot, runtimeRoot, cwd, engine: "node" }).resources.skills.map(row => row.id), ids);
  }
});
