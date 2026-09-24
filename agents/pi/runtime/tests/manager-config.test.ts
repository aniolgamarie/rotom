import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assertSingleManager, assertOrdinaryOptions, controlledSettings, loadControlledRoles, RUNTIME_KEY, MANAGER_KEY, BRIDGE_KEY } from "../../packages/subagents-vendor/src/agentcfg-config.ts";
import { resolveModel } from "../../packages/subagents-vendor/src/model-resolver.ts";

test("factory admission rejects absent, worker and duplicate managers before allocation", () => {
  try {
    delete globalThis[RUNTIME_KEY];
    assert.throws(assertSingleManager, /CONTEXT_REQUIRED/);
    globalThis[RUNTIME_KEY] = { owner: { role: "worker" }, supervisor: {} };
    assert.throws(assertSingleManager, /CONTEXT_REQUIRED/);
    globalThis[RUNTIME_KEY].owner.role = "manager";
    assertSingleManager();
    assert.equal(controlledSettings().schedulingEnabled, false);
    assert.equal(controlledSettings().workflowsEnabled, false);
    for (const key of [MANAGER_KEY, BRIDGE_KEY]) {
      globalThis[key] = {};
      assert.throws(assertSingleManager, /LISTENER_CONFLICT/);
      delete globalThis[key];
    }
  } finally { delete globalThis[RUNTIME_KEY]; delete globalThis[MANAGER_KEY]; delete globalThis[BRIDGE_KEY]; }
});

test("ordinary RPC rejects privileged option presence rather than dropping supplied fields", () => {
  assertOrdinaryOptions({ description: "fixture", cwd: "/tmp" });
  for (const key of ["unknown_option", "bypassQueue", "owner_nonce", "executor", "workflowId", "resumeSessionFile", "depth"]) {
    assert.throws(() => assertOrdinaryOptions({ [key]: false }), /SPAWN_FORBIDDEN/);
  }
  assert.throws(() => assertOrdinaryOptions({ [Symbol("private")]: {} }), /SPAWN_FORBIDDEN/);
});

test("explicit role snapshot separates registries and rejects changed content", () => {
  const cwd = mkdtempSync(join(tmpdir(), "roles-"));
  const roles = [false, true].map((managed, index) => {
    const path = join(cwd, index + ".md"), content = "controlled body " + index;
    writeFileSync(path, content, { mode: 0o600 });
    return { id: "fixture-" + index, path, compiled_digest: createHash("sha256").update(content).digest("hex"), managed,
      model: { provider: "fake", model: "fake-model" }, tools: ["read"] };
  });
  try {
    globalThis[RUNTIME_KEY] = { owner: { role: "manager" }, supervisor: {}, roleManifest: { schema_version: 1, roles },
      manifest: { role_bindings: Object.fromEntries(roles.map(role => [role.id, role])) } };
    const parser = content => ({ body: content });
    assert.deepEqual([...loadControlledRoles(parser).keys()], ["fixture-0"]);
    assert.deepEqual([...loadControlledRoles(parser, true).keys()], ["fixture-1"]);
    assert.equal(loadControlledRoles(parser).get("fixture-0").model, "fake/fake-model");
    writeFileSync(roles[1].path, "changed body");
    assert.throws(() => loadControlledRoles(parser), /ROLE_CHANGED/);
  } finally { delete globalThis[RUNTIME_KEY]; }
});

test("model resolver accepts exact provider and model only", () => {
  const models = [{ provider: "fake", id: "fake-model", name: "Fake" }];
  const registry = { getAll: () => models, find: (provider, id) => models.find(value => value.provider === provider && value.id === id) };
  assert.equal(resolveModel("fake/fake-model", registry), models[0]);
  for (const value of ["fake-model", "Fake/fake-model", "different/fake-model", "fake/fake"]) {
    assert.equal(typeof resolveModel(value, registry), "string");
  }
});
