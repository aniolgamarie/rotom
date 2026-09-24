import type { ManagedDescriptor } from "./managed-types.js";
export class ManagedObservation {
  constructor(descriptor: ManagedDescriptor, processIdentity: unknown);
  ordinal: number;
  candidateDigest: string;
  denials: Array<{ request_id: string; code: string }>;
  response(record: unknown): void;
  tool(name: string, toolCallId: string, args: unknown, result: unknown): void;
  toolError(name: string, toolCallId: string, code: string): void;
  delivered(request: { ordinal: number; payload: unknown }): void;
  snapshot(): Record<string, unknown>;
}
export function assertObservation(value: unknown, attemptId: string, options?: { failed?: boolean }): Record<string, unknown>;
