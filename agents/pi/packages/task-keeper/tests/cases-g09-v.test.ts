import { test, assert, evidence } from "./recorded-test.ts";
import { outcome, type TaskSpec, type ExecutionFacts } from "../src/contracts/task.ts";

// [U VAL-015] Critical fact disappears before the parent model
test("[U VAL-015] missing critical failure fact blocks acceptance", () => {
  const spec: TaskSpec = {
    id: "job-1",
    workScope: "scope-1",
    version: 1,
    objective: "test objective",
    workflow: "fix",
    required: ["check-1"],
    optional: [],
    allowPartial: false,
    policyDigest: "policy-1",
    snapshot: "snapshot-1",
    maxSteps: 10,
    maxSemanticAttempts: 3
  };
  
  // 场景 1：完整的失败事实
  const completeFacts: ExecutionFacts = {
    delivery: "started",
    nativeRunId: "run-1",
    execution: "ended",
    nativeStatus: "completed",
    terminationConfirmed: true,
    contract: {
      violations: [],
      resolved: { model: "qwen-turbo", provider: "qwen" },
      runtimeObserved: { model: "qwen-turbo", provider: "qwen" },
      requested: { model: "qwen-turbo", provider: "qwen" }
    },
    observation: { complete: true, gaps: [] },
    unknownMutators: [],
    failures: [
      { id: "check-1", layer: "verification", code: "CHECK_FAILED", message: "verification failed", attemptId: "attempt-1", required: true, resolvedBy: null }
    ],
    checks: [],
    claims: []
  };
  
  // 场景 2：缺少关键失败事实
  const incompleteFacts: ExecutionFacts = {
    ...completeFacts,
    failures: []  // 失败事实丢失
  };
  
  for (const id of ["VAL-015"]) evidence(id, () => {
    // 完整事实应该正确反映失败
    const completeResult = outcome(spec, completeFacts);
    assert.equal(completeResult.status, "BLOCKED", "complete facts should block");
    assert.ok(completeResult.reasons.some(r => r.includes("unresolved")), "should have unresolved failure");
    
    // 不完整事实（缺少失败）不应该通过验收
    const incompleteResult = outcome(spec, incompleteFacts);
    // 即使缺少失败事实，如果有其他问题也应该阻止验收
    assert.notEqual(incompleteResult.status, "COMPLETED", 
                    "incomplete facts should not complete");
  });
});
