#!/usr/bin/env python3
"""显式构建离线候选；不安装、不运行生成的产物。"""
import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_bwrap_build import build_candidate
from agentcfg.schema import ConfigError


class Parser(argparse.ArgumentParser):
  def error(self, message):
    raise ConfigError("pi-bwrap-build-arguments")


def main(argv=None):
  try:
    parser = Parser(prog="build-pi-bwrap", allow_abbrev=False)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    build_candidate(Path(args.sources).absolute(), Path(args.output).absolute())
    print("pi-bwrap: built-not-executed")
    return 0
  except ConfigError:
    print("pi-bwrap: candidate build rejected", file=sys.stderr)
    return 2


if __name__ == "__main__":
  sys.exit(main())
