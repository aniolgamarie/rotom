#!/usr/bin/env python3
"""纯Pi合成性能采集器；仅显式 run 子命令可启动固定官方CLI。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentcfg.pi_benchmark import main


if __name__ == "__main__":
  raise SystemExit(main())
