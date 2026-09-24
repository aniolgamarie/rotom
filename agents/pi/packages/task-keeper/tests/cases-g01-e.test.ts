import { test, assert, evidence } from "./recorded-test.ts";
import { parseConfig, applyProjectPolicy, DEFAULT_CONFIG, type Config } from "../src/config.ts";

// [U CFG-011] Repeated package synchronization
// U 层级验证：纯规则测试，验证配置合并的稳定性
test("[U CFG-011] repeated package synchronization preserves user authorizations and state", () => {
  // 创建初始用户配置（基于 DEFAULT_CONFIG）
  const userConfig: Config = structuredClone(DEFAULT_CONFIG);
  userConfig.enabled = true;
  userConfig.features.interactiveRecovery = true;
  userConfig.features.managedWorkflows = true;
  userConfig.budget.backupAttemptsPerIncident = 2;
  userConfig.budget.protectedAttemptsPerWorkScope = 5;
  userConfig.budget.minimumRequiredStageAttemptReserves = { "scope-evidence-review": 1 };
  userConfig.workflow.recipes = ["direct", "cascade"];
  userConfig.workflow.allowPartial = true;
  userConfig.workflow.risk = "medium";
  userConfig.verificationBindings = {
    "scope-evidence-review": {
      executable: "/bin/check1", args: [], environment: {}, timeoutMs: 1000,
      kind: "tests", parser: "json", minimumTests: 1, inputs: []
    }
  };
  
  // 第一次项目策略应用
  const projectPolicy1 = {
    enabled: true,
    features: { interactiveRecovery: true },
    allowedRoutes: [],
    limits: { activeJobsPerRepository: 1 },
    budget: { backupAttemptsPerIncident: 1 },
    workflow: {
      allowPartial: false,
      risk: "low",
      recipes: ["direct"],
      requiredChecks: { inspect: ["scope-evidence-review"], fix: [] }
    }
  };
  
  const merged1 = applyProjectPolicy(userConfig, projectPolicy1);
  
  // 第二次项目策略应用（重复同步）
  const projectPolicy2 = structuredClone(projectPolicy1);
  const merged2 = applyProjectPolicy(userConfig, projectPolicy2);
  
  for (const id of ["CFG-011"]) evidence(id, () => {
    // 验证重复同步后配置保持一致
    assert.equal(merged1.enabled, merged2.enabled, "enabled should be stable");
    assert.deepEqual(merged1.features, merged2.features, "features should be stable");
    assert.deepEqual(merged1.limits, merged2.limits, "limits should be stable");
    assert.deepEqual(merged1.budget, merged2.budget, "budget should be stable");
    assert.deepEqual(merged1.workflow, merged2.workflow, "workflow should be stable");
    assert.deepEqual(merged1.evidence, merged2.evidence, "evidence should be stable");
    assert.deepEqual(merged1.verificationBindings, merged2.verificationBindings, "verificationBindings should be stable");
    
    // 验证用户授权绑定未被重置
    assert.ok(merged2.verificationBindings["scope-evidence-review"], "user-authorized check should be preserved");
    
    // 验证预算未被重置
    assert.equal(merged2.budget.protectedAttemptsPerWorkScope, 5, "user budget should be preserved");
    assert.equal(merged2.budget.minimumRequiredStageAttemptReserves["scope-evidence-review"], 1, "user reserves should be preserved");
  });
});
