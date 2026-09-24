import { readFileSync, readdirSync, writeFileSync, renameSync, existsSync, mkdirSync, cpSync } from "node:fs";
import { join, dirname, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { sourceLock } from "./source-lock.ts";
import { readAcceptancePlan, recordedAcceptance } from "./acceptance-plan.ts";
import { acceptanceCoverage } from "../src/contracts/acceptance-plan.ts";
import { digest, ContractError } from "../src/contracts/primitives.ts";
import { parseCsv, planObligations, coverageReport, attributedAssertions, matrixCoverage, validateDiscovery, testIds,
  type TestEvidence, type MatrixEvidence, type TestExecution, type ExpandedMatrix } from "../src/contracts/test-plan.ts";

const root = fileURLToPath(new URL("..", import.meta.url)), docs = join(root, "docs/testing");
const reportPath = resolve(root, process.argv[2] ?? "");
if (process.argv.length !== 3 || dirname(reportPath) !== join(root, "test-results", basename(dirname(reportPath))))
  throw new ContractError("CHECKPOINT_REPORT_PATH_REQUIRED");
const report = JSON.parse(readFileSync(reportPath, "utf8"));
const fail = (message: string): never => { throw new ContractError("INVALID_CHECKPOINT", message); };
if (basename(dirname(reportPath)) !== report.runId || sourceLock(root) !== report.lockDigest) fail("source/run identity mismatch");
if (report.exitCode !== 0 || report.nativeExitCode !== 0 || !report.recordingComplete
  || report.nativeSummary.failed || report.nativeSummary.cancelled || report.nativeSummary.skipped) fail("full passing unskipped run required");
const records = join(dirname(reportPath), "records");
const readRecords = (discovery: boolean) => readdirSync(records).filter(file => file.endsWith(".jsonl") && file.endsWith(".discovery.jsonl") === discovery)
  .flatMap(file => readFileSync(join(records, file), "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)));
const executions: TestExecution[] = readRecords(false), discovered = readRecords(true);
const ordered = (rows: unknown[]) => rows.map(row => digest(row)).sort();
if (digest(ordered(executions)) !== digest(ordered(report.executions)) || executions.length !== report.tests
  || executions.some(row => row.status !== "passed" || row.assertions <= 0)
  || executions.reduce((sum, row) => sum + row.assertions, 0) !== report.assertions) fail("raw execution mismatch");
const scenarios = parseCsv(readFileSync(join(root, "tests/plan/scenario-test-matrix.csv"), "utf8"));
const faults = parseCsv(readFileSync(join(root, "tests/plan/fault-traceability.csv"), "utf8"));
const plan = planObligations(scenarios, faults);
const discovery = validateDiscovery(discovered, executions, plan);
if (discovery.notExecuted.length || digest(discovery) !== digest(report.discovery)) fail("discovery mismatch");
if (report.revision === "TK-R2") {
  const { plan: current } = readAcceptancePlan(root);
  const actual = recordedAcceptance(current, executions, root, dirname(reportPath), report.lockDigest);
  const coverage = acceptanceCoverage(current, actual, report.lockDigest);
  if (report.planDigest !== current.digest || digest(actual) !== digest(report.acceptanceEvidence)
    || digest(coverage) !== digest(report.currentCoverage) || report.ready !== coverage.ready) fail("current acceptance evidence mismatch");
  if(report.codeCoverage && digest(JSON.parse(readFileSync(join(dirname(reportPath),"code-coverage.json"),"utf8")))!==digest(report.codeCoverage))fail("code coverage artifact mismatch");
  const tap = readFileSync(join(dirname(reportPath), "tests.tap"), "utf8");
  for (const [label, key] of [["tests", "tests"], ["pass", "passed"], ["fail", "failed"], ["cancelled", "cancelled"], ["skipped", "skipped"]])
    if (Number(new RegExp(`^# ${label} (\\d+)$`, "m").exec(tap)?.[1] ?? -1) !== report.nativeSummary[key]) fail("native TAP summary mismatch");
  if (report.passed !== executions.length || report.failed || report.skipped) fail("native summary mismatch");
  const archive = join(root, "test-results", `checkpoint-before-${report.runId}`);
  if (existsSync(archive)) fail("checkpoint already applied"); mkdirSync(archive);
  const progress = join(docs, "runtime-progress.json");
  if (existsSync(progress)) cpSync(progress, join(archive, "runtime-progress.json"));
  const result = { revision: current.revision, runId: report.runId, report: `test-results/${report.runId}/report.json`,
    lockDigest: report.lockDigest, planDigest: current.digest, tests: report.tests, passed: report.passed, assertions: report.assertions,
    currentCoverage: coverage, acceptanceEvidence: actual, codeCoverage:report.codeCoverage??null, readinessBasis:report.readinessBasis??null, ready: report.ready, legacyRuntimeCreditImported: false };
  writeFileSync(progress + ".next", JSON.stringify(result, null, 2) + "\n"); renameSync(progress + ".next", progress);
  console.log(JSON.stringify({ revision: current.revision, runId: report.runId, evidence: actual.length, missing: coverage.missing.length }));
  process.exit(0);
}
const evidence: TestEvidence[] = report.evidence, matrices: MatrixEvidence[] = report.matrixEvidence;
const levels: Record<string, string[]> = {
  "process.test.ts": ["P"], "pi-rpc.test.ts": ["A", "E"], "subagents.test.ts": ["A", "P"], "workflows.test.ts": ["E"],
  "recovery.test.ts": ["U", "S"], "scheduler.test.ts": ["U", "S"], "http-transport.test.ts": ["A"],
  "verification.test.ts": ["U", "P"], "workspace.test.ts": ["P"],
};
for (const row of [...evidence, ...matrices]) {
  const execution = executions.find(item => item.file.endsWith(`/${row.file}`) && item.name === row.name);
  if (!execution) throw new ContractError("INVALID_CHECKPOINT", "evidence execution mismatch");
  const declared = /^\[([^\]]+)\]/.exec(row.name)?.[1].match(/\b(?:U|S|A|P|E|L|V)\b/g) ?? levels[basename(row.file)] ?? ["U"];
  if (row.lockDigest !== report.lockDigest || row.artifact !== `${report.runId}/tests.tap`
    || row.status !== execution.status || !declared.includes(row.level) || row.level === "L") fail("evidence identity/layer mismatch");
  if ("id" in row && !testIds(row.name).includes(row.id)) fail("evidence obligation mismatch");
  const count = "id" in row ? attributedAssertions(execution, row.id) : execution.matrixAssertions?.[`${row.matrix}:${row.variant}`];
  if (count !== row.assertions) fail("evidence assertion mismatch");
}
const expanded: ExpandedMatrix[] = JSON.parse(readFileSync(join(docs, "expanded-matrices.json"), "utf8"));
const coverage = coverageReport(plan, evidence, report.lockDigest);
const deferred = ["T66", "T68", "T69"];
const releaseCoverage = coverageReport(plan.filter(row => !deferred.includes(row.id)), evidence.filter(row => !deferred.includes(row.id)), report.lockDigest);
const expandedCoverage = matrixCoverage(expanded, matrices, report.lockDigest);
for (const [actual, expected] of [[coverage, report.coverage], [releaseCoverage, report.releaseCoverage], [expandedCoverage, report.expandedCoverage], [digest(expanded), report.expandedPlanDigest]])
  if (digest(actual) !== digest(expected)) fail("coverage/plan mismatch");
if (!existsSync(join(dirname(reportPath), "tests.tap"))) fail("TAP missing");
const tap = readFileSync(join(dirname(reportPath), "tests.tap"), "utf8");
for (const [label, key] of [["tests", "tests"], ["pass", "passed"], ["fail", "failed"], ["cancelled", "cancelled"], ["skipped", "skipped"]]) {
  const actual = Number(new RegExp(`^# ${label} (\\d+)$`, "m").exec(tap)?.[1] ?? -1);
  if (actual !== report.nativeSummary[key]) fail("native TAP summary mismatch");
}
if (report.nativeSummary.tests !== executions.length || report.passed !== executions.length || report.failed !== 0 || report.skipped !== 0
  || report.ready !== (releaseCoverage.ready && expandedCoverage.ready)) fail("readiness/summary mismatch");

const csv = (rows: Record<string, unknown>[], header = Object.keys(rows[0])) => [header, ...rows.map(row => header.map(key => row[key] ?? ""))]
  .map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n") + "\n";
const outputs = new Map<string, string>();
outputs.set("runtime-case-evidence.csv", csv(evidence.map(row => ({ obligation: `${row.id}:${row.level}`, test_file: row.file, test_name: row.name,
  assertions: row.assertions, status: row.status, artifact: `test-results/${row.artifact}`, runtime_lock: row.lockDigest,
  full_variant_audit: "pending-domain-recipe-review" })), ["obligation", "test_file", "test_name", "assertions", "status", "artifact", "runtime_lock", "full_variant_audit"]));
outputs.set("runtime-matrix-evidence.csv", csv(matrices.map(row => ({ ...row })), ["matrix", "variant", "level", "status", "assertions", "file", "name", "artifact", "lockDigest"]));
const cases = parseCsv(readFileSync(join(docs, "coverage-cases.csv"), "utf8"));
const gaps = releaseCoverage.missing.map(key => {
  const row = cases.find(item => item.obligation === key); if (!row) fail(`missing design ${key}`);
  return { ...row, current_runtime_run: report.runId, current_runtime_evidence: "missing" };
});
outputs.set("runtime-gap-cases.csv", csv(gaps, [...Object.keys(cases[0]), "current_runtime_run", "current_runtime_evidence"].filter((value, index, all) => all.indexOf(value) === index)));
for (const [file, missing, key] of [["closure-obligations.csv", releaseCoverage.missing, "obligation"], ["closure-matrices.csv", expandedCoverage.missing, "matrix_key"]] as const) {
  const path = join(docs, file); if (!existsSync(path)) continue;
  const rows = parseCsv(readFileSync(path, "utf8"));
  outputs.set(file, csv(rows.map(row => ({ ...row, current_run: report.runId,
    current_runtime_evidence: missing.includes(row[key]) ? "missing" : "minimum_present" }))));
}
outputs.set("runtime-progress.json", JSON.stringify({ runId: report.runId, report: `test-results/${report.runId}/report.json`, lockDigest: report.lockDigest,
  tests: report.tests, passed: report.passed, failed: report.failed, skipped: report.skipped, assertions: report.assertions,
  coverage, releaseScope: "P0-P3", releaseCoverage, expandedCoverage, expandedPlanDigest: report.expandedPlanDigest,
  missingCount: releaseCoverage.missing.length, ready: report.ready, deferredOnlineIds: deferred,
  fullVariantAudit: "pending-domain-recipe-review; minimum evidence is not full scenario acceptance",
  liveQwen: "pending explicit acceptance binding and request ceiling; offline report guards do not establish Q3",
  derivation: "validated against raw discovery/execution records and current package source; historical reports unchanged" }, null, 2) + "\n");
// Retain every previous checkpoint before replacing derived views. No historical run or design row is rewritten.
const archive = join(root, "test-results", `checkpoint-before-${report.runId}`);
if (existsSync(archive)) fail("checkpoint already applied; refusing to replace its audit backup");
mkdirSync(archive);
for (const [file] of outputs) if (existsSync(join(docs, file))) cpSync(join(docs, file), join(archive, file));
for (const [file, content] of outputs) writeFileSync(join(docs, `.${file}.next`), content);
for (const [file] of outputs) renameSync(join(docs, `.${file}.next`), join(docs, file));
console.log(JSON.stringify({ runId: report.runId, lockDigest: report.lockDigest, evidence: evidence.length, matrixEvidence: matrices.length,
  missing: releaseCoverage.missing.length, matrixMissing: expandedCoverage.missing.length, auditBackup: archive }));
