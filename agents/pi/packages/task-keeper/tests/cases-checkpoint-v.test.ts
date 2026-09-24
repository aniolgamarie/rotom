import { test, assert, evidence } from "./recorded-test.ts";
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";

function fixture(t: TestContext) {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("..", import.meta.url));
  for (const dir of ["scripts", "src/contracts", "tests", "docs/testing"]) mkdirSync(join(root, dir), { recursive: true });
  for (const file of ["scripts/test-report.ts", "scripts/coverage-reporter.mjs", "scripts/evidence-checkpoint.ts", "scripts/source-lock.ts", "scripts/acceptance-plan.ts", "src/contracts/acceptance-plan.ts", "src/contracts/primitives.ts",
    "src/contracts/test-plan.ts", "tests/recorded-test.ts", "docs/testing/expanded-matrices.json", "docs/testing/coverage-cases.csv"])
    cpSync(join(pkg, file), join(root, file));
  cpSync(join(pkg, "tests/plan"), join(root, "tests/plan"), { recursive: true });
  writeFileSync(join(root, "package.json"), '{"type":"module"}');
  writeFileSync(join(root, "tests/case.test.ts"), 'import {test,assert} from "./recorded-test.ts";test("[U T01] a single recorded witness",()=>assert.equal(1,1));');
  writeFileSync(join(root, "docs/testing/runtime-progress.json"), '{"oldCheckpoint":"preserve-for-audit"}');
  const run = (script: string, args: string[] = []) => spawnSync(process.execPath, ["--experimental-strip-types", `scripts/${script}.ts`, ...args], {
    cwd: root, encoding: "utf8", timeout: 10000,
    env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_TEST_RECORD_DIR: undefined, TASK_KEEPER_TEST_RESULT_ROOT: join(root, "test-results") },
  });
  const result = run("test-report", ["--legacy"]); assert.equal(result.status, 0, result.stderr);
  const latest = JSON.parse(readFileSync(join(root, "test-results/latest.json"), "utf8"));
  const reportPath = join(root, "test-results", latest.report), original = readFileSync(reportPath, "utf8"), report = JSON.parse(original);
  return { root, report, original, reportPath, checkpoint: () => run("evidence-checkpoint", [reportPath]) };
}

test("[V VAL-018] checkpoint derives exact current rows and missing set from raw execution; historical views remain auditable", t => {
  const f = fixture(t), result = f.checkpoint();
  evidence("VAL-018", () => {
    assert.equal(result.status, 0, result.stderr);
    const current = JSON.parse(readFileSync(join(f.root, "docs/testing/runtime-progress.json"), "utf8"));
    assert.equal(current.runId, f.report.runId); assert.equal(current.lockDigest, f.report.lockDigest);
    assert.equal(current.tests, 1); assert.equal(current.assertions, 1); assert.equal(current.missingCount, 706);
    assert.deepEqual(current.releaseCoverage.missing, f.report.releaseCoverage.missing);
    assert.equal(current.expandedCoverage.missing.length, 436); assert.equal(current.ready, false);
    const rows = readFileSync(join(f.root, "docs/testing/runtime-case-evidence.csv"), "utf8");
    assert.match(rows, /T01:U/); assert.match(rows, /single recorded witness/); assert.ok(rows.includes(f.report.lockDigest));
    assert.equal(readFileSync(f.reportPath, "utf8"), f.original);
    assert.equal(readFileSync(join(f.root, `test-results/checkpoint-before-${f.report.runId}/runtime-progress.json`), "utf8"), '{"oldCheckpoint":"preserve-for-audit"}');
    assert.notEqual(f.checkpoint().status, 0); // Never overwrite the audit backup on a repeat invocation.
  });
});

for (const mutation of ["source", "assertions", "name", "layer", "hash", "missing", "raw-record", "ready", "native-tap"] as const)
test(`[V VAL-018] checkpoint refuses ${mutation} drift before changing any current evidence`, t => {
  const f = fixture(t);
  if (mutation === "source") writeFileSync(join(f.root, "changed-source.ts"), "export const changed = true;");
  else if (mutation === "native-tap") {
    const tap = join(f.root, "test-results", f.report.runId, "tests.tap");
    writeFileSync(tap, readFileSync(tap, "utf8").replace("# pass 1", "# pass 2"));
  }
  else if (mutation === "ready") f.report.ready = true;
  else if (mutation === "raw-record") f.report.executions[0].assertions++;
  else {
    if (mutation === "assertions") f.report.evidence[0].assertions++;
    if (mutation === "name") f.report.evidence[0].name = "[U T01] never executed";
    if (mutation === "layer") f.report.evidence[0].level = "A";
    if (mutation === "hash") f.report.evidence[0].lockDigest = "stale";
    if (mutation === "missing") f.report.releaseCoverage.missing = [];
  }
  if (mutation !== "source") writeFileSync(f.reportPath, JSON.stringify(f.report));
  const result = f.checkpoint();
  evidence("VAL-018", () => {
    assert.equal(result.status, 1); assert.match(result.stderr, /source\/run identity mismatch|raw execution mismatch|evidence .* mismatch|coverage\/plan mismatch|readiness\/summary mismatch|native TAP summary mismatch/);
    assert.equal(readFileSync(join(f.root, "docs/testing/runtime-progress.json"), "utf8"), '{"oldCheckpoint":"preserve-for-audit"}');
    assert.equal(existsSync(join(f.root, "docs/testing/runtime-case-evidence.csv")), false);
    assert.equal(existsSync(join(f.root, `test-results/checkpoint-before-${f.report.runId}`)), false);
  });
});
