#!/usr/bin/env python3
"""Pi runtime 私有客户端，不接收 shell 字符串或任意 PID。"""

import json
import os
from pathlib import Path
import sys

# 已密封运行包不能在导入时生成 __pycache__。
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_control import read_frame, request


def main():
  result = request(os.environ["AGENTCFG_SUPERVISOR_ENDPOINT"], os.environ["AGENTCFG_SUPERVISOR_CAPABILITY"], read_frame(sys.stdin.buffer))
  sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception:
    sys.stdout.write('{"schema_version":1,"ok":false,"exit_code":4,"error":"PI_CONTROL_UNAVAILABLE"}\n')
    sys.exit(4)
