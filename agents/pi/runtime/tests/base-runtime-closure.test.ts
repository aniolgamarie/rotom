// 声明闭包的源码导入证据；不调用launcher，不证明生产转换或原生SDK加载。
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, realpathSync } from "node:fs";
import { isBuiltin, registerHooks } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const declarations = JSON.parse(readFileSync(resolve(root, "agents/pi/dependencies-modern.json"), "utf8"))
  .profiles["pi-base"].runtime_files.filter(row => row.source.endsWith(".ts"));
const sources = new Set(declarations.map(row => realpathSync(resolve(root, row.source))));
const entry = realpathSync(resolve(root, "agents/pi/runtime/official-launch.ts"));
const worker = realpathSync(resolve(root, "agents/pi/runtime/regex-worker.ts"));

async function importClosure(allowed, targetEntry = entry) {
  const generation = randomUUID(), observed = new Set(), denied = [];
  const hook = registerHooks({ resolve(specifier, context, next) {
    const parent = context.parentURL?.startsWith("file:") ? fileURLToPath(context.parentURL) : undefined;
    if (!parent || !sources.has(parent)) return next(specifier, context);
    if (isBuiltin(specifier)) return next(specifier, context);
    if (!specifier.startsWith("./") && !specifier.startsWith("../")) {
      denied.push(specifier);
      throw new Error("BASE_RUNTIME_EXTERNAL_IMPORT_REJECTED");
    }
    const target = fileURLToPath(new URL(specifier, context.parentURL));
    if (!allowed.has(target)) {
      denied.push(target);
      throw new Error("BASE_RUNTIME_UNDECLARED_IMPORT");
    }
    const resolved = next(specifier, context);
    if (!resolved.url.startsWith("file:") || fileURLToPath(resolved.url) !== target) throw new Error("BASE_RUNTIME_IMPORT_REDIRECTED");
    observed.add(target);
    // 每次把唯一世代传播到整个相对导入图，不让旧缓存掩盖删项。
    const url = new URL(resolved.url); url.searchParams.set("baseClosure", generation);
    return { ...resolved, url: url.href };
  } });
  try {
    assert(allowed.has(targetEntry));
    observed.add(targetEntry);
    const url = pathToFileURL(targetEntry); url.searchParams.set("baseClosure", generation);
    const module = await import(url.href);
    return { module, observed, denied };
  } catch (error) {
    error.denied = [...denied];
    throw error;
  } finally {
    hook.deregister();
  }
}

test("Base's declared self-owned entry imports without third-party SDK or UI", async () => {
  assert.equal(declarations.length, 35);
  assert.equal(sources.size, 35);
  assert.match(process.argv[1], /mock-entry\.mjs$/);
  const { module, observed, denied } = await importClosure(sources);
  assert.equal(typeof module.main, "function");
  assert.equal(typeof module.launch, "function");
  assert.deepEqual(denied, []);
  assert.equal(observed.size, 34);
  assert.deepEqual(new Set([...sources].filter(path => !observed.has(path))), new Set([worker]));
});

test("removing a real transitive source fails despite a previously imported complete graph", async t => {
  await importClosure(sources);
  const allowed = new Set(sources);
  const missing = realpathSync(resolve(root, "agents/pi/runtime/private-operation-input.ts"));
  allowed.delete(missing);
  await assert.rejects(importClosure(allowed), error => {
    assert.equal(error.message, "BASE_RUNTIME_UNDECLARED_IMPORT");
    assert.deepEqual(error.denied, [missing]);
    t.diagnostic("Negative oracle: missing private-operation-input.ts rejected with BASE_RUNTIME_UNDECLARED_IMPORT");
    return true;
  });
  // 失败的临时hook必须卸载；另一个新世代完整图仍能导入。
  assert.equal((await importClosure(sources)).observed.size, 34);
});

test("regex worker URL resource is explicitly declared, without importing its worker entry", () => {
  const row = declarations.find(row => resolve(root, row.source) === worker);
  assert(row);
  assert.equal(row.path, "runtime/regex-worker.mjs");
  assert.equal(row.transform, "ts-module");
  const search = readFileSync(resolve(root, "agents/pi/runtime/regex-search.ts"), "utf8");
  assert.match(search, /new URL\("\.\/regex-worker\.ts", import\.meta\.url\)/);
  assert(sources.has(fileURLToPath(new URL("./regex-worker.ts", pathToFileURL(resolve(root, "agents/pi/runtime/regex-search.ts"))))));
});

const shellEntry = realpathSync(resolve(root, "agents/pi/runtime/official-shell-tool.ts"));
const shellExecutor = realpathSync(resolve(root, "agents/pi/runtime/shell-operation-executor.ts"));
test("Shell wrapper and executor are exact Base declarations with only self-owned imports", async () => {
  for (const name of ["official-shell-tool", "shell-operation-executor"]) {
    assert.deepEqual(declarations.find(row => row.source === "agents/pi/runtime/" + name + ".ts"),
      { source: "agents/pi/runtime/" + name + ".ts", path: "runtime/" + name + ".mjs", transform: "ts-module" });
  }
  const { module, observed, denied } = await importClosure(sources, shellEntry);
  assert.equal(typeof module.createOfficialShellTool, "function");
  assert(observed.has(shellExecutor));
  assert.deepEqual(denied, []);
  assert.equal([...observed].some(path => /node_modules|full-agent|agent-manager/.test(path)), false);
});
for (const missingName of ["shell-operation-executor", "private-files"]) test("Shell transitive closure cannot borrow missing " + missingName + " from checkout", async () => {
  await importClosure(sources, shellEntry);
  const missing = realpathSync(resolve(root, "agents/pi/runtime/" + missingName + ".ts")), allowed = new Set(sources);
  allowed.delete(missing);
  await assert.rejects(importClosure(allowed, shellEntry), error => {
    assert.equal(error.message, "BASE_RUNTIME_UNDECLARED_IMPORT"); assert.deepEqual(error.denied, [missing]); return true;
  });
  assert.equal(typeof (await importClosure(sources, shellEntry)).module.createOfficialShellTool, "function");
});
