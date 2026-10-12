#!/usr/bin/env python3
"""独立准备或显式执行产品Shell合成验收；native标志不代替授权。"""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_shell_product_probe import main


if __name__ == "__main__":
  sys.exit(main())
