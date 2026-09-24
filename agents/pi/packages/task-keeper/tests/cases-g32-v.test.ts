import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { cpSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, basename } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { TestContext } from "node:test";
import type { RecoveryAcceptanceInput } from "../src/evidence/recovery-acceptance.ts";
import { isolatedDirectory } from "./helpers.ts";

const identity = { bindingDigest: "synthetic-binding", runtimeDigest: "synthetic-runtime", profileDigest: "synthetic-profile" };
function input(): RecoveryAcceptanceInput {
  const request = { ...identity, sessionId: "session", continuationKey: "same-task", artifact: "observer.json" };
  return { runId: "synthetic-report-oracle", expected: identity,
    binding: { ...identity, family: "qwen", requestCeiling: 3 }, controlledFaultsPassed: true,
    observations: [
      { ...request, requestId: "injected", origin: "injected", sentAt: 10, endedAt: 11, notBefore: 20, outcome: "rate-limited" },
      { ...request, requestId: "resumed", origin: "service-origin", sentAt: 20, endedAt: 30, notBefore: 0, outcome: "completed" },
    ], effects: [{ id: "write-once", requestId: "resumed", artifact: "observer.json" }],
    terminal: { sessionId: "session", continuationKey: "same-task", outcome: "completed", artifact: "observer.json" } };
}
function report(t: TestContext, value: RecoveryAcceptanceInput, prepare?: (root: string) => void) {
  const root = isolatedDirectory(t);
  writeFileSync(join(root, "input.json"), JSON.stringify(value));
  // Explicitly synthetic inputs test the reporter, never live-service behavior.
  writeFileSync(join(root, "observer.json"), JSON.stringify({ synthetic: true, input: value }));
  prepare?.(root);
  const child = spawnSync(process.execPath, ["--experimental-strip-types", fileURLToPath(new URL("../scripts/recovery-report.ts", import.meta.url)), join(root, "input.json")],
    { encoding: "utf8", timeout: 5000, env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_TEST_RECORD_DIR: undefined } });
  const output = child.stdout.trim().startsWith("{") ? JSON.parse(child.stdout) : null;
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const target = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-report-oracles", basename(root));
    mkdirSync(target, { recursive: true }); cpSync(root, target, { recursive: true });
    writeFileSync(join(target, "stdout.json"), child.stdout); writeFileSync(join(target, "stderr.log"), child.stderr);
    writeFileSync(join(target, "exit.json"), JSON.stringify({ code: child.status, signal: child.signal }));
  }
  return { code: child.status, output, error: child.stderr };
}

test("[V VAL-005] actual recovery report keeps missing bindings and failed live service unqualified despite passing controlled faults", t => {
  evidence("VAL-005", () => {
    const valid = report(t, input()); assert.equal(valid.code, 0, valid.error); assert.equal(valid.output.recoveryQualified, true);
    const missing = input(); missing.binding = null;
    const absent = report(t, missing); assert.equal(absent.code, 1); assert.equal(absent.output.recoveryQualified, false);
    assert.ok(absent.output.reasons.includes("LIVE_BINDING_MISSING")); assert.equal(absent.output.certificationKey, null);
    const failed = input(); failed.observations[1].outcome = "failed"; failed.terminal!.outcome = "failed";
    const failure = report(t, failed); assert.equal(failure.code, 1); assert.equal(failure.output.availabilityPassed, false);
    assert.ok(failure.output.reasons.includes("LIVE_SERVICE_NOT_COMPLETED")); assert.equal(failure.output.observations[1].outcome, "failed");
    assert.equal(failure.output.certificationKey, null);
  });
});

