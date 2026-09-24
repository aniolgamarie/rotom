export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface ManagedOwner { instance_id: string; manager_activation_id: string; owner_nonce: string }
export interface ManagedDescriptor extends ManagedOwner {
  protocol_version: 1; request_id: string; task_id: string; step_id: string; attempt_id: string;
  continuation_of: string | null; budget_scope_id: string; role_id: string; role_digest: string;
  runtime_digest: string; policy_digest: string; candidate_id: string; snapshot_digest: string;
  cwd: string; source_cwd: string; allowed_tools: string[]; read_roots: string[]; write_roots: string[];
  inherited_denials: Json[]; context_mode: "fresh"; nested: false; executor: "managed-process";
  provider_id: string; model_id: string; model_digest: string; route_id: string; thinking: string;
  request_ceiling: number; turn_ceiling: number; deadline: string; result_schema_digest: string;
  allowed_artifact_ids: string[]; workspace_write_lease_ids: string[]; workspace_identity_digest: string;
  grant_generation: number; allocation_id: string; token_limit?: number; cost_limit?: string;
}
export class ProtocolError extends Error { code: string; exitCode: number; constructor(code: string, exitCode?: number) }
export function isProtocolError(value: unknown): value is ProtocolError;
export function reject(code?: string, exitCode?: number): never;
export function closed(value: unknown, required: string[], optional?: string[]): void;
export function canonical(value: unknown): string;
export function digest(value: unknown): string;
export function clone<T>(value: T): T;
export function text(value: unknown): value is string;
export function sha(value: unknown): value is string;
export function list(value: unknown): value is string[];
export function assertOwner(value: unknown): ManagedOwner;
export function assertDescriptor(value: unknown): ManagedDescriptor;
export function assertEvent(value: unknown): void;
export function assertRule(value: unknown): unknown;
export function assertProcess(value: unknown): void;
