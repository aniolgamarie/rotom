#!/usr/bin/env python3
"""代码快照的一次性监督入口；真实IO由监督者在当前租约下执行。"""
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
    result = request(os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"], os.environ["AGENTCFG_SUPERVISOR_CAPABILITY"],
      {"schema_version": 1, "request_id": uuid.uuid4().hex, "method": "ordinary_checkpoint_perform", "args": {"operation_id": args.operation}})
    sys.exit(0 if result.get("ok") and result["result"]["status"] == "completed" else 5)
  except Exception:
    sys.exit(6)
