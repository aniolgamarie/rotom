import { test, assert } from "./recorded-test.ts";
import { cpSync, mkdirSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { isolatedDirectory } from "./helpers.ts";

test("[V] the focused launcher rejects every missing target before any selected test runs", { timeout: 20000 }, t => {
  const root = isolatedDirectory(t), pkg = join(root, "package-source"), source = fileURLToPath(new URL("..", import.meta.url));
  for (const dir of ["scripts", "tests", "node_modules"]) mkdirSync(join(pkg, dir), { recursive: true });
  for (const file of ["scripts/test-isolated.mjs", "scripts/isolation-child.mjs", "tests/recorded-test.ts"]) cpSync(join(source, file), join(pkg, file));
  writeFileSync(join(pkg, "package.json"), '{"type":"module"}');
  writeFileSync(join(pkg, "tests/present.test.ts"), 'import {test,assert} from "./recorded-test.ts";test("selected witness",()=>{console.log("SOURCE:"+process.argv[1]);assert.equal(1,1);});');
  const run = (...args: string[]) => spawnSync(process.execPath, [join(pkg, "scripts/test-isolated.mjs"), ...args], { cwd: pkg, encoding: "utf8", timeout: 10000,
    env: { ...process.env, NODE_TEST_CONTEXT: undefined } });
  const missing = run("tests/present.test.ts", "tests/missing.test.ts");
  assert.notEqual(missing.status, 0); assert.match(missing.stderr, /MISSING_TEST_TARGET/); assert.equal(missing.stdout.includes("selected witness"), false);
  const valid = run("--test-name-pattern", "selected witness", "tests/present.test.ts"); assert.equal(valid.status, 0, valid.stderr); assert.ok(valid.stdout.includes("selected witness"));
  writeFileSync(join(pkg, "tests/filtered.test.ts"), 'import {test,assert} from "./recorded-test.ts";test("selected witness",()=>assert.equal(1,1));test("unselected failure",()=>assert.fail("FILTER_WAS_IGNORED"));');
  for (const args of [
    ["tests/filtered.test.ts", "--test-name-pattern", "selected witness"],
    ["--test-name-pattern", "selected witness", "tests/filtered.test.ts"],
    ["tests/filtered.test.ts", "--test-name-pattern=selected witness"],
  ]) {
    const filtered = run(...args); assert.equal(filtered.status, 0, filtered.stdout + filtered.stderr);
    assert.equal(filtered.stdout.includes("FILTER_WAS_IGNORED"), false);
  }
  const absolute = run(join(pkg, "tests/present.test.ts")); assert.equal(absolute.status, 0, absolute.stderr);
  assert.match(absolute.stdout, /SOURCE:.*\/package\/tests\/present.test.ts/); assert.equal(absolute.stdout.includes(`SOURCE:${join(pkg, "tests/present.test.ts")}`), false);
  const outside = join(root, "outside.test.ts"); writeFileSync(outside, "throw new Error('outside source executed')");
  const escaped = run("tests/present.test.ts", outside); assert.notEqual(escaped.status, 0); assert.match(escaped.stderr, /TEST_TARGET_OUTSIDE_PACKAGE/);
  assert.equal(escaped.stdout.includes("selected witness"), false);
  symlinkSync(outside, join(pkg, "tests/escape.test.ts"));
  const symlink = run("tests/present.test.ts", "tests/escape.test.ts"); assert.notEqual(symlink.status, 0); assert.match(symlink.stderr, /TEST_TARGET_OUTSIDE_PACKAGE/);
  for (const mode of ["--report", "--typecheck", "--plan"]) {
    const ignored = run(mode, "tests/present.test.ts"); assert.notEqual(ignored.status, 0); assert.match(ignored.stderr, /UNSUPPORTED_LAUNCH_ARGUMENT/);
    assert.equal(ignored.stdout.includes("selected witness"), false);
  }
});
