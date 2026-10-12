import { finiteInteger, ContractError } from "./primitives.mjs";
export function requestBudgetAvailable(bucket, minimumRemaining = 0) {
    finiteInteger(bucket.used);
    finiteInteger(bucket.reserved);
    finiteInteger(bucket.ceiling);
    finiteInteger(minimumRemaining);
    return bucket.used < bucket.ceiling && bucket.reserved < bucket.ceiling - bucket.used - minimumRemaining;
}
export function requestSettlement(current, fact) {
    if (![
        "reserved",
        "unknown",
        "sent",
        "not_sent"
    ].includes(current) || ![
        "unknown",
        "sent",
        "not_sent"
    ].includes(fact)) throw new ContractError("INVALID_REQUEST_STATE");
    if (current === fact) return {
        changed: false,
        state: current,
        usedDelta: 0,
        reservedDelta: 0
    };
    if (current !== "reserved" && current !== "unknown") throw new ContractError("CONFLICTING_REQUEST_FACT");
    return {
        changed: true,
        state: fact,
        usedDelta: fact === "sent" ? 1 : 0,
        reservedDelta: fact === "unknown" ? 0 : -1
    };
}
