export function webServiceSelected(name: string): boolean;
export function webFetchFor(name: string): typeof fetch;
export function runWebOperation<T>(label: string, signal: AbortSignal | undefined, callback: (signal: AbortSignal) => Promise<T>): Promise<T>;
export function trackWebWork<T>(promise: Promise<T>): Promise<T>;
export function withWebProxy<T>(proxy: string | undefined, callback: () => T): T;
export function webAuthenticatedFetch(profile: string, input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
export function webProxySelection(): { specified: boolean; url: string | null };
