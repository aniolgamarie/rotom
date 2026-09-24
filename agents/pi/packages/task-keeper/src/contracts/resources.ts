import { ContractError, finiteInteger, identifier } from "./primitives.ts";

export interface ResourceDemand { id: string; capacity: number; units: number }
export interface ResourceObservation { id: string; capacity: number | null; used: number }

/** Plan the entire claim set from one transaction's observations. No partial plan is returned. */
export function resourceClaimPlan(demands: readonly ResourceDemand[], observations: readonly ResourceObservation[]): ResourceDemand[] {
  const requested = new Set<string>(), observed = new Map<string, ResourceObservation>();
  for (const demand of demands) {
    identifier(demand.id); finiteInteger(demand.capacity); finiteInteger(demand.units, 1);
    if (requested.has(demand.id)) throw new ContractError("DUPLICATE_RESOURCE");
    requested.add(demand.id);
  }
  for (const observation of observations) {
    identifier(observation.id); finiteInteger(observation.used);
    if (observation.capacity !== null) finiteInteger(observation.capacity);
    if (observed.has(observation.id)) throw new ContractError("DUPLICATE_RESOURCE_OBSERVATION");
    observed.set(observation.id, observation);
  }
  return demands.map(demand => {
    const current = observed.get(demand.id);
    if (!current) throw new ContractError("RESOURCE_OBSERVATION_MISSING", demand.id);
    const capacity = Math.min(demand.capacity, current.capacity ?? demand.capacity);
    if (current.used > capacity || demand.units > capacity - current.used) throw new ContractError("RESOURCE_DENIED", demand.id);
    return { id: demand.id, capacity, units: demand.units };
  });
}
