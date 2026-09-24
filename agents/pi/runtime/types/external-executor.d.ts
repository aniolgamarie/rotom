import type { TransactionStore } from "./managed-store.js";
export function assertDelegateReceipt(result: unknown, request: unknown, physical: unknown): any;
export class ExternalBridge {
  constructor(options: { runtime: any; manager: any; store: TransactionStore; pi: any; getContext: () => any; pause?: (milliseconds: number) => Promise<void>; now?: () => number });
  submit_delegate(envelope: unknown): Promise<any>;
  get_delegate_result(owner: unknown, runId: string): Promise<any>;
  cancel_delegate(owner: unknown, runId: string): Promise<any>;
  submit_batch(owner: unknown, batchId: string, items: unknown[]): Promise<any>;
  readonly owner: any;
  authorize(owner?: unknown): Promise<void>;
  get_batch(owner: unknown, batchId: string): Promise<any>;
  cancel_batch(owner: unknown, batchId: string): Promise<any>;
  close(): Promise<void>;
}
