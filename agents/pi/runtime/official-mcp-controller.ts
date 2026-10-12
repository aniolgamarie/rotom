// MCP宿主能力复用原准入和监督transport；没有旧插件或第二model/service执行权威。
import { createOfficialMcpAdmission } from "./official-file-admission.ts";
import { createOfficialMcpFactories } from "./official-mcp.ts";
import { createOfficialMcpStdioTransport } from "./official-mcp-stdio.ts";
import { createOfficialMcpHttpTransport } from "./official-mcp-http.ts";
import { runtimeModule } from "./runtime-module.ts";
import { reject } from "./managed-types.ts";

export async function createOfficialMcpController({ sdk, runtime, admissionOptions, mcpModule,
  checkDeployment, stdioFactory = createOfficialMcpStdioTransport, httpFactory = createOfficialMcpHttpTransport }) {
  const projection = runtime.manifest.native_mcp;
  if (!projection) reject("MCP_CAPABILITY_UNAVAILABLE", 5);
  const selected = Object.values(projection.bindings);
  // 已实现的transport范围显式封闭；不把SSE误当Streamable HTTP，不回退默认OAuth。
  if (selected.some(row => !["stdio", "streamable-http"].includes(row.transport)
      || !["none", "bearer"].includes(row.authentication))) reject("MCP_TRANSPORT_NOT_QUALIFIED", 5);
  if (selected.some(row => row.transport === "streamable-http")) mcpModule ??= await runtimeModule("@earendil-works/pi-mcp", runtime);
  const admission = createOfficialMcpAdmission(admissionOptions);
  const session = admissionOptions.sessionManager.getSessionId(), cwd = admissionOptions.cwd;
  let retired = false, activeContext, closing;
  const check = ctx => {
    if (retired) reject("MCP_CONTEXT_RETIRED", 4);
    if (ctx !== undefined && (ctx.cwd !== cwd || ctx.sessionManager?.getSessionId?.() !== session)) reject("MCP_CONTEXT_STALE", 4);
    if (admissionOptions.sessionManager.getSessionId() !== session) reject("MCP_CONTEXT_STALE", 4);
    if (typeof checkDeployment !== "function") reject("MCP_CONTEXT_UNAVAILABLE", 4);
    checkDeployment();
    if (ctx) activeContext = ctx;
  };
  // none/bearer不应请求OAuth存储；空Authorization公开配置使宿主停止默认OAuth发现。
  const credentials = Object.freeze({
    forServer() { reject("MCP_OAUTH_NOT_QUALIFIED", 5); },
    tokens() { reject("MCP_OAUTH_NOT_QUALIFIED", 5); },
    remove() { reject("MCP_OAUTH_NOT_QUALIFIED", 5); },
  });
  const factories = createOfficialMcpFactories({ sdk, projection, controller: {
    credentials, check,
    openUrl() { reject("MCP_OAUTH_NOT_QUALIFIED", 5); },
    invoke: (request, execute) => { check(request.ctx); return admission.invoke(request, execute); },
    createTransport(entry, requestedCwd, authProvider) {
      check(activeContext);
      if (requestedCwd !== cwd || authProvider !== undefined) reject("MCP_TRANSPORT_BINDING", 4);
      const binding = projection.bindings[entry.name];
      if (binding?.transport === "stdio") return stdioFactory({ runtime, serverName: entry.name, check: () => check(activeContext) });
      if (binding?.transport === "streamable-http") return httpFactory({ runtime, serverName: entry.name, entry, mcpModule, check: () => check(activeContext) });
      reject("MCP_TRANSPORT_NOT_QUALIFIED", 5);
    },
  } });
  return Object.freeze({ ...factories,
    retire() { if (retired) return; retired = true; admission.retire(); },
    close() {
      if (closing) return closing;
      retired = true; admission.retire();
      closing = (async () => {
        const outcomes = await Promise.allSettled([factories.close(), admission.drain()]);
        if (outcomes.some(row => row.status === "rejected")) reject("MCP_RETIRE_INCOMPLETE", 4);
      })();
      return closing;
    },
  });
}
