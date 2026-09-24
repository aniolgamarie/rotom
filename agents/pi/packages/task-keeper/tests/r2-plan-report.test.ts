import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import type { TestContext } from "node:test";
import { isolatedDirectory } from "./helpers.ts";
import { textHash, type AcceptanceBundle } from "../src/contracts/acceptance-plan.ts";

const pkg = fileURLToPath(new URL("..", import.meta.url));
function fixture(t: TestContext, body = 'test("[V] reported witness",()=>assert.ok(true));') {
  const root = isolatedDirectory(t);
  for (const dir of ["scripts", "src/contracts", "tests", "docs/testing"]) mkdirSync(join(root, dir), { recursive: true });
  for (const file of ["scripts/check-plan.ts", "scripts/test-report.ts", "scripts/coverage-reporter.mjs", "scripts/source-lock.ts", "scripts/acceptance-plan.ts", "scripts/evidence-checkpoint.ts",
    "src/contracts/test-plan.ts", "src/contracts/acceptance-plan.ts", "src/contracts/primitives.ts", "tests/recorded-test.ts", "docs/testing/expanded-matrices.json"])
    cpSync(join(pkg, file), join(root, file));
  for (const name of ["plan", "plan-r2"]) cpSync(join(pkg, "tests", name), join(root, "tests", name), { recursive: true });
  writeFileSync(join(root, "package.json"), '{"type":"module"}');
  writeFileSync(join(root, "tests/case.test.ts"), 'import {test,assert,acceptance,observerArtifact,matrixCase} from "./recorded-test.ts";\n' + body);
  const bundlePath = join(root, "tests/plan-r2/bundle.json");
  const bundle = JSON.parse(readFileSync(bundlePath, "utf8")) as AcceptanceBundle;
  return { root, bundle, save: () => writeFileSync(bundlePath, JSON.stringify(bundle)),
    run: (script: string, args: string[] = []) => spawnSync(process.execPath, ["--experimental-strip-types", `scripts/${script}.ts`, ...args], {
      cwd: root, encoding: "utf8", timeout: 15000, env: { ...process.env, NODE_TEST_CONTEXT: undefined,
        TASK_KEEPER_TEST_RESULT_ROOT: join(root, "test-results"), TASK_KEEPER_TEST_RECORD_DIR: undefined },
    }), report: () => {
      const path = join(root, "test-results/latest.json"); if (!existsSync(path)) return null;
      const latest = JSON.parse(readFileSync(path, "utf8")); const file = join(root, "test-results", latest.report);
      return { file, value: JSON.parse(readFileSync(file, "utf8")) };
    } };
}
function witness(id: string, variant: string, facts: unknown, body: () => void) {
  acceptance(id, variant, { level: "V", observer: "actual-node-cli", predicate: `${id}.${variant} CLI contract`, artifact: observerArtifact(`${id}-${variant}`, facts) }, body);
}
function changeFile(bundle: AcceptanceBundle, name: string, body: string) { bundle.files[name] = body; bundle.hashes[name] = textHash(body); }

test("[V] R2 plan validates the current contract and rejects specific mapping drift", t => {
  const f = fixture(t), valid = f.run("check-plan");
  assert.equal(valid.status, 0, valid.stderr);
  const summary = JSON.parse(valid.stdout); assert.equal(summary.revision, "TK-R2"); assert.equal(summary.scenarios, 142); assert.equal(summary.variants, 300);
  const original = structuredClone(f.bundle);
  const rows = (name: string) => original.files[name].trimEnd().split(/\r?\n/);
  const mutations: Array<[string, (b: AcceptanceBundle) => void, RegExp]> = [
    ["missing-scenario", b => changeFile(b, "scenario-test-matrix.csv", rows("scenario-test-matrix.csv").slice(0, -1).join("\n")+"\n"), /PLAN_REVISION_INVENTORY_MISMATCH/],
    ["changed-when", b => { const key = Object.keys(b.files).find(k => k.startsWith("specs/"))!; changeFile(b,key,b.files[key].replace("**WHEN**", "**WHEN** changed")); }, /TEST_MAPPING_DRIFT/],
    ["unknown-AC", b => changeFile(b, "scenario-test-matrix.csv", b.files["scenario-test-matrix.csv"].replace("AC01", "AC99")), /UNKNOWN_ACCEPTANCE_REFERENCE/],
    ["missing-legacy", b => changeFile(b,"legacy-obligation-map.csv",rows("legacy-obligation-map.csv").slice(0,-1).join("\n")+"\n"),/LEGACY_MAPPING_MISSING/],
    ["duplicate-identity", b => { const r=rows("acceptance-cases.csv");changeFile(b,"acceptance-cases.csv",[...r,r[1]].join("\n")+"\n"); }, /DUPLICATE_ACCEPTANCE_ID/],
    ["history-hash", b => { b.legacy.files["proposal.md"] += "\nchanged history"; }, /PLAN_SOURCE_HASH_MISMATCH/],
  ];
  for (const [variant, mutate, expected] of mutations) {
    Object.assign(f.bundle, structuredClone(original)); mutate(f.bundle); f.save(); const result = f.run("check-plan");
    witness("AC31",variant,{valid:summary,code:result.status,stderr:result.stderr},()=>{ assert.equal(result.status,1);assert.match(result.stderr,expected); });
  }
});

