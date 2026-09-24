import { test, assert, evidence } from "./recorded-test.ts";
import { validatePlan, dependenciesSatisfied, type PlanStep, type QueuedStep } from "../src/orchestration/scheduler.ts";

// [U SCH-010] Verification races with implementation
// U 层级验证：纯规则测试，验证步骤依赖的规则
test("[U SCH-010] write step cannot proceed while verification is frozen", () => {
  // 创建一个包含多个 write 和 verify 步骤的计划
  const steps: PlanStep[] = [
    { id: "impl-1", dependencies: [], allowedSkippedDependencies: [], role: "worker", kind: "write", optional: false, resources: [] },
    { id: "verify-1", dependencies: ["impl-1"], allowedSkippedDependencies: [], role: "verifier", kind: "verify", optional: false, resources: [] },
    { id: "impl-2", dependencies: ["verify-1"], allowedSkippedDependencies: [], role: "worker", kind: "write", optional: false, resources: [] },
    { id: "verify-2", dependencies: ["impl-2"], allowedSkippedDependencies: [], role: "verifier", kind: "verify", optional: false, resources: [] }
  ];
  
  validatePlan(steps, 10);
  
  // 模拟 verify-1 步骤正在运行（冻结候选）
  const queuedSteps: QueuedStep[] = [
    { ...steps[0], status: "passed", readyAt: null, intentId: "intent-1", finishedAt: Date.now() },
    { ...steps[1], status: "running", readyAt: Date.now(), intentId: "intent-1", finishedAt: null },
    { ...steps[2], status: "pending", readyAt: null, intentId: null, finishedAt: null },
    { ...steps[3], status: "pending", readyAt: null, intentId: null, finishedAt: null }
  ];
  
  // 验证 verify-1 正在运行时，impl-2 不能开始
  const impl2Step = steps[2];
  const canStartImpl2 = dependenciesSatisfied(queuedSteps, impl2Step);
  
  for (const id of ["SCH-010"]) evidence(id, () => {
    assert.equal(canStartImpl2, false, "impl-2 should not start while verify-1 is running");
    
    // 验证 verify-1 完成后，impl-2 可以开始
    queuedSteps[1].status = "passed";
    queuedSteps[1].finishedAt = Date.now();
    const canStartImpl2AfterVerify = dependenciesSatisfied(queuedSteps, impl2Step);
    assert.equal(canStartImpl2AfterVerify, true, "impl-2 can start after verify-1 passes");
    
    // 模拟 impl-2 开始运行
    queuedSteps[2].status = "running";
    queuedSteps[2].readyAt = Date.now();
    queuedSteps[2].intentId = "intent-2";
    
    // 验证 impl-2 运行时，verify-2 不能开始
    const verify2Step = steps[3];
    const canStartVerify2 = dependenciesSatisfied(queuedSteps, verify2Step);
    assert.equal(canStartVerify2, false, "verify-2 should not start while impl-2 is running");
    
    // 验证 impl-2 完成后，verify-2 可以开始
    queuedSteps[2].status = "passed";
    queuedSteps[2].finishedAt = Date.now();
    const canStartVerify2AfterImpl = dependenciesSatisfied(queuedSteps, verify2Step);
    assert.equal(canStartVerify2AfterImpl, true, "verify-2 can start after impl-2 passes");
  });
});
