import type { Config } from "../config.ts";
import { ContractError, finiteInteger, digest } from "../contracts/primitives.ts";

export interface StageState { chainDigest: string; incidentId: string; stageId: string; stageEnteredAt: number; deadline: number | null }
/** Persist the returned state with the incident. Restarting selection never resets an existing stage window. */
export function selectStage(chain: Config["recovery"]["chain"], previous: StageState | null, input: {
  now: number; incidentId: string; approved: string[]; safeBoundary: boolean; primaryRoute: string;
  primaryRecovered: boolean; backupExhausted: boolean; notBefore: Record<string, number>;
}) {
  finiteInteger(input.now);
  if (!chain.length || new Set(chain.map((stage) => stage.id)).size !== chain.length) throw new ContractError("INVALID_RECOVERY_CHAIN");
  const chainDigest = digest(chain);
  if (previous && (previous.chainDigest !== chainDigest || previous.incidentId !== input.incidentId)) throw new ContractError("STAGE_RECONCILIATION_REQUIRED");
  let index = previous ? chain.findIndex((stage) => stage.id === previous.stageId) : 0;
  if (index < 0) throw new ContractError("STAGE_NOT_FOUND");
  if (previous && !input.safeBoundary) return { state: previous, route: null, reason: "execution_not_reconciled", skipped: [] as string[] };
  if (!input.safeBoundary) return { state: null, route: null, reason: "execution_not_reconciled", skipped: [] as string[] };
  if (input.backupExhausted) {
    index = chain.findLastIndex((stage) => stage.route === input.primaryRoute && stage.wait.mode === "forever" && input.approved.includes(stage.route));
    if (index < 0) throw new ContractError("FINAL_PRIMARY_ROUTE_REQUIRED");
  } else if (input.primaryRecovered && input.approved.includes(input.primaryRoute)) {
    const primary = chain.findIndex((stage) => stage.route === input.primaryRoute);
    if (primary >= 0) index = primary;
  } else if (previous?.deadline !== null && previous?.deadline !== undefined && input.now >= previous.deadline) index++;
  const skipped: string[] = [];
  while (index < chain.length && !input.approved.includes(chain[index].route)) skipped.push(chain[index++].id);
  const stage = chain[index];
  if (!stage) return { state: previous, route: null, reason: "no_authorized_final_route", skipped };
  const state = previous?.stageId === stage.id ? previous : { chainDigest, incidentId: input.incidentId, stageId: stage.id,
    stageEnteredAt: input.now, deadline: stage.wait.mode === "forever" ? null : input.now + stage.wait.maxMs! };
  if ((input.notBefore[stage.route] ?? 0) > input.now) return { state, route: null, reason: "route_not_before", skipped };
  return { state, route: stage.route, reason: "safe_stage_candidate", skipped };
}
