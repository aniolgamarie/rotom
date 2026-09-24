export interface McpToolOwner { readonly runtime: object; }
export function captureMcpToolOwner(): McpToolOwner;
export function registerMcpTool(name: string, server: string, original: string, execute: (...args: any[]) => any, owner?: McpToolOwner): (...args: any[]) => Promise<any>;
export function unregisterMcpTool(name: string, owner: McpToolOwner): void;
export function registerMcpNamespace(name: string, server: string, execute: (...args: any[]) => any, owner?: McpToolOwner): (...args: any[]) => Promise<any>;
