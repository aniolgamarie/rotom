#!/usr/bin/env python3
"""显式导入本地候选，输出非秘密来源声明；不构建或激活。"""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agentcfg.pi_bwrap_import import import_candidate
from agentcfg.schema import ConfigError


class Parser(argparse.ArgumentParser):
  def error(self, message):
    raise ConfigError("pi-bwrap-import-arguments")


def main(argv=None):
  try:
    parser = Parser(prog="import-pi-bwrap", allow_abbrev=False)
    parser.add_argument("--repository", default=str(ROOT))
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--sources", required=True)
    args = parser.parse_args(argv)
    source = import_candidate(Path(args.repository).absolute(), Path(args.candidate).absolute(), Path(args.sources).absolute())
    print(json.dumps(source, sort_keys=True, separators=(",", ":")))
    return 0
  except ConfigError:
    print("pi-bwrap: candidate import rejected", file=sys.stderr)
    return 2


if __name__ == "__main__":
  sys.exit(main())
