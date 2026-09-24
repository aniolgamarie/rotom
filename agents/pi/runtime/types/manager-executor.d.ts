import type { ManagedDescriptor } from "./managed-types.js";
import type { TransactionStore } from "./managed-store.js";
export class ManagerExecutor {
  constructor(options: { manager: unknown; backend: unknown; store: TransactionStore; pi: unknown; context: () => unknown });
  dispatch(descriptor: ManagedDescriptor, run: { manager_run_id: string }): Promise<{ attempt_id: string; lease_id: string; state: "queued" | "running" }>;
  acknowledge(runId: string): void;
  cancel(leaseId: string): Promise<void>;
  reconcile(leaseId: string, owner: { instance_id: string }): Promise<unknown>;
  verify_result(leaseId: string, artifactDigest: string): Promise<unknown>;
  gc(runId: string): Promise<void>;
}
