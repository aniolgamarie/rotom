import type { EvaluationRun } from "../../src/evidence/evaluation.ts";
export function evaluationStarts(): EvaluationRun[] {
  const base: EvaluationRun = { id: "run-0", taskId: "task", family: "family", split: "holdout", level: "L1", policy: "direct",
    environmentDigest: "env", modelBindingDigest: "model", toolsDigest: "tools", acceptanceDigest: "acceptance", startedAt: 100,
    durationMs: 1000, waitingMs: 100, requests: 1, unknownRequests: 0, cost: 1, accepted: true, failed: false, cancelled: false,
    humanInterventions: 0, artifact: "runtime-fact.json", failureHistory: [], disposition: "finished", issueId: "issue", sourceSnapshot: "snapshot" };
  const runs = Array.from({ length: 10 }, (_, n) => ({ ...structuredClone(base), id: `run-${n}`, artifact: `run-${n}.json`, cost: n < 3 ? n + 1 : n < 5 ? null : 0 }));
  for (const n of [4, 5]) { runs[n].accepted = false; runs[n].failed = true; runs[n].failureHistory = ["implementation_failed"]; }
  runs[6].accepted = false; runs[6].failed = true; runs[6].disposition = "infra_failed";
  runs[7].accepted = null; runs[7].disposition = "parked";
  runs[8].accepted = null; runs[8].disposition = "censored"; runs[8].unknownRequests = 1;
  runs[9].accepted = false; runs[9].cancelled = true;
  return runs;
}
