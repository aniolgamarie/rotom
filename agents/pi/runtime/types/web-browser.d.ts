export function webBrowserDeclared(name?: string): boolean;
export function registerWebCookieReader(reader: (name: string, url: URL, signal?: AbortSignal) => Promise<string | undefined>): void;
export function webBrowserCookieHeader(name: string, url: URL, signal?: AbortSignal): Promise<string>;
export interface BrowserSnapshot {
  snapshot_id: string;
  directory: string;
  profile: string;
  browser: string;
  sidecars: string[];
  release(): Promise<void>;
  password(): string;
}
export function webBrowserSnapshot(options: { binding?: string; browser?: string; profile?: string; hosts: string[]; signal?: AbortSignal }): Promise<BrowserSnapshot>;
