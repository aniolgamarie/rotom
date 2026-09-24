import { test, assert } from "./recorded-test.ts";
import { cpSync, mkdirSync, writeFileSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { isolatedDirectory } from "./helpers.ts";

test("[V VAL-018] the actual focused launcher rejects a filter that executed no recorded tests", { timeout: 15000 }, t => {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("..", import.meta.url));
  for (const dir of ["scripts", "tests", "node_modules"]) mkdirSync(join(root, dir));
  for (const file of ["scripts/test-isolated.mjs", "scripts/isolation-child.mjs", "tests/recorded-test.ts"]) cpSync(join(pkg, file), join(root, file));
  writeFileSync(join(root, "package.json"), '{"type":"module"}');
  writeFileSync(join(root, "tests/case.test.ts"), 'import {test,assert} from "./recorded-test.ts";test("positive witness",()=>assert.equal(1,1));');
  const run = (pattern: string) => spawnSync(process.execPath, [join(root, "scripts/test-isolated.mjs"), "--test-name-pattern", pattern, "tests/case.test.ts"],
    { cwd: root, encoding: "utf8", timeout: 10000, env: { ...process.env, NODE_TEST_CONTEXT: undefined } });
  const empty = run("does-not-match"); assert.notEqual(empty.status, 0); assert.match(empty.stderr, /ZERO_EXECUTED_TESTS/);
  const valid = run("positive witness"); assert.equal(valid.status, 0, valid.stderr);
  const summaries = readdirSync(join(root, "test-results")).filter(name => name.startsWith("focused-"))
    .map(name => JSON.parse(readFileSync(join(root, "test-results", name, "summary.json"), "utf8")));
  assert.ok(summaries.some(s => s.executed === 0 && s.reason === "ZERO_EXECUTED_TESTS"));
  assert.ok(summaries.some(s => s.executed === 1 && s.assertedPassed === 1 && s.exitCode === 0));
});
