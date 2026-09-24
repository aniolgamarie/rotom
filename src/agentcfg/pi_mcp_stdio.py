"""长期 stdio 服务沿用同一监督者，容量与有限执行任务分开。"""
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict


def prepare_stdio(operations, principal, args):
  closed(args, ("operation_id", "server_name"))
  host = operations.host; manifest = host.manifest()
  if principal.role != "manager" or "pi-mcp" not in manifest.get("plugins", []): raise Conflict("MCP_STDIO_CONTEXT")
  if not isinstance(args["server_name"], str): raise ConfigError("pi-mcp-server")
  selected = manifest["options"].get("mcp", {}).get("servers", {}).get(args["server_name"])
  if not selected or selected["transport"] != "stdio": raise ConfigError("pi-mcp-stdio-binding")
  if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 180: raise ConfigError("pi-operation-id")
  name = selected["command_ref"]
  binding = manifest["options"].get("external_tools", {}).get(name)
  roots = manifest["options"].get("paths", {}).get("roots", {})
  if not binding or not binding.get("interactive") or binding.get("project_root") not in roots: raise ConfigError("pi-mcp-stdio-binding")
  return operations.commands.prepare(principal, {"operation_id": "mcp-stdio:" + args["operation_id"], "role_id": "main", "cwd": roots[binding["project_root"]]["path"],
    "tool_name": "bash", "input": {"command": "agentcfg:" + name}}, service_name=args["server_name"])
