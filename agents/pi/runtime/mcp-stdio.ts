// MCP 仅声明服务绑定，物理 IO 与其他普通进程共用监督传输。
import { randomUUID } from "node:crypto";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { reject } from "./managed-types.ts";
import { SupervisedStdioTransport } from "./supervised-stdio.ts";

export class BoundStdioTransport extends SupervisedStdioTransport {
  constructor(runtime, serverName, options = {}) { super(runtime, serverName, { ...options, errorPrefix: "MCP" }); }
  binding() {
    requireOrdinaryHelper(this.runtime, "pi-mcp", this.ticket?.manager_run_id ?? null);
    const selected = this.runtime.manifest.options.mcp?.servers?.[this.serverName];
    const command = this.runtime.manifest.options.external_tools?.[selected?.command_ref];
    const root = this.runtime.manifest.options.paths?.roots?.[command?.project_root];
    if (!selected?.command_ref || selected.transport !== "stdio" || command?.interactive !== true || !root?.path) reject("MCP_STDIO_BINDING_REQUIRED", 2);
    return { selected, cwd: root.path };
  }
  async prepare() {
    this.binding();
    const ticket = await this.runtime.supervisor.call("ordinary_mcp_stdio_prepare", { operation_id: "mcp-" + randomUUID(), server_name: this.serverName });
    if (ticket.execution_class !== "service" || ticket.service_name !== this.serverName) {
      if (ticket.kind === "command" && ticket.lease_id && ticket.operation_id) await this.runtime.ordinaryOperations.abort(ticket);
      reject("MCP_STDIO_SERVICE_UNVERIFIED", 5);
    }
    return ticket;
  }
}
