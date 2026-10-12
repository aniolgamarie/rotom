import { ContractError, finiteInteger } from "./primitives.mjs";
export function writerCapacity(limit) {
    finiteInteger(limit);
    return Math.min(1, limit);
}
export function assertWriterAllowed(limit) {
    if (writerCapacity(limit) === 0) throw new ContractError("WRITERS_DISABLED");
}
