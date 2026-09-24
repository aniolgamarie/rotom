import { test, assert, evidence } from "./recorded-test.ts";
import { capabilityStatus, type AdapterIdentity, type Certification } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";

// [U VAL-011] Reference version differs from chosen runtime
// U 层级验证：纯规则测试，验证版本差异的认证规则
test("[U VAL-011] reference version differs from chosen runtime requires re-certification", () => {
  const reference: AdapterIdentity = {
    adapter: "managed-child", version: "v1.0.0", runtime: "pinned",
    profileDigest: "reader-profile", transportDigest: "direct-chat", mode: "foreground/fresh"
  };
  const runtime: AdapterIdentity = {
    ...reference, version: "v1.1.0"  // 版本不同
  };
  
  // 创建基于参考版本的认证
  const certification: Certification = {
    identityDigest: digest(reference),
    capabilities: {
      settled: { supported: true, testEvidence: ["fixture-evidence"], level: "A" },
      termination: { supported: true, testEvidence: ["fixture-evidence"], level: "A" },
      events: { supported: true, testEvidence: ["fixture-evidence"], level: "A" }
    }
  };
  
  const required: Array<"events" | "termination"> = ["events", "termination"];
  
  // 参考版本应该通过认证
  const referenceStatus = capabilityStatus(reference, certification, required);
  for (const id of ["VAL-011"]) evidence(id, () => {
    assert.equal(referenceStatus.eligible, true, "reference version should be eligible");
  });
  
  // 运行时版本不同，认证应该失败（identityDigest 不匹配）
  const runtimeStatus = capabilityStatus(runtime, certification, required);
  for (const id of ["VAL-011"]) evidence(id, () => {
    assert.equal(runtimeStatus.eligible, false, "runtime version should not be eligible with reference certification");
    assert.deepEqual(runtimeStatus.missing, ["certification_missing_or_stale"]);
  });
  
  // 需要为运行时版本重新认证
  const runtimeCertification: Certification = {
    identityDigest: digest(runtime),
    capabilities: certification.capabilities
  };
  const reCertifiedStatus = capabilityStatus(runtime, runtimeCertification, required);
  for (const id of ["VAL-011"]) evidence(id, () => {
    assert.equal(reCertifiedStatus.eligible, true, "runtime should be eligible after re-certification");
  });
});
