import type { ManagedEndpoint } from "./managed-bridge.js";
export interface ManagedEventBus { on(channel: string, handler: (value: unknown) => void): () => void; emit(channel: string, value: unknown): void }
export function listenerCount(events: ManagedEventBus): number;
export function registerManagedRpc(events: ManagedEventBus, bridge: ManagedEndpoint): () => void;
export class ManagedClient {
  constructor(events: ManagedEventBus, options?: { timeout?: number });
  call(method: "handshake" | "preflight" | "dispatch" | "inspect" | "get_result" | "cancel" | "reconcile" | "consume", args: unknown): Promise<unknown>;
}
