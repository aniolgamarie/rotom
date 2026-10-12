#!/usr/bin/env python3
"""独立明确授权后的官方SDK用户意图探针入口。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_intent_scope_probe import main

if __name__ == "__main__":
  raise SystemExit(main())
