#!/usr/bin/env python3
"""固定的stdio工具代理；只继承当前委托能力，不加载全局MCP资源。"""

import argparse
import json
import math
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



def _reject_json():
  error = ValueError("DELEGATE_PROTOCOL_REJECTED")
  try:
    raise error
  except ValueError:
    # 仅清自有异常，避免保留解析正文或 caller 正在处理的秘密异常。
    error.__context__ = None
    error.__cause__ = None
    raise


def _json_pairs(items):
  value = {}
  for key, child in items:
    if key in value: _reject_json()
    value[key] = child
  return value


def _json_constant(_value): _reject_json()


def _json_float(value):
  result = float(value)
  if not math.isfinite(result): _reject_json()
  return result


def _decode_json(raw):
  if type(raw) is not bytes or len(raw) > 1024 * 1024: _reject_json()
  failed = False
  try:
    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_json_pairs,
      parse_constant=_json_constant, parse_float=_json_float)
  except (ValueError, UnicodeError, RecursionError):
    failed = True
  if failed: _reject_json()
  return value


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--input", type=Path, required=True)
  args = parser.parse_args()
  with Tree(args.input.parent) as tree: raw = tree.read(args.input.name, max_bytes=1024 * 1024)
  value = _decode_json(raw[0]); data = value["input"]; request, grant = data["request"], data["grant"]
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
      message = _decode_json(frame)
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