const validBody = `test("[V] actual current report witness",()=>{const artifact=observerArtifact("actual-input",{observed:1});acceptance("AC32","wrong-source",{level:"V",observer:"fixture-file",predicate:"observed equals one",artifact},()=>assert.equal(1,1));});`;
test("[V] current report and checkpoint reject edited evidence and source without importing legacy credit", t => {
  const f=fixture(t,validBody), run=f.run("test-report"); assert.equal(run.status,0,run.stderr);
  const original=f.report()!; assert.ok(original); assert.equal(original.value.revision,"TK-R2");
  assert.deepEqual(original.value.currentCoverage.credited,["AC32.wrong-source"]); assert.equal(original.value.ready,false);
  const value=structuredClone(original.value);
  for(const variant of ["wrong-plan","wrong-name","wrong-layer","zero-assertion"]){
    const changed=structuredClone(value);
    if(variant==="wrong-plan")changed.planDigest="old-plan";
    if(variant==="wrong-name")changed.acceptanceEvidence[0].name="never executed";
    if(variant==="wrong-layer")changed.acceptanceEvidence[0].level="E";
    if(variant==="zero-assertion")changed.acceptanceEvidence[0].assertions=0;
    writeFileSync(original.file,JSON.stringify(changed));const rejected=f.run("evidence-checkpoint",[original.file]);
    witness("AC32",variant,{status:rejected.status,stderr:rejected.stderr},()=>{assert.equal(rejected.status,1);assert.match(rejected.stderr,/acceptance evidence mismatch/);});
  }
  writeFileSync(original.file,JSON.stringify(value));
  writeFileSync(join(f.root,"changed.ts"),"export const changed=true;");const stale=f.run("evidence-checkpoint",[original.file]);
  witness("AC32","wrong-source",{status:stale.status,stderr:stale.stderr},()=>{assert.equal(stale.status,1);assert.match(stale.stderr,/source\/run identity mismatch/);});
});

for(const variant of ["missing-artifact","zero-tests","skipped","failed-retry"] as const)test(`[V] current reporter preserves ${variant} as incomplete or failed`, t=>{
  const body=variant==="zero-tests"?"":variant==="skipped"?'test("[V] skipped",t=>{assert.ok(true);t.skip("unavailable");});':variant==="failed-retry"?'test("[V] failure",()=>assert.fail("original failure"));test("[V] later pass",()=>assert.ok(true));':validBody.replace('const artifact=observerArtifact("actual-input",{observed:1});','const artifact="missing.json";');
  const f=fixture(t,body), result=f.run("test-report"), report=f.report();
  witness("AC32",variant,{status:result.status,stderr:result.stderr,report:report?.value??null},()=>{
    if(variant!=="skipped")assert.notEqual(result.status,0);
    if(report)assert.equal(report.value.ready,false);
    if(variant==="missing-artifact")assert.match(result.stderr,/INVALID_ACCEPTANCE_ARTIFACT/);
    if(variant==="zero-tests")assert.match(result.stderr,/ZERO_DISCOVERED_OR_EXECUTED_TESTS/);
    if(variant==="failed-retry"){assert.equal(report!.value.failed,1);assert.equal(report!.value.passed,1);}
    if(variant==="skipped")assert.equal(report!.value.skipped,1);
  });
});

test("[V] current checkpoint publishes a verified partial run with matching plan and raw witnesses",t=>{
  const f=fixture(t,validBody);const run=f.run("test-report");assert.equal(run.status,0,run.stderr);
  const r=f.report()!, saved=f.run("evidence-checkpoint",[r.file]);assert.equal(saved.status,0,saved.stderr);
  const checkpoint=JSON.parse(readFileSync(join(f.root,"docs/testing/runtime-progress.json"),"utf8"));
  assert.equal(checkpoint.planDigest,r.value.planDigest);assert.equal(checkpoint.currentCoverage.missing.length,299);
  assert.equal(checkpoint.legacyRuntimeCreditImported,false);assert.equal(checkpoint.ready,false);
});
