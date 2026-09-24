import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { constrainModels, launch, settingsStorage } from "../launch.ts";

function models() {
  const allowed = { provider: "fixture", id: "selected" }, other = { provider: "fixture", id: "unselected" };
  const calls = [];
  const runtime = { getModels: () => [allowed, other], getAvailableSnapshot: () => [allowed, other],
    getAvailable: async () => [allowed, other], getModel: (_, id) => id === "selected" ? allowed : other };
  for (const name of ["prepareRequest", "stream", "complete", "streamSimple", "completeSimple", "fetchDeferred", "cancelDeferred"]) {
    runtime[name] = model => { calls.push([name, model.id]); return "sent"; };
  }
  return { runtime, calls, allowed, other };
}

test("bootstrap cannot select defaults or send model/helper requests; login remains separate", async () => {
  const f = models();
  constrainModels(f.runtime, { bootstrap: true, allowed_models: [] });
  assert.deepEqual(f.runtime.getModels(), []);
  assert.deepEqual(await f.runtime.getAvailable(), []);
  assert.equal(f.runtime.getModel("fixture", "selected"), undefined);
  assert.throws(() => f.runtime.streamSimple(f.allowed), /pi-main-model-unbound/);
  assert.equal(f.calls.length, 0);
  await assert.rejects(launch({ manifest: { bootstrap: true }, argv: ["--print", "task"] }), /pi-main-model-unbound/);
});

test("ordinary request route must remain in the explicit model set", () => {
  const f = models();
  constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  assert.deepEqual(f.runtime.getModels(), [f.allowed]);
  assert.equal(f.runtime.streamSimple(f.allowed), "sent");
  assert.throws(() => f.runtime.completeSimple(f.other), /pi-model-not-selected/);
  assert.deepEqual(f.calls, [["streamSimple", "selected"]]);
});

test("settings preserve UI changes but never enable native package discovery or project overrides", () => {
  const home = mkdtempSync(join(tmpdir(), "settings-"));
  const path = join(home, "settings.json");
  writeFileSync(path, JSON.stringify({ theme: "test", packages: ["npm:unselected"] }), { mode: 0o600 });
  const storage = settingsStorage(path);
  storage.withLock("global", text => {
    const state = JSON.parse(text);
    assert.deepEqual(state.packages, []);
    return JSON.stringify({ ...state, theme: "changed", extensions: ["/unselected"] });
  });
  const saved = JSON.parse(readFileSync(path, "utf8"));
  assert.equal(saved.theme, "changed");
  assert.deepEqual(saved.extensions, []);
  storage.withLock("project", text => { assert.equal(text, undefined); });
  assert.throws(() => storage.withLock("project", () => "{}"), /pi-project-settings-disabled/);
});

test("project role frontmatter cannot replace configured identity, model or tools", async () => {
  const { compileRoles } = await import("../launch.ts");
  const root = mkdtempSync(join(tmpdir(), "roles-"));
  const source = join(root, "project.md");
  writeFileSync(source, "untrusted source");
  const sdk = { parseFrontmatter: () => ({ frontmatter: { name: "task-keeper-writer", tools: "bash", model: "unselected" }, body: "bounded review instructions" }) };
  const binding = { model: { provider: "fixture", model: "selected" }, tools: ["read"], read_roots: ["project"], write_roots: [], managed: false };
  const manifest = { role_bindings: { reviewer: binding } };
  const selection = { digest: "fixture", resources: { roles: [{ id: "reviewer", path: source, digest: "source", scope: "project" }] } };
  const path = compileRoles(sdk, manifest, selection, root);
  const role = JSON.parse(readFileSync(path, "utf8")).roles[0];
  const rendered = readFileSync(role.path, "utf8");
  assert.match(rendered, /model: "fixture\/selected"/);
  assert.match(rendered, /tools: "read"/);
  assert.doesNotMatch(rendered, /task-keeper-writer|unselected|bash/);
  binding.managed = true;
  assert.throws(() => compileRoles(sdk, manifest, selection, root), /pi-role-binding/);
});

test("parent SDK helper requests cannot bypass the managed task scope using another transport", () => {
  const f = models();
  let denied = 0;
  constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] },
    { getStore: () => ({ recordDenial: () => { denied++; } }) });
  assert.throws(() => f.runtime.completeSimple(f.allowed), /pi-managed-parent-helper-denied/);
  assert.equal(f.calls.length, 0);
  assert.equal(denied, 1);
});

test("helper cannot keep a permitted model name while replacing its API or endpoint", () => {
  const f = models(); f.allowed.api = "openai-completions"; f.allowed.baseUrl = "https://fixture.invalid/v1";
  constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  assert.throws(() => f.runtime.completeSimple({ ...f.allowed, baseUrl: "https://unselected.invalid/v1" }), /pi-model-not-selected/);
  assert.throws(() => f.runtime.completeSimple({ ...f.allowed, api: "different" }), /pi-model-not-selected/);
  assert.equal(f.calls.length, 0);
});
