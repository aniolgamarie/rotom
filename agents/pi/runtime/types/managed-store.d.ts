import type { ManagedOwner } from "./managed-types.js";
export interface TransactionStore {
  transaction<T>(operation: (state: Record<string, unknown>) => T | Promise<T>): Promise<T>;
}
export class ManagedStore implements TransactionStore {
  constructor(options: { root: string; owner: ManagedOwner; authorize: () => Promise<void> });
  readonly path: string;
  transaction<T>(operation: (state: Record<string, unknown>) => T | Promise<T>): Promise<T>;
  close(): Promise<void>;
}
