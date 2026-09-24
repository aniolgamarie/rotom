import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { selectResources, installPackagePolicy, loaderOptions, parseArguments, restrictExtensions } from "../resource-loader.ts";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "loader-"));
  const instanceRoot = join(root, "instance"), runtimeRoot = join(root, "runtime"), cwd = join(root, "project");
  for (const path of [instanceRoot, runtimeRoot, cwd]) mkdirSync(path);
  function put(base, path, text = "fixture resource") {
    const target = join(base, path);
    mkdirSync(join(target, ".."), { recursive: true });
    writeFileSync(target, text);
    return target;
  }
  put(runtimeRoot, "packages/selected/index.js");
  put(runtimeRoot, "packages/unselected/index.js", "throw Error('unselected factory ran')");
  put(instanceRoot, "pi-home/prompts/review.md");
  put(instanceRoot, "pi-home/AGENTS.md", "selected rules");
  put(instanceRoot, "pi-home/APPEND_SYSTEM.md", "selected append rules");
  put(cwd, ".pi/extensions/undeclared.js", "throw Error('discovered project factory')");
  const resources = { roles: [], extensions: [], skills: [], prompts: ["pi-home/prompts/review.md"], themes: [] };
  const resource_ids = { roles: {}, extensions: {}, skills: {}, prompts: { review: resources.prompts[0] }, themes: {} };
  const manifest = { schema_version: 1, engine: "node", bootstrap: false, resources, resource_ids, plugins: ["selected"],
    options: { discovery: { project_resources: false } }, project_resources: [], external_skills: [] };
  const installed = { extensions: [
    { id: "selected", capability_id: "selected", path: "packages/selected/index.js" },
    { id: "unselected", capability_id: "unselected", path: "packages/unselected/index.js" },
  ], skills: [], prompts: [], themes: [] };
  return { instanceRoot, runtimeRoot, cwd, manifest, installed, engine: "node", put };
}

test("selection precedes factories; neither cwd discovery nor installed extras participates", async () => {
  const f = fixture();
  const selected = selectResources(f);
  const calls = [];
  class FakePackages {
    async resolve() { throw Error("native discovery"); }
    async resolveExtensionSources() { throw Error("native temporary install"); }
    async install() { calls.push("download"); }
    async update() { calls.push("update"); }
  }
  installPackagePolicy({ DefaultPackageManager: FakePackages }, selected);
  const manager = new FakePackages();
  assert.deepEqual(await manager.resolve(), { extensions: [], skills: [], prompts: [], themes: [] });
  const options = loaderOptions(selected);
  const paths = await manager.resolveExtensionSources(options.additionalExtensionPaths);
  for (const resource of paths.extensions) calls.push(resource.path);
  assert.deepEqual(calls, [join(f.runtimeRoot, "packages/selected/index.js")]);
  assert.equal(options.noContextFiles, true);
  assert.equal(options.noExtensions, true);
  assert.equal(options.agentsFilesOverride({ agentsFiles: [] }).agentsFiles[0].content, "selected rules");
  await assert.rejects(manager.install("npm:evil"), /agentcfg/);
  await assert.rejects(manager.update(), /agentcfg/);
  await assert.rejects(manager.resolveExtensionSources(["npm:evil"]), /pi-resource/);
  await assert.rejects(manager.resolveExtensionSources([join(f.cwd, ".pi/extensions/undeclared.js")]), /pi-resource/);
});

test("service validation can narrow an approved selection but cannot add or restore extensions", () => {
  const original = selectResources(fixture());
  const narrowed = restrictExtensions(original, []);
  assert.deepEqual(loaderOptions(narrowed).additionalExtensionPaths, []);
  assert.equal(original.resources.extensions.length, 1);
  assert.notEqual(narrowed.digest, original.digest);
  assert.throws(() => restrictExtensions(narrowed, ["selected"]), /pi-validation-extension-scope/);
  assert.throws(() => restrictExtensions(original, ["unselected"]), /pi-validation-extension-scope/);
  assert.throws(() => restrictExtensions({ ...original }, []), /pi-validation-extension-scope/);
});

test("selected missing paths and symlink escapes fail before factory execution", () => {
  const f = fixture();
  f.installed.extensions[0].path = "packages/missing.js";
  assert.throws(() => selectResources(f), /pi-resource/);
  const outside = f.put(f.cwd, "external.js");
  symlinkSync(outside, join(f.runtimeRoot, "escape.js"));
  f.installed.extensions[0].path = "escape.js";
  assert.throws(() => selectResources(f), /pi-resource/);
  f.installed.extensions[0].path = "../project/external.js";
  assert.throws(() => selectResources(f), /pi-resource/);
});

test("only explicitly declared project resources load; managed role replacement is forbidden", () => {
  const f = fixture();
  f.manifest.options.discovery.project_resources = true;
  f.put(f.cwd, ".pi/prompts/local.md");
  f.manifest.project_resources = [{ id: "local", kind: "prompts", path: ".pi/prompts/local.md" }];
  const result = selectResources(f);
  assert.equal(result.resources.prompts.length, 2);
  f.put(f.instanceRoot, "pi-home/agents/task-keeper-reader.md");
  f.manifest.resources.roles = ["pi-home/agents/task-keeper-reader.md"];
  f.manifest.resource_ids.roles = { "task-keeper-reader": "pi-home/agents/task-keeper-reader.md" };
  f.put(f.cwd, ".pi/agents/replacement.md");
  f.manifest.project_resources = [{ id: "replacement", kind: "roles", path: ".pi/agents/replacement.md", override: "task-keeper-reader" }];
  assert.throws(() => selectResources(f), /pi-resource-conflict/);
});

test("logical collisions and duplicate canonical paths fail; digest changes with content", () => {
  const f = fixture();
  const first = selectResources(f).digest;
  f.put(f.instanceRoot, "pi-home/prompts/review.md", "changed content");
  assert.notEqual(selectResources(f).digest, first);
  f.installed.prompts.push({ id: "review", capability_id: "selected", path: "packages/selected/index.js" });
  assert.throws(() => selectResources(f), /pi-resource-conflict/);
});

test("bootstrap loads no plugin factories and engine mismatch is fatal", () => {
  const f = fixture();
  f.manifest.bootstrap = true;
  assert.equal(selectResources(f).resources.extensions.length, 0);
  f.engine = "bun";
  assert.throws(() => selectResources(f), /pi-engine/);
});

test("CLI keeps literal argument boundaries and refuses native resource/model overrides", () => {
  assert.deepEqual(parseArguments(["--thinking", "high", "-p", "a b", "c"]), { print: true, thinking: "high", help: false, messages: ["a b", "c"] });
  assert.deepEqual(parseArguments(["--", "--model", "literal"]).messages, ["--model", "literal"]);
  for (const argv of [["-e", "npm:evil"], ["--extension=evil"], ["--model", "unselected"], ["--tools=all"], ["--mode", "rpc"], ["--agent-dir", "/tmp"], ["--thinking"]]) {
    assert.throws(() => parseArguments(argv), /pi-arguments/);
  }
});

test("a selected plugin absent from the installed resource manifest cannot silently disappear", () => {
  const f = fixture();
  f.manifest.plugins.push("missing-todo");
  assert.throws(() => selectResources(f), /pi-resource-selected-plugin-missing/);
});
