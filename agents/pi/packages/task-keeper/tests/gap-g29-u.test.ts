import { test, assert } from "./recorded-test.ts";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { Artifacts } from "../src/store/artifacts.ts";
import { ReviewCache, type ReviewReuseContract } from "../src/verification/reuse.ts";
import { parseConfig, applyProjectPolicy } from "../src/config.ts";
import { isolatedDirectory } from "./helpers.ts";
function setup(root: string) {
  const store = new Store(root), artifacts = new Artifacts(store), cache = new ReviewCache(store);
  const contract: ReviewReuseContract = { spec: { id: "job", workScope: "scope", version: 1, objective: "fixed", workflow: "fix", required: ["tests", "review"], optional: [],
    allowPartial: false, risk: "high", policyDigest: "policy", snapshot: "snapshot", maxSteps: 16, maxSemanticAttempts: 3 }, artifacts: ["patch", "checks"],
    modelDigest: "model", profileDigest: "profile", runtimeDigest: "runtime", writerDescriptorIds: ["writer"] };
  const raw = artifacts.pin("job", "snapshot", JSON.stringify({ descriptorId: "reviewer", status: "ended", terminationConfirmed: true }), "runtime");
  const receipt = artifacts.pin("job", "snapshot", JSON.stringify({ review: { passed: true }, invocation: "reviewer" }), "verifier");
  const proof = { resultArtifact: raw.id, receiptArtifact: receipt.id, descriptorId: "reviewer", purpose: "acceptance" as const, complete: true, independent: true };
  return { store, artifacts, cache, contract, raw, receipt, proof };
}
for (const id of ["WFL-010", "T86"]) test(`[U S ${id}] complete independent review reuse is exact and retains source provenance`, t => {
  const x = setup(isolatedDirectory(t)); t.after(() => x.store.close());
  assert.equal(x.cache.lookup(x.contract), null);
  assert.equal(x.cache.remember(x.contract, x.proof), true);
  const first = x.cache.lookup(x.contract)!; assert.equal(first.result.descriptorId, "reviewer"); assert.equal(first.receiptArtifact, x.receipt.id);
  assert.deepEqual(x.cache.lookup({ ...x.contract, artifacts: ["checks", "patch"] }), first);
  assert.equal(x.cache.remember(x.contract, { ...x.proof, purpose: "diagnostic" }), true);
  assert.equal(x.cache.lookup(x.contract)?.purpose, "diagnostic");
  assert.equal(x.cache.lookup(x.contract)?.result.descriptorId, "reviewer");
});
for (const id of ["WFL-008", "T81"]) test(`[U S ${id}] stale incomplete or writer-owned diagnostic evidence cannot replace acceptance`, t => {
  const x = setup(isolatedDirectory(t)); t.after(() => x.store.close());
  for (const change of [{ complete: false }, { independent: false }, { descriptorId: "writer" }]) {
    assert.equal(x.cache.remember(x.contract, { ...x.proof, ...change }), false); assert.equal(x.cache.lookup(x.contract), null);
  }
  x.cache.remember(x.contract, x.proof);
  for (const change of [
    { spec: { ...x.contract.spec, snapshot: "changed" } }, { spec: { ...x.contract.spec, version: 2 } },
    { spec: { ...x.contract.spec, policyDigest: "new" } }, { spec: { ...x.contract.spec, risk: "unknown" as const } },
    { spec: { ...x.contract.spec, required: ["tests", "review", "new-check"] } },
    { artifacts: ["patch", "new-checks"] }, { profileDigest: "stricter" }, { modelDigest: "other" }, { runtimeDigest: "upgraded" },
    { writerDescriptorIds: ["reviewer"] },
  ]) { assert.equal(x.cache.lookup({ ...x.contract, ...change }), null); assert.ok(x.cache.lookup(x.contract)); }
  writeFileSync(join(x.store.root, "artifacts", x.raw.id), "changed"); assert.equal(x.cache.lookup(x.contract), null);
});
test("[U WFL-009] user risk and required checks cannot be weakened by project review policy", () => {
  const user = parseConfig({ workflow: { risk: "high", allowPartial: false } });
  const result = applyProjectPolicy(user, { workflow: { risk: "low", allowPartial: true, requiredChecks: { fix: [] } } });
  assert.equal(result.workflow.risk, "high"); assert.equal(result.workflow.allowPartial, false);
  assert.deepEqual(result.workflow.requiredChecks.fix, user.workflow.requiredChecks.fix);
  assert.equal(parseConfig({}).workflow.risk, "unknown");
  assert.throws(() => parseConfig({ workflow: { risk: "trusted-by-model" } }));
});
