import { test, assert } from "./recorded-test.ts";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";
import { isolatedDirectory } from "./helpers.ts";
import { evaluationStarts } from "./fixtures/evaluation.ts";
import type { EvaluationRun } from "../src/evidence/evaluation.ts";
for (const id of ["VAL-009", "VAL-010", "T73", "T74", "T75"]) test(`[V ${id}] TC-${id}-V actual evaluation report rejects biased or unsupported outcome claims`, t => {
  const root = isolatedDirectory(t), path = join(root, "evaluation-input.json"), script = fileURLToPath(new URL("../scripts/evaluation-report.ts", import.meta.url));
  const run = (runs: EvaluationRun[], startedRunIds = runs.map(r => r.id)) => {
    writeFileSync(path, JSON.stringify({ runs, startedRunIds }));
    return spawnSync(process.execPath, ["--experimental-strip-types", script, path], { encoding: "utf8", timeout: 10000 });
  };
  const starts = evaluationStarts(), good = run(starts); assert.equal(good.status, 0, good.stderr);
  const report = JSON.parse(good.stdout); assert.equal(report.totalStarted, 10); assert.equal(report.groups[0].successPerStarted, 0.4);
  assert.equal(report.groups[0].knownCost, 6); assert.equal(report.groups[0].unknownCostRuns, 2);
  const filtered = run(starts.filter(r => r.accepted), starts.map(r => r.id)); assert.notEqual(filtered.status, 0); assert.match(filtered.stderr, /EVALUATION_START_INVENTORY_MISMATCH/);
  const leaked = run([starts[0], { ...starts[1], split: "development", family: "renamed", artifact: "renamed.json" }]); assert.notEqual(leaked.status, 0); assert.match(leaked.stderr, /HOLDOUT_FAMILY_LEAKAGE/);
  const shadow = { ...starts[0], executionMode: "shadow" as const, accepted: null };
  const unexecuted = run([shadow]); assert.equal(unexecuted.status, 0); assert.equal(JSON.parse(unexecuted.stdout).efficacyClaim, "not_established");
  const falseSuccess = run([{ ...shadow, accepted: true }]); assert.notEqual(falseSuccess.status, 0); assert.match(falseSuccess.stderr, /CONFLICTING_EVALUATION_OUTCOME/);
});
