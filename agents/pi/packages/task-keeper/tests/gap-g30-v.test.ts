import { test, assert, evidence } from "./recorded-test.ts";
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";
const pkg = fileURLToPath(new URL("..", import.meta.url));
function fixture(t: TestContext, body: string, mutate?: (root: string) => void) {
  const root = isolatedDirectory(t);
  for (const dir of ["scripts", "tests", "src/contracts", "docs/testing"]) mkdirSync(join(root, dir), { recursive: true });
  for (const path of ["scripts/test-report.ts", "scripts/coverage-reporter.mjs", "scripts/source-lock.ts", "scripts/acceptance-plan.ts", "src/contracts/acceptance-plan.ts", "tests/recorded-test.ts", "src/contracts/test-plan.ts", "src/contracts/primitives.ts"]) cpSync(join(pkg, path), join(root, path));
  cpSync(join(pkg, "docs/testing/expanded-matrices.json"), join(root, "docs/testing/expanded-matrices.json"));
  cpSync(join(pkg, "tests/plan"), join(root, "tests/plan"), { recursive: true });
  writeFileSync(join(root, "package.json"), '{"type":"module"}');
  writeFileSync(join(root, "tests/case.test.ts"), `import { test, assert, evidence, matrixCase } from "./recorded-test.ts";\n${body}`);
  mutate?.(root);
  const child = spawnSync(process.execPath, ["--experimental-strip-types", "scripts/test-report.ts", "--legacy"], {
    cwd: root, env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_TEST_RESULT_ROOT: join(root, "results") }, encoding: "utf8", timeout: 15000,
  });
  const parentRecords = process.env.TASK_KEEPER_TEST_RECORD_DIR;
  if (parentRecords) {
    const target = join(dirname(parentRecords), "validation-fixtures", basename(root)); mkdirSync(target, { recursive: true, mode: 0o700 });
    writeFileSync(join(target, "input-case.ts"), body, { mode: 0o600 });
    writeFileSync(join(target, "output.log"), child.stdout + child.stderr, { mode: 0o600 });
    if (existsSync(join(root, "results"))) cpSync(join(root, "results"), join(target, "results"), { recursive: true });
  }
  const latest = join(root, "results/latest.json");
  const report = existsSync(latest) ? JSON.parse(readFileSync(join(root, "results", JSON.parse(readFileSync(latest, "utf8")).report), "utf8")) : null;
  const tap = report ? readFileSync(join(root, "results", report.runId, "tests.tap"), "utf8") : "";
  return { code: child.status, output: child.stdout + child.stderr, report, tap };
}
test("[V VAL-013] actual reporter refuses aggregate multi-ID assertions and records only attributed obligations", (t) => {
  const { code, report, output } = fixture(t, 'test("[U VAL-013 VAL-018] witness", () => { evidence("VAL-013", () => assert.equal(1,1)); assert.equal(2,2); });');
  assert.equal(code, 0, output); assert.equal(report.tests, 1);
  assert.equal(report.evidence.find((e: {id: string}) => e.id === "VAL-013").assertions, 1);
  assert.equal(report.evidence.find((e: {id: string}) => e.id === "VAL-018").assertions, 0);
  assert.equal(report.coverage.missing.includes("VAL-013:U"), false);
  assert.equal(report.coverage.missing.includes("VAL-018:U"), true);
  assert.equal(report.discovery.unattributed.length, 1);
  assert.equal(report.ready, false);
  assert.equal(report.codeCoverage.complete,false);assert.equal(report.codeCoverage.scope,"observed-test-workers");assert.equal(report.codeCoverage.nativePiSubprocessCoverage,"not-collected");assert.ok(report.codeCoverage.files.every((file:{path:string})=>file.path==="index.ts"||file.path.startsWith("src/")));
});