test("[V VAL-006 VAL-007] actual report distinguishes smoke, injected recovery and service-origin facts for the exact profile", t => {
  evidence("VAL-006", () => {
    const smoke = input(); smoke.observations.shift();
    const result = report(t, smoke); assert.equal(result.code, 1); assert.equal(result.output.availabilityPassed, true);
    assert.equal(result.output.recoveryQualified, false); assert.ok(result.output.reasons.includes("RECOVERY_NOT_EXERCISED"));
  });
  evidence("VAL-007", () => {
    const valid = report(t, input()); assert.equal(valid.code, 0, valid.error); assert.equal(valid.output.recoveryQualified, true);
    assert.deepEqual(valid.output.origins, { injected: ["injected"], "service-origin": ["resumed"], loopback: [] });
    assert.deepEqual(valid.output.scope, identity); assert.equal(valid.output.requests, 2); assert.equal(valid.output.sideEffects, 1);
    assert.equal(valid.output.observations[1].sentAt, 20); assert.equal(valid.output.observations[0].notBefore, 20);
    assert.equal(valid.output.terminal.continuationKey, "same-task");
    const mutations: Array<[string, (value: RecoveryAcceptanceInput) => void]> = [
      ["BINDING_CERTIFICATION_STALE", value => { value.binding!.runtimeDigest = "upgraded"; }],
      ["OBSERVED_IDENTITY_MISMATCH", value => { value.observations[1].profileDigest = "another"; }],
      ["REQUEST_CEILING_EXCEEDED", value => { value.binding!.requestCeiling = 1; }],
      ["RECOVERY_BEFORE_NOT_BEFORE", value => { value.observations[1].sentAt = 19; }],
      ["CONTINUATION_IDENTITY_CHANGED", value => { value.observations[1].continuationKey = "replayed-task"; }],
      ["DUPLICATE_SIDE_EFFECT", value => { value.effects.push({ ...value.effects[0] }); }],
      ["LOOPBACK_IS_NOT_LIVE_ACCEPTANCE", value => { value.observations[1].origin = "loopback"; }],
      ["TASK_NOT_COMPLETED", value => { value.terminal!.outcome = "unknown"; }],
      ["UNRESOLVED_REQUEST_OUTCOME", value => { value.observations[1].outcome = "unknown"; }],
    ];
    for (const [reason, mutate] of mutations) {
      const value = input(); mutate(value); const invalid = report(t, value);
      assert.equal(invalid.code, 1, invalid.error); assert.equal(invalid.output.recoveryQualified, false);
      assert.ok(invalid.output.reasons.includes(reason), reason); assert.equal(invalid.output.certificationKey, null);
    }
    const missing = input(); missing.observations[1].artifact = "absent.json";
    const invalid = report(t, missing); assert.equal(invalid.code, 1); assert.equal(invalid.output, null);
  });
});


test("[V] service reporting accepts provider-neutral bindings while retaining live evidence limits",t=>{
  for(const family of ["independent-provider","same-model-other-provider","qwen"]){
    const value=input();value.binding!.family=family;const result=report(t,value);
    if(family==="qwen"){assert.equal(result.code,0,result.error);continue;}
    const variant=family==="independent-provider"?"non-Qwen-valid":"same-model-other-provider";
    // This is reporter validation with synthetic evidence, not a live-service measurement.
    acceptance("AC36",variant,{level:"V",observer:"actual-report-cli-synthetic-input",predicate:"brand does not participate in qualification",artifact:observerArtifact(`report-${family}`,{input:value,result})},()=>{
      assert.equal(result.code,0,result.error);assert.equal(result.output.recoveryQualified,true);assert.equal(result.output.reasons.length,0);
      assert.ok(result.output.limitations.some((line:string)=>line.includes("do not certify any live provider")));
    });
  }
  for(const [variant,change,reason] of [
    ["live-absent",(value:RecoveryAcceptanceInput)=>{value.binding=null;},"LIVE_BINDING_MISSING"],
    ["smoke-only",(value:RecoveryAcceptanceInput)=>{value.observations.shift();},"RECOVERY_NOT_EXERCISED"],
    ["live-failure",(value:RecoveryAcceptanceInput)=>{value.observations[1].outcome="failed";},"LIVE_SERVICE_NOT_COMPLETED"],
    ["profile-stale",(value:RecoveryAcceptanceInput)=>{value.binding!.profileDigest="changed";},"BINDING_CERTIFICATION_STALE"],
  ] as const){const value=input();change(value);const result=report(t,value);
    acceptance("AC36",variant,{level:"V",observer:"actual-report-cli-synthetic-input",predicate:reason,artifact:observerArtifact(`report-${variant}`,{input:value,result})},()=>{
      assert.equal(result.code,1);assert.equal(result.output.recoveryQualified,false);assert.ok(result.output.reasons.includes(reason));assert.equal(result.output.certificationKey,null);
    });
  }
});
