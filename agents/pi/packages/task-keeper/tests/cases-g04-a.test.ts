import { test, assert, evidence } from "./recorded-test.ts";
import { capabilityStatus, modelBindingDigest, type AdapterIdentity, type Certification } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";

// [U VAL-011] Reference version differs from chosen runtime
// U 层级验证：纯规则测试，验证版本差异的认证规则
test("[U VAL-011] runtime version mismatch prevents capability inheritance from reference docs", () => {
  // 模拟参考文档中的模型绑定
  const referenceModel = {
    api: "openai-completions", provider: "qwen", id: "qwen-turbo",
    baseUrl: "https://api.example.com", reasoning: false,
    contextWindow: 8192, maxTokens: 2048,
    thinkingLevelMap: { off: "none", low: "low", high: "high" }
  };
  
  // 模拟运行时实际使用的模型绑定（版本不同）
  const runtimeModel = {
    ...referenceModel, id: "qwen-turbo-v2"  // 模型版本不同
  };
  
  const referenceBinding = modelBindingDigest(referenceModel);
  const runtimeBinding = modelBindingDigest(runtimeModel);
  
  for (const id of ["VAL-011"]) evidence(id, () => {
    // 绑定摘要应该不同
    assert.notEqual(referenceBinding, runtimeBinding, "different model versions should have different bindings");
    
    // 创建基于参考版本的适配器身份
    const referenceIdentity: AdapterIdentity = {
      adapter: "managed-child", version: "v1.0.0", runtime: "pinned",
      profileDigest: digest(referenceBinding), transportDigest: "direct-chat", mode: "foreground/fresh"
    };
    
    // 创建运行时适配器身份
    const runtimeIdentity: AdapterIdentity = {
      ...referenceIdentity, profileDigest: digest(runtimeBinding)
    };
    
    // 创建认证
    const certification: Certification = {
      identityDigest: digest(referenceIdentity),
      capabilities: {
        events: { supported: true, testEvidence: ["actual-runtime-test"], level: "A" },
        termination: { supported: true, testEvidence: ["actual-runtime-test"], level: "A" }
      }
    };
    
    const required: Array<"events" | "termination"> = ["events", "termination"];
    
    // 参考身份应该通过
    const refStatus = capabilityStatus(referenceIdentity, certification, required);
    assert.equal(refStatus.eligible, true, "reference identity should be eligible");
    
    // 运行时身份应该失败（profileDigest 不同）
    const runStatus = capabilityStatus(runtimeIdentity, certification, required);
    assert.equal(runStatus.eligible, false, "runtime identity should not be eligible");
    assert.deepEqual(runStatus.missing, ["certification_missing_or_stale"]);
  });
});