test("[V VAL-002 VAL-019] a successful structural-only run reports every runtime fault as missing and code coverage unavailable", t => {
  const result = fixture(t, `import {readFileSync} from 'node:fs';
import {parseCsv,planObligations} from '../src/contracts/test-plan.ts';
test('structural plan only',()=>{
  const plan=planObligations(parseCsv(readFileSync('tests/plan/scenario-test-matrix.csv','utf8')),
    parseCsv(readFileSync('tests/plan/fault-traceability.csv','utf8')));
  assert.ok(plan.length>100);assert.ok(plan.some(item=>item.id==='T01'));
});`);
  for (const id of ["VAL-002", "VAL-019"]) evidence(id, () => {
    assert.equal(result.code, 0, result.output); assert.equal(result.report.passed, 1);
    assert.equal(result.report.failed, 0); assert.equal(result.report.evidence.length, 0);
    assert.equal(result.report.coverage.evidenceRecords, 0); assert.equal(result.report.coverage.codeCoverage, "unavailable");
    assert.equal(result.report.ready, false); assert.equal(result.report.releaseCoverage.ready, false);
    assert.equal(result.report.expandedCoverage.credited.length, 0);
    for (let n = 1; n <= 88; n++) assert.ok(result.report.coverage.missing.some((key: string) => key.startsWith(`T${String(n).padStart(2, "0")}:`)));
  });
  const runtime = fixture(t, 'test("[U T01] single executed contract",()=>assert.equal(1,1));');
  for (const id of ["VAL-002", "VAL-019"]) evidence(id, () => {
    assert.equal(runtime.code, 0); assert.equal(runtime.report.coverage.missing.includes("T01:U"), false);
    assert.ok(runtime.report.coverage.missing.includes("T01:A")); assert.equal(runtime.report.ready, false);
    assert.equal(runtime.report.coverage.codeCoverage, "unavailable");
  });
});
test("[V VAL-018] actual discovery rejects zero tests and preserves skipped and failed runs", (t) => {
  const zero = fixture(t, ''); assert.notEqual(zero.code, 0); assert.match(zero.output, /ZERO_DISCOVERED_OR_EXECUTED_TESTS/);
  const skipped = fixture(t, 'test("[U VAL-018] ordinary", () => assert.ok(true)); test("[V VAL-018] skipped", {skip:true}, () => assert.fail());');
  assert.ok(skipped.report, skipped.output); assert.equal(skipped.report.nativeSummary.skipped, 1); assert.equal(skipped.report.discovery.notExecuted.length, 1);
  assert.equal(skipped.report.coverage.missing.includes("VAL-018:V"), true); assert.equal(skipped.report.ready, false);
  const dynamic = fixture(t, 'test("[V VAL-018] dynamic", t => { assert.ok(true); t.skip("missing binding"); });');
  assert.equal(dynamic.report.executions[0].status, "skipped"); assert.equal(dynamic.report.coverage.missing.includes("VAL-018:V"), true);
  const failed = fixture(t, 'test("[V VAL-018] broken", () => assert.fail("real failure"));');
  assert.notEqual(failed.code, 0); assert.equal(failed.report.failed, 1); assert.equal(failed.report.ready, false);
});
test("[V VAL-012] report command rejects source scenario drift before certifying a run", (t) => {
  const result = fixture(t, 'test("[U VAL-012] valid", () => assert.ok(true));', root => {
    const path = join(root, "tests/plan/specs/task-keeper-config/spec.md");
    writeFileSync(path, readFileSync(path, "utf8").replace("**THEN**", "**THEN** changed"));
  });
  assert.notEqual(result.code, 0); assert.equal(result.report, null); assert.match(result.output, /ContractError/);
});

test("[V VAL-018] a failing cleanup is recorded as a failed execution, not a passing body", t => {
  const result = fixture(t, 'test("[V VAL-018] hook failure", t => { assert.ok(true); t.after(() => { throw new Error("cleanup failed"); }); });');
  assert.notEqual(result.code, 0); assert.ok(result.report, result.output);
  assert.equal(result.report.nativeSummary.failed, 1); assert.equal(result.report.failed, 1); assert.equal(result.report.passed, 0);
  assert.equal(result.report.executions[0].status, "failed"); assert.equal(result.report.ready, false);
});

test("[V VAL-003] P0-P3 release excludes only deferred online obligations while retaining every original ID", t => {
  const result = fixture(t, 'test("[U VAL-003] report-input fixture", () => assert.ok(true));');
  assert.equal(result.code, 0, result.output); assert.equal(result.report.releaseScope, "P0-P3");
  assert.deepEqual(result.report.deferredOnlineIds, ["T66", "T68", "T69"]);
  for (const id of ["T66", "T68", "T69"]) for (const layer of ["U", "V"]) {
    assert.ok(result.report.coverage.missing.includes(`${id}:${layer}`)); assert.equal(result.report.releaseCoverage.missing.includes(`${id}:${layer}`), false);
  }
  assert.ok(result.report.releaseCoverage.missing.includes("T75:V")); assert.equal(result.report.ready, false);
  assert.equal(result.report.coverage.missing.length - result.report.releaseCoverage.missing.length, 6);
});

test("[V VAL-017] actual reporter attributes only the executed matrix case and rejects invented variants", t => {
  const result = fixture(t, 'test("[P E] lifecycle witness", () => matrixCase("lifecycle-preservation", "restart.unknown", () => assert.ok(true)));');
  assert.equal(result.code, 0, result.output);
  assert.deepEqual(result.report.expandedCoverage.credited, ["lifecycle-preservation:restart.unknown:P", "lifecycle-preservation:restart.unknown:E"]);
  assert.ok(result.report.expandedCoverage.missing.includes("lifecycle-preservation:restart.not-sent:P"));
  assert.equal(result.report.expandedCoverage.ready, false); assert.equal(result.report.ready, false);
  const wrong = fixture(t, 'test("[P] invented", () => matrixCase("lifecycle-preservation", "invented", () => assert.ok(true)));');
  assert.notEqual(wrong.code, 0); assert.match(wrong.output, /Unknown matrix case/);
  const empty = fixture(t, 'test("[P] empty variant", () => { matrixCase("lifecycle-preservation", "restart.unknown", () => {}); assert.ok(true); });');
  assert.equal(empty.code, 0); assert.deepEqual(empty.report.expandedCoverage.credited, []);
});

