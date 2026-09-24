#!/usr/bin/env python3
"""一次性文件操作进程；实际IO由监督者的固定目录句柄执行。"""
import argparse
import os
from pathlib import Path
import sys
import uuid
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_control import request

if __name__ == "__main__":
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--operation", required=True)
  args = parser.parse_args()
  try:
    reply = request(os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"], os.environ["AGENTCFG_SUPERVISOR_CAPABILITY"],
      {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": "ordinary_perform", "args": {"operation_id": args.operation}})
    sys.exit(0 if reply.get("ok") else reply.get("exit_code", 6))
  except Exception:
    sys.exit(6)
