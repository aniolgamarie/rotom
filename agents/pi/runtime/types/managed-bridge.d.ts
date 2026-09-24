import type { ManagedOwner, ManagedDescriptor } from "./managed-types.js";
import type { TransactionStore } from "./managed-store.js";
export interface DispatchReply { attempt_id: string; manager_run_id: string; lease_id: string | null; state: "queued" | "running" | "start_unknown" }
export interface ManagedEndpoint {
  handshake(request: { protocol_version: number; instance_id: string; request_id: string }): unknown;
  preflight(descriptor: ManagedDescriptor): Promise<unknown>;
  dispatch(request: { descriptor: ManagedDescriptor; admission_token: string; idempotency_key: string }): Promise<DispatchReply>;
  inspect(owner: ManagedOwner, runId: string): Promise<unknown>;
  get_result(owner: ManagedOwner, attemptId: string): Promise<unknown>;
  cancelAttempt(owner: ManagedOwner, attemptId: string, reason: string): Promise<unknown>;
  reconcile(owner: ManagedOwner, leaseId: string): Promise<unknown>;
  consume(owner: ManagedOwner, receiptId: string, receiptDigest: string): Promise<unknown>;
}
export class ManagedBridge implements ManagedEndpoint {
  constructor(options: { owner: ManagedOwner; runtime: { identity: string; slice_identity: string; capabilities: string[] };
    store: TransactionStore; executor: unknown; resolve: (descriptor: ManagedDescriptor, options: { purpose: "admission" | "result" }) => Promise<unknown>; listeners: () => number; now?: () => number });
  handshake: ManagedEndpoint["handshake"];
  preflight: ManagedEndpoint["preflight"];
  dispatch: ManagedEndpoint["dispatch"];
  inspect: ManagedEndpoint["inspect"];
  get_result: ManagedEndpoint["get_result"];
  cancelAttempt: ManagedEndpoint["cancelAttempt"];
  reconcile: ManagedEndpoint["reconcile"];
  consume: ManagedEndpoint["consume"];
  event(owner: ManagedOwner, event: unknown): Promise<unknown>;
  publishResult(owner: ManagedOwner, runId: string, receipt: unknown): Promise<unknown>;
  cancel(owner: ManagedOwner, runId: string, reason: string): Promise<unknown>;
  gc(owner: ManagedOwner, runId: string): Promise<unknown>;
}
