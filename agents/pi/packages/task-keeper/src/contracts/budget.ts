import { finiteInteger, ContractError } from "./primitives.ts";

/** Unknown requests remain in reserved; this predicate never releases or resets accounting. */
export function requestBudgetAvailable(bucket: { used: number; reserved: number; ceiling: number }, minimumRemaining = 0): boolean {
  finiteInteger(bucket.used); finiteInteger(bucket.reserved); finiteInteger(bucket.ceiling); finiteInteger(minimumRemaining);
  // Subtraction avoids rounding an overflowing sum of valid safe integers.
  return bucket.used < bucket.ceiling && bucket.reserved < bucket.ceiling - bucket.used - minimumRemaining;
}

export type RequestState = "reserved" | "unknown" | "sent" | "not_sent";
export type RequestFact = Exclude<RequestState, "reserved">;
/** Idempotent accounting transition; unknown is still reserved, never a free attempt. */
export function requestSettlement(current: RequestState, fact: RequestFact) {
  if (!["reserved", "unknown", "sent", "not_sent"].includes(current) || !["unknown", "sent", "not_sent"].includes(fact)) throw new ContractError("INVALID_REQUEST_STATE");
  if (current === fact) return { changed: false, state: current, usedDelta: 0, reservedDelta: 0 };
  if (current !== "reserved" && current !== "unknown") throw new ContractError("CONFLICTING_REQUEST_FACT");
  return { changed: true, state: fact, usedDelta: fact === "sent" ? 1 : 0, reservedDelta: fact === "unknown" ? 0 : -1 };
}
