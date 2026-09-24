import { test, assert, evidence } from "./recorded-test.ts";
import { configured } from "./fixtures/config.ts";
import { configurationPolicyDigest } from "../src/config.ts";
import { outcome } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U T46] changing skip filter threshold or verifier binding invalidates the original acceptance policy", () => {
  for (const id of ["T46"]) evidence(id, () => {
    const config = configured();
    config.verificationBindings.tests = { executable: "/fixture/node", args: ["checks.js"], environment: {},
      timeoutMs: 1000, kind: "tests", parser: "json", minimumTests: 2, inputs: ["checks.js"] };
    const initial = configurationPolicyDigest(config), { spec, facts } = acceptedCandidate();
    spec.policyDigest = initial; for (const check of facts.checks) check.policyDigest = initial;
    assert.equal(outcome(spec, facts).status, "COMPLETED");
    for (const patch of [{ args: ["checks.js", "--skip-required"] }, { args: ["checks.js", "--filter=easy"] },
      { minimumTests: 1 }, { inputs: ["other-checks.js"] }, { executable: "/fixture/other-node" }]) {
      const changed = structuredClone(config); Object.assign(changed.verificationBindings.tests, patch);
      const policy = configurationPolicyDigest(changed), before = structuredClone(facts);
      assert.notEqual(policy, initial);
      const receipt = outcome({ ...spec, policyDigest: policy }, facts);
      assert.equal(receipt.status, "BLOCKED"); assert.deepEqual(facts, before);
      assert.equal(outcome(spec, facts).status, "COMPLETED");
    }
  });
  // File-byte changes use verificationInputs/sourceSnapshot and remain P/E checks.
});
