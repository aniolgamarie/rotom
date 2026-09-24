"""无外部依赖的stdio MCP示例，只处理初始化、工具发现和echo。"""

import json
import sys

PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = {PROTOCOL, "2025-06-18", "2025-03-26", "2024-11-05"}
TOOL = {"name": "echo", "description": "Return exactly the supplied text; local fixture only.",
  "inputSchema": {"type": "object", "additionalProperties": False,
    "required": ["text"], "properties": {"text": {"type": "string"}}}}


def error(identity, code, message):
  return {"jsonrpc": "2.0", "id": identity, "error": {"code": code, "message": message}}


def handle(request):
  if (not isinstance(request, dict) or request.get("jsonrpc") != "2.0"
      or not isinstance(request.get("method"), str)):
    return error(None, -32600, "Invalid request")
  if "id" not in request:
    return None
  identity = request["id"]
  if identity is not None and type(identity) not in (str, int):
    return error(None, -32600, "Invalid request")
  method, params = request["method"], request.get("params", {})
  if not isinstance(params, dict):
    return error(identity, -32602, "Invalid params")
  if method == "initialize":
    version = params.get("protocolVersion")
    if version is not None and not isinstance(version, str):
      return error(identity, -32602, "Invalid protocol version")
    result = {"protocolVersion": version if version in SUPPORTED_PROTOCOLS else PROTOCOL,
      "capabilities": {"tools": {}}, "serverInfo": {"name": "rotom-echo-mcp", "version": "1.0.0"}}
  elif method == "ping":
    result = {}
  elif method == "tools/list":
    result = {"tools": [TOOL]}
  elif method == "tools/call":
    arguments = params.get("arguments")
    if (params.get("name") != "echo" or not isinstance(arguments, dict)
        or set(arguments) != {"text"} or not isinstance(arguments["text"], str)):
      return error(identity, -32602, "Invalid echo arguments")
    result = {"content": [{"type": "text", "text": arguments["text"]}], "isError": False}
  else:
    return error(identity, -32601, "Method not found")
  return {"jsonrpc": "2.0", "id": identity, "result": result}


def serve(source, target):
  for line in source:
    try:
      request = json.loads(line)
      response = handle(request)
    except (ValueError, TypeError):
      response = error(None, -32700, "Parse error")
    if response is not None:
      target.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
      target.flush()


if __name__ == "__main__":
  serve(sys.stdin, sys.stdout)
