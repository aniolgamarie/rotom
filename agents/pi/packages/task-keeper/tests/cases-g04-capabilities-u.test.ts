import { test, assert, evidence } from "./recorded-test.ts";
import { capabilityStatus, executionRequirements, type AdapterIdentity, type Certification, type Capability } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";
import { configured } from "./fixtures/config.ts";
import { parseConfig } from "../src/config.ts";

const identity: AdapterIdentity = { adapter: "managed-child", version: "candidate", runtime: "pinned", profileDigest: "reader-profile", transportDigest: "direct-chat", mode: "foreground/fresh" };
function certificate(candidate = identity): Certification {
  const capabilities: Certification["capabilities"] = {};
  for (const key of ["settled", "continuationIdentity", "termination", "events", "readonly", "workspace", "requestGate"] as Capability[])
    capabilities[key] = { supported: true, level: "A", testEvidence: ["retained-fixture-evidence"] };
  return { identityDigest: digest(candidate), capabilities };
}

test("[U T67] deferred advisors cannot enable themselves and protected execution still requires a certified request gate", () => {
  for (const id of ["T67"]) evidence(id, () => {
    for (const mode of ["shadow", "online", "active"]) {
      const config = configured();
      assert.throws(() => parseConfig({ ...config, advisor: { mode } }));
      assert.equal(config.advisor.mode, "off");
    }
    const required = executionRequirements("fix", true), cert = certificate();
    delete cert.capabilities.requestGate;
    assert.deepEqual(capabilityStatus(identity, cert, required), { eligible: false, missing: ["requestGate"] });
    assert.equal(capabilityStatus(identity, certificate(), required).eligible, true);
  });
  // This covers admission only; each summary/compaction HTTP call is certified
  // by the original request-path matrix, not by these structural inputs.
});

test("[U EXE-001 T48] a foreground fresh certificate cannot authorize any background or fork mode", () => {
  const cert = certificate(), required = executionRequirements("fix", true);
  for (const id of ["EXE-001", "T48"]) evidence(id, () => {
    assert.equal(capabilityStatus(identity, cert, required).eligible, true);
    for (const mode of ["background/fresh", "foreground/fork", "background/fork"]) {
      const result = capabilityStatus({ ...identity, mode }, cert, required);
      assert.equal(result.eligible, false); assert.deepEqual(result.missing, ["certification_missing_or_stale"]);
    }
    assert.equal(capabilityStatus(identity, null, required).eligible, false);
  });
});

test("[U CFG-010 RTB-007 T33] missing managed request gate does not invalidate an independent interactive certificate", () => {
  const childCert = certificate(); childCert.capabilities.requestGate = { supported: false, level: "A", testEvidence: ["denial-not-proven"] };
  const parent: AdapterIdentity = { ...identity, adapter: "interactive", mode: "rpc" }, parentCert = certificate(parent);
  for (const id of ["CFG-010", "RTB-007", "T33"]) evidence(id, () => {
    assert.equal(capabilityStatus(identity, childCert, executionRequirements("fix", true)).eligible, false);
    assert.deepEqual(capabilityStatus(identity, childCert, executionRequirements("fix", true)).missing, ["requestGate"]);
    assert.equal(capabilityStatus(identity, null, executionRequirements("fix", true)).eligible, false);
    assert.equal(capabilityStatus(parent, parentCert, executionRequirements("interactive", false)).eligible, true);
    for (const gate of [undefined, { supported: true, level: "U" as const, testEvidence: ["unit-only"] }, { supported: true, level: "A" as const, testEvidence: [] }]) {
      const incomplete = certificate(); incomplete.capabilities.requestGate = gate;
      assert.equal(capabilityStatus(identity, incomplete, executionRequirements("fix", true)).eligible, false);
    }
    assert.equal(capabilityStatus(identity, certificate(), executionRequirements("fix", true)).eligible, true);
  });
});

test("[U EXE-002] each compatibility identity dimension independently invalidates the old certificate", () => {
  const cert = certificate(), required = executionRequirements("inspect", false);
  assert.equal(capabilityStatus(identity, cert, required).eligible, true);
  for (const key of Object.keys(identity) as Array<keyof AdapterIdentity>) {
    const changed = { ...identity, [key]: "different" };
    assert.equal(capabilityStatus(changed, cert, required).eligible, false, key);
  }
  for (const missing of required) {
    const incomplete = certificate(); delete incomplete.capabilities[missing];
    assert.deepEqual(capabilityStatus(identity, incomplete, required).missing, [missing]);
  }
});
