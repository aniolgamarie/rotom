import { test, assert } from "./recorded-test.ts";
import { cpSync, mkdirSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { isolatedDirectory } from "./helpers.ts";

test("[V VAL-016] actual independent admission cases detect each removed guard and retain their legal control", { timeout: 20000 }, t => {
  const root = isolatedDirectory(t), pkg = join(root, "package"), source = fileURLToPath(new URL("..", import.meta.url));
  cpSync(source, pkg, { recursive: true, filter: path => !relative(source, path).split("/").some(part => ["node_modules", "test-results", "coverage", "docs"].includes(part)) });
  symlinkSync(join(source, "node_modules"), join(pkg, "node_modules"));
  const path = join(pkg, "src/reliability/eligibility.ts"), original = readFileSync(path, "utf8");
  const guards = original.split("\n").filter(line => line.trim().startsWith("if (") && line.includes("return "));
  assert.equal(guards.length, 9);
  const observations: Array<{guard:string;code:number|null;stdout:string;stderr:string}> = [];
  const run = (guard: string | null) => {
    writeFileSync(path, guard ? original.replace(guard, "") : original);
    const records = join(root, `records-${observations.length}`); mkdirSync(records);
    const result = spawnSync(process.execPath, ["--experimental-strip-types", "--test", "--test-name-pattern", "separate counterexample", "tests/cases-recovery-eligibility-u.test.ts"], {
      cwd: pkg, encoding: "utf8", timeout: 10000, env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_TEST_RECORD_DIR: records },
    });
    observations.push({ guard: guard?.trim() ?? "original", code: result.status, stdout: result.stdout, stderr: result.stderr });
    return result;
  };
  const baseline = run(null); assert.equal(baseline.status, 0, baseline.stdout + baseline.stderr);
  for (const guard of guards) {
    const result = run(guard);
    assert.equal(result.signal, null); assert.notEqual(result.status, 0, `guard was not detected: ${guard}`);
    assert.match(result.stdout + result.stderr, /AssertionError|TypeError/);
  }
  const restored = run(null); assert.equal(restored.status, 0, restored.stdout + restored.stderr);
  assert.equal(readFileSync(join(source, "src/reliability/eligibility.ts"), "utf8"), original);
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const target = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "admission-mutations"); mkdirSync(target, { recursive: true });
    writeFileSync(join(target, "observations.json"), JSON.stringify(observations, null, 2));
  }
});
