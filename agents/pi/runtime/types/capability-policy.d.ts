export function requireOrdinaryHelper(runtime: any, capability: string, serviceRunId?: string | null): void;
export function compactionOwner(manifest: any): "native" | "smart-compact";
export function mayTransformHistory(runtime: any): boolean;
export function assertSessionBoundary(runtime: any): Promise<void>;
