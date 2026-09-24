#!/usr/bin/env python3
"""固定的stdio工具代理；只继承当前委托能力，不加载全局MCP资源。"""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.activity import digest
from agentcfg.model_delegate import validate_record
from agentcfg.pi_control import request as control_request
from agentcfg.pi_delegate_mcp import DelegateMcp
from agentcfg.storage import Conflict, Tree


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--input", type=Path, required=True)
  args = parser.parse_args()
  with Tree(args.input.parent) as tree: raw = tree.read(args.input.name, max_bytes=1024 * 1024)
  value = json.loads(raw[0]); data = value["input"]; request, grant = data["request"], data["grant"]
  validate_record("request-v2", request)
  if (value["schema_version"] != 2 or request["backend"] != "codex" or str(Path.cwd()) != request["cwd"]
      or data["definition_digest"] != digest({key: item for key, item in data.items() if key != "definition_digest"})):
    raise Conflict("DELEGATE_MCP_IDENTITY")
  endpoint = os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"]
  capability = os.environ.pop("AGENTCFG_DELEGATE_MCP_CAPABILITY")
  def control(method, arguments):
    reply = control_request(endpoint, capability, {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": method, "args": arguments})
    if reply.get("ok") is not True: raise Conflict("DELEGATE_MCP_CONTROL_REJECTED")
    return reply["result"]
  owner = control("handshake", {})
  if owner.get("role") != "worker" or owner.get("lease_id") != request["lease_id"] or owner.get("runtime_identity") != request["runtime_identity"]:
    raise Conflict("DELEGATE_MCP_IDENTITY")
  server = DelegateMcp(request, grant, control)
  while True:
    frame = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if not frame: return 0
    if len(frame) > 1024 * 1024 or not frame.endswith(b"\n"): return 2
    try:
      message = json.loads(frame)
      reply = server.handle(message)
    except Exception:
      reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "DELEGATE_PROTOCOL_REJECTED"}}
    if reply is not None:
      output = (json.dumps(reply, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
      if len(output) > 1024 * 1024: return 2
      sys.stdout.buffer.write(output); sys.stdout.buffer.flush()


if __name__ == "__main__":
  try: sys.exit(main())
  except Exception:
    sys.stderr.write("DELEGATE_MCP_FAILED\n")
    sys.exit(5)
