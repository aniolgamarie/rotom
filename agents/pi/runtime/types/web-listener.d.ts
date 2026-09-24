import type { IncomingMessage, Server, ServerResponse } from "node:http";
export function webCuratorSettings(): { enabled: boolean; browser_network: "user-browser"; port?: number; max_seconds?: number };
export function createWebCuratorServer(handler: (request: IncomingMessage, response: ServerResponse) => Promise<void>): Server;
export function webCuratorAsset(server: Server): string;
export function listenWebCurator(server: Server, signal?: AbortSignal): Promise<void>;
export function closeWebCurator(server: Server): Promise<void>;

export function webCuratorUrl(server: Server, token: string): string;
export function webCuratorLinkAllowed(url: string): boolean;
