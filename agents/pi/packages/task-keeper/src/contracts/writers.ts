import { ContractError, finiteInteger } from "./primitives.ts";

/** The fixed workflow supports one managed writer; configuration is an upper bound. */
export function writerCapacity(limit: number): number {
  finiteInteger(limit);
  return Math.min(1, limit);
}

export function assertWriterAllowed(limit: number): void {
  if (writerCapacity(limit) === 0) throw new ContractError("WRITERS_DISABLED");
}
