import type { ManagedRequest } from "../contracts/requests.ts";
export interface LedgerLimits { model_requests: number; model_turns: number; deadline: string; token_limit?: number; cost_limit?: string }
export interface Usage { usage_id: string | null; input_tokens: number | null; output_tokens: number | null; cost: string | null; never_sent?: boolean }
export class RequestLedger {
  constructor(options: { store: { transaction(operation: (state: Record<string, any>) => unknown): Promise<unknown> };
    task_id: string; budget_scope_id: string; limits: LedgerLimits; minimum_remaining?: number; now?: () => number;
    verify(request: ManagedRequest): { valid: boolean; route_id: string; grant_digest: string; bounds_certified?: boolean } });
  reserve(request: ManagedRequest): Promise<any>;
  mark_sent(requestId: string): Promise<any>;
  mark_unknown(requestId: string): Promise<any>;
  settle(requestId: string, usage: Usage): Promise<any>;
}
