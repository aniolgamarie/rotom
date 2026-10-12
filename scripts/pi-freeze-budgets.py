#!/usr/bin/env python3
"""从显式 JSON 原子新建数值预算；不执行样本、不采集候选、不签发授权。"""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.deployment import json_bytes
from agentcfg.pi_budgets import freeze_budget
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, StateError, Tree
from agentcfg.paths import PathError


class Parser(argparse.ArgumentParser):
  def error(self, message):
    raise ConfigError("pi-budget-arguments")


def _object(pairs):
  value = {}
  for key, item in pairs:
    if key in value: raise ConfigError("pi-budget-json")
    value[key] = item
  return value


def _constant(value):
  raise ConfigError("pi-budget-json")


def _read(path):
  path = Path(path).absolute()
  with Tree(path.parent, private=False) as tree:
    raw = tree.read(path.name, max_bytes=1024 * 1024)
  if raw is None: raise StateError()
  try:
    return json.loads(raw[0], object_pairs_hook=_object, parse_constant=_constant)
  except (ValueError, UnicodeError):
    raise ConfigError("pi-budget-json") from None


def main(argv=None):
  try:
    parser = Parser(prog="pi-freeze-budgets", allow_abbrev=False)
    for option in ("baseline", "tolerances", "output"): parser.add_argument("--" + option, required=True)
    parser.add_argument("--revision", type=int, required=True)
    args = parser.parse_args(argv)
    budget = freeze_budget(_read(args.baseline), _read(args.tolerances), revision=args.revision)
    output = Path(args.output).absolute()
    with Tree(output.parent, private=False) as tree:
      tree.write_new(output.name, json_bytes(budget))
    return 0
  except ConfigError:
    print("pi-budget: invalid input", file=sys.stderr); return 2
  except Conflict:
    print("pi-budget: output conflict", file=sys.stderr); return 4
  except (OSError, StateError, PathError):
    print("pi-budget: filesystem failure", file=sys.stderr); return 6


if __name__ == "__main__":
  sys.exit(main())
