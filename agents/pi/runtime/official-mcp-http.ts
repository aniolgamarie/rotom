// 公开Streamable HTTP只消费固定受管fetch；不使用SDK的默认网络和OAuth回退。
import { mcpHttpFetch } from "./mcp-http.ts";
import { reject } from "./managed-types.ts";

export function createOfficialMcpHttpTransport({ runtime, serverName, entry, mcpModule, check, fetchFactory = mcpHttpFetch }) {
  const binding = runtime?.manifest?.native_mcp?.bindings?.[serverName];
  if (typeof mcpModule?.StreamableHttpTransport !== "function" || typeof check !== "function" || typeof fetchFactory !== "function"
      || binding?.transport !== "streamable-http" || !["none", "bearer"].includes(binding.authentication)
      || entry?.name !== serverName || entry.config?.type !== "http") reject("MCP_HTTP_TRANSPORT_UNAVAILABLE", 5);
  const events = Object.fromEntries(["Message", "Error", "Close"].map(name => [name, new Set()]));
  let raw, fetch, preparing, closed = false, closePromise, version;
  const live = () => { if (closed) reject("MCP_REQUEST_ABORTED", 4); check(); };
  const emit = (name, value) => { for (const listener of [...events[name]]) listener(value); };
  const prepare = () => preparing ??= (async () => {
    live(); fetch = await fetchFactory(runtime, serverName); live();
    raw = new mcpModule.StreamableHttpTransport({ url: entry.config.url, headers: entry.config.headers,
      fetch: async (input, init) => { live(); const value = await fetch(input, init); live(); return value; },
      openGetStream: false, maxMessageBytes: 1024 * 1024, reconnect: { maxRetries: 0 } });
    // OAuth未接通时不提供authProvider；401只拒绝，不让SDK自动重发业务请求。
    for (const name of Object.keys(events)) {
      if (typeof raw["on" + name] !== "function") reject("MCP_HTTP_TRANSPORT_UNAVAILABLE", 5);
      raw["on" + name](value => {
        if (closed && name !== "Close") return;
        emit(name, name === "Error" ? Error("MCP_HTTP_TRANSPORT_FAILED") : value);
      });
    }
    if (version !== undefined) raw.setProtocolVersion(version);
    live(); return raw;
  })();
  const transport = {
    async start() { live(); try { await (await prepare()).start(); live(); } catch { reject("MCP_HTTP_TRANSPORT_FAILED", 5); } },
    async send(message) { live(); try { await (await prepare()).send(message); live(); } catch { reject("MCP_HTTP_TRANSPORT_FAILED", 5); } },
    setProtocolVersion(value) { live(); version = value; raw?.setProtocolVersion(value); },
    close() {
      if (closePromise) return closePromise;
      closed = true;
      // 不依赖当前session仍存活；在初始化await途中退出也关闭迟到创建的fetch。
      closePromise = (async () => {
        fetch?.close();
        if (preparing) await preparing.catch(() => {});
        fetch?.close();
        try { if (raw) await raw.close(); }
        finally { fetch?.close(); }
      })();
      return closePromise;
    },
  };
  for (const name of Object.keys(events)) transport["on" + name] = listener => {
    live(); if (typeof listener !== "function") reject("MCP_HTTP_TRANSPORT_UNAVAILABLE", 5);
    events[name].add(listener); return () => events[name].delete(listener);
  };
  return Object.freeze(transport);
}
