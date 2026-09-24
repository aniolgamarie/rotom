export function webConfigDirectory(): string;
export function webConfig(): Record<string, unknown>;
export function webCredentialDeclared(reference: unknown): boolean;
export function webCredential(reference: unknown, signal?: AbortSignal): string;

export function webConfigurationIdentity(): object;
export function assertWebOperation(): void;
export function webCacheDirectory(create: boolean): string | null;
export function webCredentialDocument(reference: unknown, signal?: AbortSignal): string;
