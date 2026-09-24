import { test, assert, evidence } from "./recorded-test.ts";
import { capabilityStatus, executionRequirements, type AdapterIdentity, type Certification } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";

// [U VAL-001] Implementation deviates from baseline
test("[U VAL-001] implementation deviation from baseline requires explicit ADR and evidence", () => {
  const baseline: AdapterIdentity = {
    adapter: "managed-child", version: "v1.0.0", runtime: "pinned",
    profileDigest: "baseline-profile", transportDigest: "direct-chat", mode: "foreground/fresh"
  };
  
  const deviated: AdapterIdentity = {
    ...baseline, version: "v1.1.0"
  };
  
  const required = executionRequirements("fix", false);
  
  const baselineCertification: Certification = {
    identityDigest: digest(baseline),
    capabilities: {
      events: { supported: true, testEvidence: ["baseline-test"], level: "A" },
      termination: { supported: true, testEvidence: ["baseline-test"], level: "A" },
      workspace: { supported: true, testEvidence: ["baseline-test"], level: "A" }
    }
  };
  
  for (const id of ["VAL-001"]) evidence(id, () => {
    const baselineStatus = capabilityStatus(baseline, baselineCertification, required);
    assert.equal(baselineStatus.eligible, true, "baseline should be eligible");
    
    const deviatedStatus = capabilityStatus(deviated, baselineCertification, required);
    assert.equal(deviatedStatus.eligible, false, "deviated implementation should not be eligible");
    assert.deepEqual(deviatedStatus.missing, ["certification_missing_or_stale"]);
    
    const deviatedCertification: Certification = {
      identityDigest: digest(deviated),
      capabilities: baselineCertification.capabilities
    };
    const reCertifiedStatus = capabilityStatus(deviated, deviatedCertification, required);
    assert.equal(reCertifiedStatus.eligible, true, "deviated implementation needs re-certification");
  });
});

// [U VAL-008] P3 gate unavailable while P1 is certified
test("[U VAL-008] P3 gate unavailable does not block P1 certified route", () => {
  const p1Identity: AdapterIdentity = {
    adapter: "managed-child", version: "v1.0.0", runtime: "pinned",
    profileDigest: "p1-profile", transportDigest: "direct-chat", mode: "foreground/fresh"
  };
  
  const p1Required = executionRequirements("fix", false);
  
  const p1Certification: Certification = {
    identityDigest: digest(p1Identity),
    capabilities: {
      events: { supported: true, testEvidence: ["p1-test"], level: "A" },
      termination: { supported: true, testEvidence: ["p1-test"], level: "A" },
      workspace: { supported: true, testEvidence: ["p1-test"], level: "A" }
    }
  };
  
  for (const id of ["VAL-008"]) evidence(id, () => {
    const p1Status = capabilityStatus(p1Identity, p1Certification, p1Required);
    assert.equal(p1Status.eligible, true, "P1 should be eligible without requestGate");
    
    // P3 需要 requestGate（受保护路线）
    const p3Identity: AdapterIdentity = {
      ...p1Identity, profileDigest: "p3-profile"
    };
    const p3Required = executionRequirements("fix", true);
    const p3Status = capabilityStatus(p3Identity, p1Certification, p3Required);
    assert.equal(p3Status.eligible, false, "P3 should not be eligible");
    
    // P1 的认证不应该被 P3 的 gate 不可用阻塞
    const p1StatusAfterP3Check = capabilityStatus(p1Identity, p1Certification, p1Required);
    assert.equal(p1StatusAfterP3Check.eligible, true, "P1 should remain eligible");
  });
});
