// 同进程 HTTP listener 由现有 manager 持有；父 Pi 进程本身仍由 supervisor 监督。
import { EventEmitter } from "node:events";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";

import { listeners, listenOwnedServer, closeOwnedListener } from "./owned-listener.ts";
function callbackBinding(runtime, options) {
  requireOrdinaryHelper(runtime, "pi-mcp");
  const binding = runtime.manifest.options.mcp?.servers?.[options.serverName];
  if (binding?.authentication !== "oauth" || binding.oauth?.grant_type !== "authorization_code") reject("MCP_CALLBACK_UNSELECTED", 4);
  const url = new URL(binding.oauth.redirect_uri);
  const host = url.hostname === "localhost" ? "127.0.0.1" : url.hostname.replace(/^\[|\]$/g, "");
  if (url.protocol !== "http:" || !["127.0.0.1", "::1"].includes(host) || !url.port || url.username || url.password || url.search || url.hash
      || options.host !== host || options.port !== Number(url.port) || options.path !== url.pathname) reject("MCP_CALLBACK_ENDPOINT", 4);
  return runtime.manifest.options.mcp.callback_max_seconds ?? 600;
}

export async function listenMcpCallback(server, options, dependencies = {}) {
  const runtime = dependencies.runtime ?? globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  const seconds = callbackBinding(runtime, options);
  return listenOwnedServer(server, options, seconds, dependencies);
}

export function mcpAppSettings(name, runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")]) {
  requireOrdinaryHelper(runtime, "pi-mcp");
  if (!Object.hasOwn(runtime.manifest.options.mcp?.servers ?? {}, name) || runtime.manifest.options.mcp.apps?.enabled !== true
      || runtime.manifest.options.mcp.apps.browser_network !== "user-browser") reject("MCP_APPS_NOT_SELECTED", 4);
  return runtime.manifest.options.mcp.apps;
}

export function validateMcpAppResource(name, resource) {
  const settings = mcpAppSettings(name), allowed = new Set((settings.allowed_browser_origins ?? []).map(value => new URL(value).origin));
  const meta = resource?.meta ?? {};
  for (const domains of Object.values(meta.csp ?? {})) {
    if (!Array.isArray(domains)) reject("MCP_APPS_CSP_UNSELECTED", 4);
    for (const value of domains) {
      let url;
      try { url = new URL(value); } catch { reject("MCP_APPS_CSP_UNSELECTED", 4); }
      if (url.protocol !== "https:" || url.username || url.password || /[\s;'"*]/.test(value) || !allowed.has(url.origin)) reject("MCP_APPS_CSP_UNSELECTED", 4);
    }
  }
  if (Object.keys(meta.permissions ?? {}).some(key => !(settings.permissions ?? []).includes(key))) reject("MCP_APPS_PERMISSION_UNSELECTED", 4);
}

export async function listenMcpApps(host, proxy, options, dependencies = {}) {
  const runtime = dependencies.runtime ?? globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  const settings = mcpAppSettings(options.serverName, runtime);
  if (options.port !== undefined && options.port !== (settings.host_port ?? 0)) reject("MCP_APPS_PORT_UNSELECTED", 4);
  const servers = [host, proxy], ports = [settings.host_port ?? 0, settings.proxy_port ?? 0], bound = new Set();
  if (ports[0] !== 0 && ports[0] === ports[1]) reject("MCP_APPS_PORT_CONFLICT", 2);
  class Pair extends EventEmitter {
    get listening() { return servers.some(server => server.listening); }
    listen(_port, address, done) {
      void (async () => {
        for (const [index, server] of servers.entries()) {
          await new Promise((resolve, fail) => {
            const error = () => fail(new Error("MCP_APPS_BIND_FAILED"));
            server.once("error", error);
            try { server.listen(ports[index], address, () => { server.off("error", error); bound.add(server); resolve(); }); }
            catch { server.off("error", error); fail(new Error("MCP_APPS_BIND_FAILED")); }
          });
        }
        done();
      })().catch(() => this.emit("error", new Error("MCP_APPS_BIND_FAILED")));
    }
    close(done) {
      options.stop?.();
      void Promise.all(servers.map(server => new Promise((resolve, fail) => {
        try { server.close(error => error && !(error.code === "ERR_SERVER_NOT_RUNNING" && !bound.has(server)) ? fail(error) : resolve()); }
        catch (error) { fail(error); }
      }))).then(async () => {
        await options.drain?.();
        this.emit("close"); done();
      }).catch(() => done(new Error("MCP_LISTENER_TERMINATION_UNKNOWN")));
    }
    closeAllConnections() { for (const server of servers) server.closeAllConnections?.(); }
  }
  const pair = new Pair();
  for (const server of servers) {
    if (listeners.has(server)) reject("MCP_LISTENER_MANAGER_REQUIRED", 5);
    server.on("connection", socket => pair.emit("connection", socket));
    // 监听前错误由 bind promise 处理；运行中错误交给同一资源所有者。
    server.on("error", () => { if (bound.has(server)) pair.emit("error", new Error("MCP_APPS_LISTENER_FAILED")); });
    listeners.set(server, { close: () => closeMcpListener(pair) });
  }
  await listenOwnedServer(pair, { host: "127.0.0.1", port: 0, kind: "mcp-app", description: "MCP App", signal: options.signal,
    startupSignal: options.startupSignal }, settings.max_seconds ?? 1800, dependencies);
}

export function closeMcpListener(server) { return closeOwnedListener(server, "MCP"); }
