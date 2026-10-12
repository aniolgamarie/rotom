#!/usr/bin/env python3
"""受信PID1的Shell引导入口；不接受脚本文件、任意argv或模型认证。"""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
# -I -B -S 由受信父侧固定；依赖只来自只读bootstrap挂载，不处理环境或.pth。
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), "/.rotom-shell-bootstrap/python-deps"]
from agentcfg.pi_shell_worker import main


if __name__ == "__main__":
  try:
    main()
  except Exception:
    sys.stderr.write("受管Shell未执行或隔离入口失败；请核对执行身份与后端。\n")
  sys.exit(5)
