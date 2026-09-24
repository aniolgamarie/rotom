#!/usr/bin/env python3
"""冻结批次客户端；不启动执行器。"""
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.model_delegate_batch import main
if __name__ == "__main__":
  try: sys.exit(main())
  except Exception as error:
    print(json.dumps({"schema_version": 2, "error_code": "DELEGATE_BATCH_FAILED"}))
    sys.exit(getattr(error, "exit_code", 6))