test("[V VAL-018] coverage stays in recorded workers and malformed subprocess coverage still fails validation", t => {
  const run = (restore: boolean) => fixture(t, "", root => {
    const child = "const fs=require('node:fs'),path=require('node:path');if(process.env.NODE_V8_COVERAGE)fs.writeFileSync(path.join(process.env.NODE_V8_COVERAGE,`coverage-999999-${Date.now()}-0.json`),'{');";
    writeFileSync(join(root, "tests/case.test.ts"), `import {spawnSync} from 'node:child_process';
const inherited=process.env.NODE_V8_COVERAGE;
const {test,assert}=await import('./recorded-test.ts');
test('[U VAL-018] real coverage worker',()=>{
  assert.ok(inherited);
  ${restore ? "process.env.NODE_V8_COVERAGE=inherited;" : "assert.equal(process.env.NODE_V8_COVERAGE,undefined);"}
  const child=spawnSync(process.execPath,['-e',${JSON.stringify(child)}],{encoding:'utf8'});
  assert.equal(child.status,0);
});`);
  });
  const valid = run(false); assert.equal(valid.code, 0, valid.output); assert.equal(valid.report.passed, 1);
  const broken = run(true); assert.notEqual(broken.code, 0); assert.match(broken.tap, /Could not report code coverage/);
  assert.equal(broken.report.passed, 1); assert.equal(broken.report.exitCode, 1); assert.equal(broken.report.ready, false);
});


test("[V VAL-004] an offline reporter cannot certify live acceptance from a test label", t => {
  const forged = fixture(t, 'test("[L VAL-007] claimed live acceptance", () => assert.ok(true));');
  assert.notEqual(forged.code, 0); assert.ok(forged.report, forged.output); assert.notEqual(forged.report.exitCode, 0);
  assert.ok(forged.report.coverage.missing.includes("VAL-007:L")); assert.equal(forged.report.ready, false);
  assert.ok(forged.report.rejectedEvidence.some((item: {level:string;reason:string}) => item.level === "L" && item.reason === "LIVE_EVIDENCE_UNAVAILABLE_IN_OFFLINE_REPORT"));
  const offline = fixture(t, 'test("[V VAL-004] valid offline witness", () => assert.ok(true));');
  assert.equal(offline.code, 0, offline.output); assert.deepEqual(offline.report.rejectedEvidence, []);
  assert.ok(offline.report.coverage.missing.includes("VAL-007:L"));
});


test("[V VAL-018] long reports emit progress before completion and preserve streamed TAP", t => {
  const result = fixture(t, 'test("[V VAL-018] delayed witness", async () => { await new Promise(resolve => setTimeout(resolve, 150)); assert.ok(true); console.error("late-worker-output"); });', root => {
    const path = join(root, "scripts/test-report.ts");
    writeFileSync(path, readFileSync(path, "utf8").replace("setInterval(reportProgress, 30_000)", "setInterval(reportProgress, 20)"));
  });
  assert.equal(result.code, 0, result.output);
  const progress = result.output.split("\n").filter(line => line.startsWith('{"event":"test-progress"')).map(line => JSON.parse(line));
  assert.ok(progress.length > 0); assert.ok(progress.some(item => item.completed === 0));
  assert.ok(progress.every(item => item.runId === result.report.runId && item.failed === 0 && item.elapsedSeconds >= 0));
  assert.match(result.tap, /late-worker-output/); assert.match(result.tap, /# pass 1/);
  assert.equal(result.report.nativeExitCode, 0); assert.equal(result.report.recordingComplete, true);
});


test("[V VAL-018] a native test timeout cannot leave passed evidence after an earlier assertion", t => {
  const result = fixture(t, 'test("[V VAL-018] timed-out witness", {timeout:30}, async t => { assert.ok(true); const keepAlive=setInterval(()=>{},10); t.after(()=>clearInterval(keepAlive)); await new Promise(()=>{}); });');
  assert.notEqual(result.code,0); assert.ok(result.report,result.output); assert.equal(result.report.nativeSummary.cancelled,1);
  assert.equal(result.report.executions[0].status,"failed"); assert.ok(result.report.executions[0].assertions>0);
  assert.equal(result.report.coverage.missing.includes("VAL-018:V"),true); assert.equal(result.report.ready,false);
});
