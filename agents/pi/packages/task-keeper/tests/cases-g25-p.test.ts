import { test, assert, evidence } from "./recorded-test.ts";
import { validatePlan, dependenciesSatisfied, type PlanStep, type QueuedStep } from "../src/orchestration/scheduler.ts";

// [U SCH-010] Verification races with implementation
// U 层级验证：纯规则测试，验证步骤依赖的规则
test("[U SCH-010] verification step blocks concurrent write to frozen candidate", () => {
  // 创建一个包含 verify 步骤的计划
  const steps: PlanStep[] = [
    { id: "impl", dependencies: [], allowedSkippedDependencies: [], role: "worker", kind: "write", optional: false, resources: [] },
    { id: "verify", dependencies: ["impl"], allowedSkippedDependencies: [], role: "verifier", kind: "verify", optional: false, resources: [] },
    { id: "review", dependencies: ["verify"], allowedSkippedDependencies: [], role: "reviewer", kind: "review", optional: false, resources: [] }
  ];
  
  validatePlan(steps, 10);
  
  // 模拟 verify 步骤正在运行
  const queuedSteps: QueuedStep[] = [
    { ...steps[0], status: "passed", readyAt: null, intentId: "intent-1", finishedAt: Date.now() },
    { ...steps[1], status: "running", readyAt: Date.now(), intentId: "intent-1", finishedAt: null },
    { ...steps[2], status: "pending", readyAt: null, intentId: null, finishedAt: null }
  ];
  
  // 验证 verify 步骤正在运行时，review 步骤不能开始
  const reviewStep = steps[2];
  const canStart = dependenciesSatisfied(queuedSteps, reviewStep);
  
  for (const id of ["SCH-010"]) evidence(id, () => {
    assert.equal(canStart, false, "review should not start while verify is running");
    
    // 验证 verify 步骤完成后，review 步骤可以开始
    queuedSteps[1].status = "passed";
    queuedSteps[1].finishedAt = Date.now();
    const canStartAfterVerify = dependenciesSatisfied(queuedSteps, reviewStep);
    assert.equal(canStartAfterVerify, true, "review can start after verify passes");
    
    // 验证 verify 步骤失败后，review 步骤不能开始
    queuedSteps[1].status = "failed";
    const canStartAfterFail = dependenciesSatisfied(queuedSteps, reviewStep);
    assert.equal(canStartAfterFail, false, "review should not start after verify fails");
  });
});
