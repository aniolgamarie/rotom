export function readseekWorker(): any;
export function readseekSettings(): Record<string, unknown>;
export function readseekAvailability(): { available: boolean; reason?: string };
export function wrapReadseekTool<T>(tool: T): T;
export function recordReadseekAnchor(action: string, path?: string): void;
