import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mayTransformHistory } from "../../packages/runtime-ui/capability-policy.mjs";
import { pluginSettings } from "../../packages/runtime-ui/plugin-settings.mjs";

const key = Symbol.for("agentcfg.pi.runtime.v1");
function context(t, value) {
  const previous = globalThis[key]; globalThis[key] = value;
  t.after(() => { if (previous === undefined) delete globalThis[key]; else globalThis[key] = previous; });
}
const manager = options => ({ owner: { role: "manager" }, manifest: { plugins: ["pi-todo"], options: { todo: options } } });
const fixed = (code, exitCode) => error => error.message === code && error.code === code && error.exitCode === exitCode
  && error[Symbol.for("agentcfg.pi.protocol-error.v1")] === true;

test("selected manager receives independent JSON clone without global mutation", t => {
  const value = { locale: "zh-CN", panel: { width: 20 }, items: ["one"] }, runtime = manager(value);
  context(t, runtime);
  const copy = pluginSettings("pi-todo", "todo");
  assert.deepEqual(copy, value); assert.notEqual(copy, value); assert.notEqual(copy.panel, value.panel);
  copy.panel.width = 99; copy.items.push("two");
  assert.deepEqual(pluginSettings("pi-todo", "todo"), value); assert.equal(globalThis[key], runtime);
});

test("missing/null selected settings preserve empty-object native default", t => {
  const runtime = manager(undefined); context(t, runtime);
  assert.deepEqual(pluginSettings("pi-todo", "todo"), {});
  runtime.manifest.options.todo = null;
  assert.deepEqual(pluginSettings("pi-todo", "todo"), {});
});

for (const runtime of [undefined, {}, { owner: { role: "worker" } }, { owner: { role: "delegate" } },
  { owner: { role: "manager" }, manifest: { plugins: [], options: {} } },
  { owner: { role: "manager" }, manifest: { plugins: "pi-todo", options: {} } }]) {
  test("unselected or nonmanager access has fixed capability error", t => {
    context(t, runtime); assert.throws(() => pluginSettings("pi-todo", "todo"), fixed("CAPABILITY_NOT_SELECTED", 5));
  });
}
for (const value of [false, 0, "synthetic-private-sentinel", [], new Date(), { invalid: undefined }, { invalid: Infinity }]) {
  test("invalid selected configuration has fixed error without data", t => {
    context(t, manager(value));
    const code = value instanceof Date || value && typeof value === "object" && !Array.isArray(value) ? "PROTOCOL_INVALID" : "PLUGIN_CONFIG_INVALID";
    assert.throws(() => pluginSettings("pi-todo", "todo"), error => fixed(code, 2)(error) && !error.message.includes("synthetic-private-sentinel"));
  });
}

test("history only transforms for manager outside scoped managed request", () => {
  assert.equal(mayTransformHistory(undefined), false);
  assert.equal(mayTransformHistory({ owner: { role: "worker" } }), false);
  assert.equal(mayTransformHistory({ owner: { role: "manager" } }), true);
  assert.equal(mayTransformHistory({ owner: { role: "manager" }, managedRequestScope: { getStore: () => undefined } }), true);
  assert.equal(mayTransformHistory({ owner: { role: "manager" }, managedRequestScope: { getStore: () => ({ selected: true }) } }), false);
});

test("package has exactly two dependency-free public exports and owned notice", () => {
  const url = new URL("../../packages/runtime-ui/", import.meta.url);
  const manifest = JSON.parse(readFileSync(new URL("package.json", url), "utf8"));
  assert.equal(manifest.name, "@agentcfg/pi-runtime"); assert.equal(manifest.version, "2.0.0");
  assert.equal(manifest.private, true); assert.equal(manifest.type, "module"); assert.equal(manifest.license, "UNLICENSED");
  assert.deepEqual(Object.keys(manifest.exports).sort(), ["./capability-policy", "./plugin-settings"]);
  for (const field of ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "scripts"]) assert.equal(manifest[field], undefined);
  assert.deepEqual(manifest.exports["./capability-policy"], { types: "./capability-policy.d.ts", import: "./capability-policy.mjs" });
  assert.deepEqual(manifest.exports["./plugin-settings"], { types: "./plugin-settings.d.ts", import: "./plugin-settings.mjs" });
  assert.match(readFileSync(new URL("NOTICE", url), "utf8"), /仓库自有/);
});

test("existing selected consumers import only the supported public function names", () => {
  const loop = readFileSync(new URL("../../packages/loop-guard/index.ts", import.meta.url), "utf8");
  const todo = readFileSync(new URL("../../packages/todo-vendor/config.ts", import.meta.url), "utf8");
  assert.match(loop, /import\s*\{\s*mayTransformHistory\s*\}\s*from\s*["']@agentcfg\/pi-runtime\/capability-policy["']/);
  assert.match(todo, /import\s*\{\s*pluginSettings\s*\}\s*from\s*["']@agentcfg\/pi-runtime\/plugin-settings["']/);
});
