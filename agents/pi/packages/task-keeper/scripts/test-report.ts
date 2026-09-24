import { spawn } from "node:child_process";
import { readFileSync, existsSync, readdirSync, mkdirSync, writeFileSync, appendFileSync } from "node:fs";
import { join, relative, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { digest } from "../src/contracts/primitives.ts";
import { sourceLock } from "./source-lock.ts";
import { readAcceptancePlan, recordedAcceptance } from "./acceptance-plan.ts";
import { acceptanceCoverage } from "../src/contracts/acceptance-plan.ts";
import { parseCsv, planObligations, coverageReport, type TestEvidence, type TestExecution, verifyScenarioMapping, validateDiscovery, attributedAssertions, matrixCoverage, type ExpandedMatrix, type MatrixEvidence } from "../src/contracts/test-plan.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const runId = new Date().toISOString().replace(/[:.]/g, "-");
const resultRoot = process.env.TASK_KEEPER_TEST_RESULT_ROOT ?? join(root, "test-results");
const directory = join(resultRoot, runId), records = join(directory, "records");
mkdirSync(records, { recursive: true, mode: 0o700 });
const files = readdirSync(join(root, "tests")).filter((name) => name.endsWith(".test.ts")).sort();
const lockDigest = sourceLock(root);
const currentPlan = process.argv.includes("--legacy") ? null : readAcceptancePlan(root).plan;
let log = "";
const tapPath = join(directory, "tests.tap"), startedAt = Date.now();
writeFileSync(tapPath, "", { mode: 0o600 });
function reportProgress() {
  let completed = 0, failed = 0, discovered = 0;
  for (const name of readdirSync(records)) {
    if (!name.endsWith(".jsonl")) continue;
    for (const line of readFileSync(join(records, name), "utf8").split("\n")) {
      if (!line) continue;
      // Workers append independently; a partial final line is retried at the next tick.
      let record; try { record = JSON.parse(line); } catch { continue; }
      if (name.endsWith(".discovery.jsonl")) discovered++;
      else { completed++; if (record.status === "failed") failed++; }
    }
  }
  console.error(JSON.stringify({ event: "test-progress", runId, elapsedSeconds: Math.floor((Date.now() - startedAt) / 1000),
    completed, discovered, failed, artifact: tapPath }));
}
const progressTimer = setInterval(reportProgress, 30_000);
progressTimer.unref();
const child = spawn(process.execPath, ["--experimental-strip-types", "--experimental-test-coverage", "--test", "--test-concurrency=8", "--test-reporter=./scripts/coverage-reporter.mjs", ...files.map((file) => `tests/${file}`)], {
  cwd: root, env: { ...process.env, TASK_KEEPER_TEST_RECORD_DIR: records, TASK_KEEPER_CODE_COVERAGE_FILE: join(directory,"code-coverage.json") }, stdio: ["ignore", "pipe", "pipe"],
});
for (const stream of [child.stdout, child.stderr]) stream.on("data", (chunk) => { const data = chunk.toString(); log += data; appendFileSync(tapPath, data); });
const exitCode = await new Promise<number>((resolve) => { child.on("error", () => resolve(1)); child.on("close", (code) => resolve(code ?? 1)); });
clearInterval(progressTimer);
const executions = readdirSync(records).filter(file => !file.endsWith(".discovery.jsonl")).flatMap((file) => readFileSync(join(records, file), "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line))) as TestExecution[];
const discovered = readdirSync(records).filter(file => file.endsWith(".discovery.jsonl")).flatMap(file => readFileSync(join(records, file), "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)));
const scenarios = parseCsv(readFileSync(join(root, "tests/plan/scenario-test-matrix.csv"), "utf8"));
const faults = parseCsv(readFileSync(join(root, "tests/plan/fault-traceability.csv"), "utf8"));
const obligations = planObligations(scenarios, faults);
const specs = Object.fromEntries(readdirSync(join(root, "tests/plan/specs")).map(name => [`specs/${name}/spec.md`, readFileSync(join(root, "tests/plan/specs", name, "spec.md"), "utf8")]));
verifyScenarioMapping(specs, scenarios);
const discovery = validateDiscovery(discovered, executions, obligations);
const evidence: TestEvidence[] = [];
const matrixEvidence: MatrixEvidence[] = [];
const rejectedEvidence: Array<{ file: string; name: string; level: string; reason: string }> = [];
const expandedPlan = JSON.parse(readFileSync(join(root, "docs/testing/expanded-matrices.json"), "utf8")) as ExpandedMatrix[];
const levels: Record<string, string[]> = {
  "process.test.ts": ["P"], "pi-rpc.test.ts": ["A", "E"], "subagents.test.ts": ["A", "P"], "workflows.test.ts": ["E"],
  "recovery.test.ts": ["U", "S"], "scheduler.test.ts": ["U", "S"], "http-transport.test.ts": ["A"],
  "verification.test.ts": ["U", "P"], "workspace.test.ts": ["P"],
};
for (const execution of executions) {
  // Only explicitly named obligations are credited. An ID at one level does not certify the other required levels.
  const ids = execution.name.match(/\b(?:T\d{2}|TK\d{2}|(?:CFG|EXE|EVD|REC|SCH|WFL|RTB|VAL)-\d{3})\b/g) ?? [];
  if (ids.some((id) => !obligations.some((obligation) => obligation.id === id))) throw new Error(`Unknown obligation in ${execution.name}`);
  const explicitLevels = /^\[([^\]]+)\]/.exec(execution.name)?.[1].match(/\b(?:U|S|A|P|E|L|V)\b/g);
  const declaredLevels = explicitLevels ?? levels[basename(execution.file)] ?? ["U"];
  if (declaredLevels.includes("L")) rejectedEvidence.push({ file: relative(root, execution.file), name: execution.name, level: "L", reason: "LIVE_EVIDENCE_UNAVAILABLE_IN_OFFLINE_REPORT" });
  const actualLevels = declaredLevels.filter(level => level !== "L");
  for (const [key, assertions] of Object.entries(execution.matrixAssertions ?? {})) {
    if (key.startsWith("r2-acceptance:")) continue;
    const [matrix, variant, extra] = key.split(":");
    const declared = expandedPlan.find(item => item.id === matrix);
    if (extra || !declared?.cases.some(item => item.id === variant)) throw new Error(`Unknown matrix case: ${key}`);
    for (const level of actualLevels.filter(level => declared.layers.includes(level))) matrixEvidence.push({ matrix, variant, level,
      status: execution.status, assertions, name: execution.name, file: relative(root, execution.file), artifact: `${runId}/tests.tap`, lockDigest });
  }
  for (const id of new Set(ids)) for (const level of actualLevels) {
    if (!obligations.find((obligation) => obligation.id === id)?.levels.includes(level)) continue;
    evidence.push({ id, level, status: execution.status, assertions: attributedAssertions(execution, id), name: execution.name,
      file: relative(root, execution.file), artifact: `${runId}/tests.tap`, lockDigest });
  }
}
const coverage = coverageReport(obligations, evidence, lockDigest);
const expandedCoverage = matrixCoverage(expandedPlan, matrixEvidence, lockDigest);
// The change explicitly delivers P0–P3. Preserve future online IDs in the full matrix.
const deferredOnlineIds = ["T66", "T68", "T69"];
const releaseCoverage = coverageReport(obligations.filter(item => !deferredOnlineIds.includes(item.id)),
  evidence.filter(item => !deferredOnlineIds.includes(item.id)), lockDigest);
function emitMatrix(rows: Record<string, string>[], name: string) {
  const header = Object.keys(rows[0]);
  const output = rows.map((row) => {
    const id = row.scenario_id ?? row.id, actual = evidence.filter((item) => item.id === id);
    const missing = coverage.missing.filter((item) => item.startsWith(`${id}:`));
    const credited = actual.filter(item => item.status === "passed" && item.assertions > 0 && item.lockDigest === lockDigest);
    return { ...row, status: actual.some((item) => item.status === "failed") ? "failed" : missing.length === 0 ? "passed-required-layers"
      : credited.length ? "partial-coverage" : deferredOnlineIds.includes(id) ? "P4-online-deferred" : "pending",
      test_file: [...new Set(actual.map((item) => item.file))].join(";"), test_name: [...new Set(actual.map((item) => item.name))].join(";"),
      result_artifact: actual.length ? `${runId}/report.json` : "" };
  });
  const cell = (value: string) => `"${value.replace(/"/g, '""')}"`;
  writeFileSync(join(directory, name), [header, ...output.map((row) => header.map((key) => (row as Record<string, string>)[key] ?? ""))].map((row) => row.map(cell).join(",")).join("\n") + "\n", { mode: 0o600 });
}
emitMatrix(scenarios, "scenario-test-matrix.csv"); emitMatrix(faults, "fault-traceability.csv");
const nativeSummary = { tests: Number(/^# tests (\d+)$/m.exec(log)?.[1] ?? 0), passed: Number(/^# pass (\d+)$/m.exec(log)?.[1] ?? 0),
  failed: Number(/^# fail (\d+)$/m.exec(log)?.[1] ?? 0), cancelled: Number(/^# cancelled (\d+)$/m.exec(log)?.[1] ?? 0), skipped: Number(/^# skipped (\d+)$/m.exec(log)?.[1] ?? 0) };
const recordingComplete = nativeSummary.tests === discovered.length;
const invalidRun = exitCode !== 0 || !recordingComplete || !executions.length || executions.some(execution => execution.assertions === 0) || rejectedEvidence.length > 0;
const acceptanceEvidence = currentPlan ? recordedAcceptance(currentPlan, executions, root, directory, lockDigest) : [];
const currentCoverage = currentPlan ? acceptanceCoverage(currentPlan, acceptanceEvidence, lockDigest) : null;
const ready = !invalidRun && discovery.notExecuted.length === 0 && (currentCoverage ? currentCoverage.ready : releaseCoverage.ready && expandedCoverage.ready);
const commandExitCode = exitCode || (invalidRun || (process.argv.includes("--release") && !ready) ? 1 : 0);
const codeCoverage=existsSync(join(directory,"code-coverage.json"))?JSON.parse(readFileSync(join(directory,"code-coverage.json"),"utf8")):null;
const report = { runId, lockDigest, node: process.version, revision: currentPlan?.revision ?? "legacy-P0-P3", planDigest: currentPlan?.digest ?? null, acceptanceEvidence, currentCoverage,
  codeCoverage, readinessBasis:"passing tests and mapped acceptance records; semantic review is separate",
  exitCode: commandExitCode, nativeExitCode: exitCode, rejectedEvidence, tests: nativeSummary.tests, recordedExecutions: executions.length, recordingComplete,
  assertions: executions.reduce((sum, execution) => sum + execution.assertions, 0), nativeSummary,
  passed: nativeSummary.passed, failed: nativeSummary.failed + nativeSummary.cancelled, skipped: nativeSummary.skipped,
  coverage, expandedCoverage, matrixEvidence, expandedPlanDigest: digest(expandedPlan), releaseScope: "P0-P3", releaseCoverage, deferredOnlineIds, deferredOnlineBehavior: ["T75 online utility remains deferred; its offline report guard is required"], evidence, executions, discovery, ready,
  limitations: ["Loopback fixtures are not live provider-service certification", "Unmapped and unexecuted scenario obligations remain pending", "Code coverage excludes test/cut copies and describes observed test workers only; native Pi subprocess coverage is not collected; scenario status is derived from AC mappings", "Failed runs remain in their original run directories"] };
writeFileSync(join(directory, "report.json"), JSON.stringify(report, null, 2) + "\n", { mode: 0o600 });
writeFileSync(join(resultRoot, "latest.json"), JSON.stringify({ runId, report: `${runId}/report.json` }) + "\n", { mode: 0o600 });
console.log(JSON.stringify({ runId, revision: report.revision, tests: report.tests, passed: report.passed, failed: report.failed, assertions: report.assertions,
  releaseReady: report.ready, currentMissing: currentCoverage?.missing.length ?? null, legacyMissingObligationLevels: releaseCoverage.missing.length, legacyMatrixMissing: expandedCoverage.missing.length }));
process.exitCode = commandExitCode;
