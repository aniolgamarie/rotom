import { finiteInteger, ContractError, digest } from "../contracts/primitives.ts";

export interface EvaluationRun {
  id: string; taskId: string; family: string; split: "development" | "holdout";
  level: "L1" | "L2" | "L3"; policy: "direct" | "cascade" | "critique";
  environmentDigest: string; modelBindingDigest: string; toolsDigest: string; acceptanceDigest: string;
  startedAt: number; durationMs: number; waitingMs: number; requests: number; unknownRequests: number;
  cost: number | null; accepted: boolean | null; failed: boolean; cancelled: boolean; humanInterventions: number;
  artifact: string; failureHistory: string[];
  disposition?: "finished" | "infra_failed" | "parked" | "censored";
  executionMode?: "executed" | "shadow";
  issueId?: string; sourceSnapshot?: string;
}
/** Every started run stays in the denominator; unknown outcomes and unknown fees are disclosed. */
export function evaluate(runs: EvaluationRun[], startedRunIds?: readonly string[]) {
  if (!runs.length || new Set(runs.map((run) => run.id)).size !== runs.length) throw new ContractError("INVALID_EVALUATION_RUNS");
  if (startedRunIds && (new Set(startedRunIds).size !== startedRunIds.length || startedRunIds.length !== runs.length
    || runs.some(run => !startedRunIds.includes(run.id)))) throw new ContractError("EVALUATION_START_INVENTORY_MISMATCH");
  const splits = new Map<string, string>(), groups = new Map<string, EvaluationRun[]>();
  for (const run of runs) {
    for (const field of ["id", "taskId", "family", "environmentDigest", "modelBindingDigest", "toolsDigest", "acceptanceDigest", "artifact"] as const)
      if (typeof run[field] !== "string" || !run[field].trim()) throw new ContractError("INVALID_EVALUATION_IDENTITY");
    if (!["development", "holdout"].includes(run.split) || !["L1", "L2", "L3"].includes(run.level)
      || !["direct", "cascade", "critique"].includes(run.policy) || ![true, false, null].includes(run.accepted)
      || typeof run.failed !== "boolean" || typeof run.cancelled !== "boolean"
      || !Array.isArray(run.failureHistory) || run.failureHistory.some(failure => typeof failure !== "string")
      || (run.disposition !== undefined && !["finished", "infra_failed", "parked", "censored"].includes(run.disposition))
      || (run.executionMode !== undefined && !["executed", "shadow"].includes(run.executionMode))) throw new ContractError("INVALID_EVALUATION_FACT");
    for (const field of ["startedAt", "durationMs", "waitingMs", "requests", "unknownRequests", "humanInterventions"] as const) finiteInteger(run[field]);
    if (!run.artifact || run.waitingMs > run.durationMs || (run.cost !== null && (!Number.isFinite(run.cost) || run.cost < 0))) throw new ContractError("INVALID_EVALUATION_FACT");
    if (run.accepted && (run.failed || run.cancelled)) throw new ContractError("CONFLICTING_EVALUATION_OUTCOME");
    if ((run.disposition === "parked" || run.disposition === "censored" || run.executionMode === "shadow")
      && (run.accepted !== null || run.failed || run.cancelled)) throw new ContractError("CONFLICTING_EVALUATION_OUTCOME");
    if (run.disposition === "infra_failed" && (!run.failed || run.accepted === true)) throw new ContractError("CONFLICTING_EVALUATION_OUTCOME");
    const identities = [`family:${run.family}`];
    for (const field of ["issueId", "sourceSnapshot"] as const) if (run[field] !== undefined) {
      if (typeof run[field] !== "string" || !run[field]!.trim()) throw new ContractError("INVALID_EVALUATION_IDENTITY");
      identities.push(`${field}:${run[field]}`);
    }
    for (const identity of identities) {
      if (splits.has(identity) && splits.get(identity) !== run.split) throw new ContractError("HOLDOUT_FAMILY_LEAKAGE");
      splits.set(identity, run.split);
    }
    const key = `${run.level}:${run.split}:${run.policy}`;
    groups.set(key, [...groups.get(key) ?? [], run]);
  }
  const setup = new Set(runs.map((run) => digest([run.environmentDigest, run.modelBindingDigest, run.toolsDigest, run.acceptanceDigest])));
  return { totalStarted: runs.length, startInventoryVerified: startedRunIds !== undefined, comparableSetup: setup.size === 1, efficacyClaim: "not_established",
    groups: [...groups].map(([key, group]) => ({ key, started: group.length,
      accepted: group.filter((run) => run.accepted === true).length, unknownOutcome: group.filter((run) => run.accepted === null).length,
      failures: group.filter((run) => run.failed && run.disposition !== "infra_failed").length, cancelled: group.filter((run) => run.cancelled).length,
      infraFailures: group.filter(run => run.disposition === "infra_failed").length,
      parked: group.filter(run => run.disposition === "parked").length, censored: group.filter(run => run.disposition === "censored").length,
      shadowOnly: group.filter(run => run.executionMode === "shadow").length,
      successPerStarted: group.filter((run) => run.accepted === true).length / group.length,
      requests: group.reduce((sum, run) => sum + run.requests, 0), unknownRequests: group.reduce((sum, run) => sum + run.unknownRequests, 0),
      knownCost: group.reduce((sum, run) => sum + (run.cost ?? 0), 0), unknownCostRuns: group.filter((run) => run.cost === null).length,
      durationMs: group.reduce((sum, run) => sum + run.durationMs, 0), waitingMs: group.reduce((sum, run) => sum + run.waitingMs, 0),
      humanInterventions: group.reduce((sum, run) => sum + run.humanInterventions, 0), artifacts: group.map((run) => run.artifact) })),
    limitations: ["L1 fixtures establish contracts, not model quality", "L2 replay depends on trace representativeness", "L3 requires a bound live model and grouped holdout tasks", "No efficacy conclusion follows from a single successful task"] };
}
