#!/usr/bin/env python3
"""显式准备/预检入口；run必须另获组合探针授权。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_reviewer_sdk_process_probe import main
if __name__ == "__main__":
  raise SystemExit(main())
