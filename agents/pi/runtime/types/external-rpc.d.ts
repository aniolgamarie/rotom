export function registerExternalRpc(events: any, bridge: any): () => void;
export class ExternalClient {
  constructor(events: any, options?: { timeout?: number });
  call(method: string, args: unknown): Promise<any>;
}
