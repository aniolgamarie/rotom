import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DEFAULT_CONFIG, parseConfig, readConfig } from "../src/config.ts";
import { fromAgentcfg } from "../src/agentcfg-config.ts";

test("agentcfg generates usable three-role and real-check bindings without reading a legacy config", () => {
  const root = mkdtempSync(join(tmpdir(), "tk-config-")); mkdirSync(join(root, "pi-home"));
  writeFileSync(join(root, "pi-home/models.json"), JSON.stringify({ providers: { "agentcfg-fixture": { models: [{ id: "fake-model", reasoning: true }] } } }));
  const check = { executable: "/fixture/check", args: [], timeout_seconds: 30, foreground: true, project_root: "project", kind: "build", parser: "exit-code", minimum_tests: 1, inputs: [] };
  const runtime = { owner: { role: "manager" }, instanceRoot: root,
    roleManifest: { roles: ["reader", "writer", "reviewer"].map(name => ({ id: "task-keeper-" + name, managed: true, model: { provider: "agentcfg-fixture", model: "fake-model" } })) },
    manifest: { options: { task_keeper: { enabled: true, check_ids: ["build", "focused-tests"], second_view_enabled: false,
      limits: { model_requests: 20, model_turns: 20, wall_seconds: 1800 } }, network: { routes: { direct: { mode: "direct", provider_ids: ["fixture"] } } },
      checks: { build: check, "focused-tests": { ...check, kind: "tests", parser: "pytest" } } } } };
  const config = parseConfig(fromAgentcfg(DEFAULT_CONFIG, runtime));
  assert.equal(config.enabled, true); assert.equal(config.features.managedWorkflows, true);
  assert.equal(config.roles.worker.route, "managed-worker");
  assert.equal(config.executionProfiles.worker.thinking, "medium");
  assert.equal(config.verificationBindings["focused-tests"].parser, "pytest");
  assert.equal(config.storage.path, join(root, "pi-home/task-keeper/runtime.db"));
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key]; globalThis[key] = runtime;
  try { assert.deepEqual(readConfig("/not-an-authorized-legacy-path"), config); }
  finally { globalThis[key] = old; }
});
