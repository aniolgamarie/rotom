#!/usr/bin/env python3
"""准备/显式运行固定Shell helper探针；native标志不代替用户授权。"""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_shell_probe import main


if __name__ == "__main__":
  sys.exit(main())
