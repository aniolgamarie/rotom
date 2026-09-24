import { requireOrdinaryHelper } from "@agentcfg/pi-runtime/capability-policy";
import { digest } from "@agentcfg/pi-runtime/managed-types";
import { pluginSettings } from "@agentcfg/pi-runtime/plugin-settings";
import type { McpConfig, ServerDefinition } from "./types.ts";
function runtime(): any {
  const current = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  requireOrdinaryHelper(current, "pi-mcp");
  if (!current.manifest.mcp_config) throw new Error("MCP_BINDINGS_REQUIRED");
  return current;
}
export function declaredMcpConfiguration(): McpConfig {
  return structuredClone(runtime().manifest.mcp_config);
}
export function declaredMcpServer(name: string, definition: ServerDefinition): void {
  const selected = runtime().manifest.mcp_config.mcpServers[name];
  if (!selected || selected.command !== definition.command || selected.url !== definition.url
      || selected.httpTransport !== definition.httpTransport || selected.auth !== definition.auth
      || selected.bearerTokenEnv !== definition.bearerTokenEnv || definition.socket
      || JSON.stringify(selected.args ?? []) !== JSON.stringify(definition.args ?? [])
      || definition.env || definition.pluginDataDir || definition.headers || definition.bearerToken
      || definition.requestHeadersCommand || JSON.stringify(definition.oauth) !== JSON.stringify(selected.oauth)) throw new Error("MCP_SERVICE_UNSELECTED");
}

export function declaredOAuthServer(name: string, url: string): ServerDefinition {
  const selected = runtime().manifest.mcp_config.mcpServers[name];
  if (!selected || selected.url !== url || selected.auth !== "oauth" || !selected.oauth) throw new Error("MCP_OAUTH_UNSELECTED");
  return structuredClone(selected);
}

export function assertOAuthConfiguration(name: string, url: string, config: Record<string, unknown>): void {
  const selected = declaredOAuthServer(name, url).oauth as Record<string, unknown>;
  const expected = { ...selected };
  if (typeof expected.clientSecret === "string") {
    expected.clientSecret = resolveOAuthClientSecret(expected.clientSecret);
  }
  if (Object.keys(config).length !== Object.keys(expected).length
      || Object.entries(expected).some(([key, value]) => config[key] !== value)) throw new Error("MCP_OAUTH_CONFIG_MISMATCH");
}

export function resolveOAuthClientSecret(reference: string): string {
  const match = /^\$\{(AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16})\}$/.exec(reference);
  const value = match ? process.env[match[1]!] : undefined;
  if (!value || /[\r\n\0]/.test(value)) throw new Error("MCP_OAUTH_CREDENTIAL_REQUIRED");
  return value;
}

export function mcpAuthenticationAccount(name: string): string {
  // 清理私有凭据不产生辅助模型／网络请求，不因正在关闭的 listener 自身而拒绝清理。
  const settings = pluginSettings("pi-mcp", "mcp") as { servers?: Record<string, { oauth?: unknown }> };
  const current = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  const server = current.manifest.mcp_config?.mcpServers?.[name];
  if (!server || !settings.servers?.[name]) throw new Error("MCP_AUTH_ACCOUNT_UNSELECTED");
  return "sha256-" + digest({ name, url: server.url ?? null, auth: server.auth ?? false,
    oauth: server.oauth ?? false, binding: settings.servers[name]?.oauth ?? null });
}

export function assertOAuthAuthorizationUrl(name: string, url: URL): void {
  const current = runtime();
  const definition = current.manifest.mcp_config.mcpServers[name];
  const binding = current.manifest.options.mcp.servers[name];
  const origins = [definition?.url, ...(binding?.oauth?.allowed_origins ?? [])].map(value => new URL(value).origin);
  if (definition?.auth !== "oauth" || url.protocol !== "https:" || url.username || url.password || !origins.includes(url.origin)) throw new Error("MCP_OAUTH_AUTHORIZATION_ORIGIN");
}
