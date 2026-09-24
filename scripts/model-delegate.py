#!/usr/bin/env python3
"""冻结运行包的委托 CLI 入口。"""
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.model_delegate_cli import main
from agentcfg.pi_codex_admission import public_rejection

if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception as error:
    # 不回显路径、prompt、后端原始错误或环境值。
    print(json.dumps({"schema_version": 2, "error_code": public_rejection(error) or "DELEGATE_OPERATION_FAILED"}, separators=(",", ":")))
    sys.exit(getattr(error, "exit_code", 6))
