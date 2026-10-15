import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { constrainModels, launch, launchFailureCode, settingsStorage } from "../launch.ts";

function models() {
  const allowed = { provider: "fixture", id: "selected" }, other = { provider: "fixture", id: "unselected" };
  const calls = [];
  const runtime = { getModels: () => [allowed, other], getAvailableSnapshot: () => [allowed, other],
    getAvailable: async () => [allowed, other], getModel: (_, id) => id === "selected" ? allowed : other };
  for (const name of ["stream", "complete", "streamSimple", "completeSimple", "fetchDeferred", "cancelDeferred"]) {
    runtime[name] = model => { calls.push([name, model.id]); return "sent"; };
  }
  return { runtime, calls, allowed, other };
}

test("launch diagnostics expose only fixed local failure codes", async () => {
  await assert.rejects(launch({ manifest: { bootstrap: true }, argv: ["--print", "private prompt"] }), error => {
    assert.equal(launchFailureCode(error), "pi-main-model-unbound");
    return true;
  });
  const canary = "synthetic-private-exception-body";
  for (const error of [new Error(canary), { code: canary, exitCode: 4 }, null]) {
    assert.equal(launchFailureCode(error), "pi-launch-failed");
    assert.doesNotMatch(launchFailureCode(error), /synthetic-private/);
  }
});

test("bootstrap cannot select defaults or send model/helper requests; login remains separate", async () => {
  const f = models();
  const runtime = constrainModels(f.runtime, { bootstrap: true, allowed_models: [] });
  assert.deepEqual(runtime.getModels(), []);
  assert.deepEqual(await runtime.getAvailable(), []);
  assert.equal(runtime.getModel("fixture", "selected"), undefined);
  assert.throws(() => runtime.streamSimple(f.allowed), /pi-main-model-unbound/);
  assert.equal(f.calls.length, 0);
  await assert.rejects(launch({ manifest: { bootstrap: true }, argv: ["--print", "task"] }), /pi-main-model-unbound/);
});

test("ordinary request route must remain in the explicit model set", () => {
  const f = models();
  const runtime = constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  assert.deepEqual(runtime.getModels(), [f.allowed]);
  assert.notEqual(runtime.getModels()[0], f.allowed);
  assert.equal(runtime.streamSimple(f.allowed), "sent");
  assert.throws(() => runtime.completeSimple(f.other), /pi-model-not-selected/);
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
  const runtime = constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] },
    { getStore: () => ({ recordDenial: () => { denied++; } }) });
  assert.throws(() => runtime.completeSimple(f.allowed), /pi-managed-parent-helper-denied/);
  assert.equal(f.calls.length, 0);
  assert.equal(denied, 1);
});

test("helper cannot keep a permitted model name while replacing its API or endpoint", () => {
  const f = models(); f.allowed.api = "openai-completions"; f.allowed.baseUrl = "https://fixture.invalid/v1";
  const runtime = constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  assert.throws(() => runtime.completeSimple({ ...f.allowed, baseUrl: "https://unselected.invalid/v1" }), /pi-model-not-selected/);
  assert.throws(() => runtime.completeSimple({ ...f.allowed, api: "different" }), /pi-model-not-selected/);
  assert.equal(f.calls.length, 0);
});

 test("model facade preserves host methods and receiver while keeping one stable identity", () => {
  const f = models(), original = f.runtime.streamSimple;
  f.runtime.receiver = function () { return this; };
  const runtime = constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  assert.notEqual(runtime, f.runtime);
  assert.equal(f.runtime.streamSimple, original);
  assert.equal(runtime.receiver(), f.runtime);
  assert.equal(runtime.receiver, runtime.receiver);
  assert.throws(() => { runtime.streamSimple = original; }, /readonly/);
});

test("exposed model bindings are immutable snapshots, never a writable host route reference", () => {
  const f = models(); f.allowed.api = "openai-completions"; f.allowed.baseUrl = "https://fixture.invalid/v1";
  const runtime = constrainModels(f.runtime, { bootstrap: false, allowed_models: [{ provider: "fixture", model: "selected" }] });
  const exposed = runtime.getModel("fixture", "selected");
  assert.throws(() => { exposed.baseUrl = "https://unselected.invalid/v1"; }, TypeError);
  f.allowed.baseUrl = "https://unselected.invalid/v1";
  assert.throws(() => runtime.streamSimple(f.allowed), /pi-model-not-selected/);
  assert.equal(f.calls.length, 0);
});
