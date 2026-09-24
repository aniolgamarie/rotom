import type { ManagedDescriptor } from "./managed-types.js";
export function createGuardedTools(options: { descriptor: ManagedDescriptor; context: unknown; supervisor: unknown;
  submitResult?: (value: unknown, association: { tool_call_id: string; value_digest: string }) => Promise<void> }): unknown[];
