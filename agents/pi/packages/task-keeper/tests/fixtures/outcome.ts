import type { TaskSpec, ExecutionFacts } from "../../src/contracts/task.ts";
export function acceptedCandidate(): { spec: TaskSpec; facts: ExecutionFacts } {
  return { spec: { id: "job", workScope: "scope", version: 1, objective: "verify the bounded candidate", workflow: "fix",
    required: ["tests", "review"], optional: ["extra"], allowPartial: true, risk: "unknown", policyDigest: "policy", snapshot: "tree", maxSteps: 16, maxSemanticAttempts: 3 },
  facts: { delivery: "started", nativeRunId: "native", execution: "ended", nativeStatus: "completed", terminationConfirmed: true,
    contract: { requested: { model: "configured-model", thinking: "high" }, resolved: { model: "configured-model", thinking: "high" },
      runtimeObserved: { model: "configured-model", thinking: "high" }, violations: [] }, observation: { complete: true, gaps: [] },
    unknownMutators: [], failures: [], claims: [], checks: ["tests", "review", "extra"].map(checkId => ({ checkId, status: "passed", snapshot: "tree",
      specVersion: 1, policyDigest: "policy", source: checkId === "review" ? "reviewer" : "verifier", artifactId: `artifact-${checkId}` })) } };
}
