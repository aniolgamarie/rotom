import { test, assert, evidence } from "./recorded-test.ts";
import { join } from "node:path";
import { existsSync } from "node:fs";
import { runVerification, parseTestCounts } from "../src/verification/runner.ts";
import type { VerificationBinding } from "../src/config.ts";
import { isolatedDirectory } from "./helpers.ts";

function binding(program: string): VerificationBinding {
  return { executable: process.execPath, args: ["-e", program], environment: {}, timeoutMs: 5000, kind: "tests", parser: "json", minimumTests: 1 };
}

test("[P WFL-004 T44] real verifier distinguishes passing, zero, skipped, inconsistent and unknown tests", async (t) => {
  const cwd = isolatedDirectory(t), target = { cwd, jobId: "job", snapshot: "tree" };
  for (const [counts, expected] of [
    [{ tests: 2, passed: 2, failed: 0, skipped: 0 }, "passed"],
    [{ tests: 0, passed: 0, failed: 0, skipped: 0 }, "failed"],
    [{ tests: 2, passed: 0, failed: 0, skipped: 2 }, "failed"],
    [{ tests: 2, passed: 1, failed: 1, skipped: 0 }, "failed"],
    [{ tests: 2, passed: 1, failed: 0, skipped: 0 }, "unknown"],
  ] as const) {
    const check = binding(`console.log(${JSON.stringify(JSON.stringify(counts))})`);
    const result = await runVerification("tests", { tests: check }, target);
    for (const id of ["WFL-004", "T44"]) evidence(id, () => {
      assert.equal(result.status, expected); assert.equal(result.exitCode, 0); assert.equal(result.terminationConfirmed, true);
      assert.equal(result.terminationCoverage, "pid-namespace"); assert.equal(result.notSent, false);
      assert.deepEqual(JSON.parse(result.stdout), counts); assert.equal(result.checkId, "tests"); assert.equal(result.jobId, "job");
      assert.equal(result.reason, expected === "passed" ? "verified" : expected === "unknown" ? "test_count_unknown" : "required_tests_not_passed");
    });
  }
  const uncounted = await runVerification("tests", { tests: binding("console.log('Done')") }, target);
  for (const id of ["WFL-004", "T44"]) evidence(id, () => {
    assert.equal(uncounted.status, "unknown"); assert.equal(uncounted.counts, null); assert.equal(uncounted.exitCode, 0);
    assert.equal(uncounted.terminationConfirmed, true); assert.equal(uncounted.reason, "test_count_unknown");
  });
});

test("[P T46 T63] check argv is literal and binding changes invalidate its digest", async (t) => {
  const cwd = isolatedDirectory(t), target = { cwd, jobId: "job", snapshot: "tree" };
  const check = { ...binding("console.log(process.argv[1])"), kind: "build" as const, parser: "exit-code" as const };
  check.args.push("$(touch injected-file)");
  const result = await runVerification("build", { build: check }, target);
  assert.equal(result.status, "passed", JSON.stringify(result)); assert.equal(existsSync(join(cwd, "injected-file")), false);
  const changed = await runVerification("build", { build: { ...check, environment: { FIXTURE: "changed" } } }, target);
  assert.notEqual(changed.bindingDigest, result.bindingDigest); assert.notEqual(changed.environmentDigest, result.environmentDigest);
  await assert.rejects(runVerification("arbitrary", { build: check }, target));
});

test("timeout, abort and output truncation never produce a passing receipt", async (t) => {
  const cwd = isolatedDirectory(t), target = { cwd, jobId: "job", snapshot: "tree" };
  const slow = { ...binding("setInterval(()=>{},1000)"), timeoutMs: 100 };
  const timed = await runVerification("tests", { tests: slow }, target, { killGraceMs: 50 });
  assert.notEqual(timed.status, "passed"); assert.equal(timed.reason, "timeout");
  const loud = binding("console.log('x'.repeat(10000))");
  assert.equal((await runVerification("tests", { tests: loud }, target, { maxOutputBytes: 100 })).status, "unknown");
  const controller = new AbortController(); controller.abort();
  await assert.rejects(runVerification("tests", { tests: slow }, target, { signal: controller.signal }));
  assert.deepEqual(parseTestCounts("# tests 2\n# pass 2\n# fail 0\n# skipped 0\n", "tap"), { tests: 2, passed: 2, failed: 0, skipped: 0 });
  assert.equal(parseTestCounts("# tests 2\n# tests 3\n# pass 2\n# fail 0\n# skipped 0\n", "tap"), null);
});

test("bounded full output is not silently cut by the diagnostic redactor", async (t) => {
  const cwd = isolatedDirectory(t), target = { cwd, jobId: "job", snapshot: "tree" };
  const check = { ...binding("console.log('x'.repeat(5000)+'SECRET')"), kind: "build" as const, parser: "exit-code" as const };
  const result = await runVerification("build", { build: check }, target, { secrets: ["SECRET"] });
  assert.equal(result.status, "passed"); assert.equal(result.truncated, false);
  assert.ok(result.stdout.length > 5000); assert.equal(result.stdout.includes("SECRET"), false);
});

test("a lingering ordinary descendant cannot be accepted as a completed verifier", async (t) => {
  const cwd = isolatedDirectory(t), target = { cwd, jobId: "job", snapshot: "tree" };
  const program = "const {spawn}=require('node:child_process');const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});child.unref();";
  const check = { ...binding(program), kind: "build" as const, parser: "exit-code" as const };
  const result = await runVerification("build", { build: check }, target);
  assert.equal(result.status, "failed", JSON.stringify(result)); assert.equal(result.terminationConfirmed, true);
  assert.equal(result.reason, "unfinished_descendants_terminated"); assert.equal(result.terminationCoverage, "pid-namespace");
});
