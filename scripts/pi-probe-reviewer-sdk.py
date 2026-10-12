#!/usr/bin/env python3
"""自有显式探针入口；默认prepare/preflight不执行Node或官方SDK。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_reviewer_sdk_probe import main

if __name__ == "__main__":
  raise SystemExit(main())
