import assert from "node:assert/strict";
import { test } from "node:test";
import { parseTestCounts, evaluateVerification } from "../src/verification/runner.ts";

test("pytest checks require a single real count summary and cannot accept zero tests from exit zero", () => {
  assert.deepEqual(parseTestCounts("...\n2 passed, 1 skipped in 0.14s\n", "pytest"), { tests: 3, passed: 2, failed: 0, skipped: 1 });
  assert.equal(parseTestCounts("no tests ran in 0.10s\n", "pytest"), null);
  assert.equal(parseTestCounts("1 passed in 0.10s\n2 passed in 0.20s\n", "pytest"), null);
  const result = evaluateVerification({ kind: "tests", parser: "pytest", minimumTests: 1 }, {
    stdout: "no tests ran in 0.10s", truncated: false, timedOut: false, cancelled: false, spawnFailed: false, exitCode: 0,
    terminationConfirmed: true, admissionError: null, lingering: 0, launcherExitCode: 0, started: true, terminalObserved: true });
  assert.equal(result.status, "unknown");
  assert.equal(result.reason, "test_count_unknown");
});
