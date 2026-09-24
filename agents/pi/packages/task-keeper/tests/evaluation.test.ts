import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { evaluate, type EvaluationRun } from "../src/evidence/evaluation.ts";

test("[U V VAL-009 VAL-010 T73 T74 T75] evaluation retains failed, cancelled, unknown and expensive starts without holdout leakage", () => {
  const run: EvaluationRun = { id: "one", taskId: "task", family: "family", split: "holdout", level: "L1", policy: "direct",
    environmentDigest: "env", modelBindingDigest: "model", toolsDigest: "tools", acceptanceDigest: "acceptance", startedAt: 100,
    durationMs: 1000, waitingMs: 500, requests: 2, unknownRequests: 0, cost: 0.1, accepted: true, failed: false, cancelled: false,
    humanInterventions: 0, artifact: "one.json", failureHistory: [] };
  const report = evaluate([run, { ...run, id: "two", accepted: false, failed: true, cost: null }, { ...run, id: "three", accepted: null, cancelled: true, unknownRequests: 1 }]);
  assert.equal(report.totalStarted, 3); assert.equal(report.groups[0].successPerStarted, 1 / 3);
  assert.equal(report.groups[0].unknownCostRuns, 1); assert.equal(report.groups[0].unknownRequests, 1); assert.equal(report.groups[0].cancelled, 1);
  assert.equal(report.efficacyClaim, "not_established");
  assert.throws(() => evaluate([run, { ...run, id: "two", split: "development" }]));
  assert.equal(evaluate([run, { ...run, id: "two", policy: "cascade", acceptanceDigest: "weakened" }]).comparableSetup, false);
  const old=JSON.parse(JSON.stringify({...run,policy:"cascade"})),history=evaluate([old]);
  acceptance("AC30","old-history-readable",{level:"U",observer:"legacy-evaluation-reader",predicate:"historical cascade remains readable without enabling execution",artifact:observerArtifact("legacy-cascade-history",{old,history})},()=>{
    assert.equal(history.groups[0].key,"L1:holdout:cascade");assert.equal(history.groups[0].requests,2);assert.equal(history.groups[0].knownCost,.1);assert.equal(history.totalStarted,1);
  });
  assert.throws(() => evaluate([])); assert.throws(() => evaluate([run, run]));
});
