export function listenMcpCallback(server: any, options: { serverName?: string; host: string; port: number; path: string; signal?: AbortSignal; startupSignal?: AbortSignal }): Promise<void>;
export function closeMcpListener(server: any): Promise<void>;
export function mcpAppSettings(name: string): { enabled: boolean; host_port?: number; proxy_port?: number; max_seconds?: number };
export function validateMcpAppResource(name: string, resource: unknown): void;
export function listenMcpApps(host: any, proxy: any, options: { serverName: string; port?: number; signal?: AbortSignal; startupSignal?: AbortSignal; stop?: () => void; drain?: () => Promise<unknown> }): Promise<void>;
