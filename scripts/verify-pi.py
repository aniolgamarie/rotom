#!/usr/bin/env python3
"""agentcfg Pi 隔离验证与固定范围汇总。"""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_verification import main

if __name__ == "__main__":
  raise SystemExit(main())
