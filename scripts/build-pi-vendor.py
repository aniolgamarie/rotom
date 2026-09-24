#!/usr/bin/env python3
"""显式构建已迁入仓库的 Pi 源归档；不下载、不执行包生命周期。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agentcfg.pi_vendor import build_archive, read_inputs
from agentcfg.storage import Tree
from agentcfg.deployment import json_bytes


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  recipes, _ = read_inputs(args.repository)
  built = {identity: build_archive(args.repository, recipe) for identity, recipe in recipes["sources"].items()}
  with Tree(args.output.absolute(), create=True) as output:
    records = {}
    for identity, (raw, record) in built.items():
      record["vendor_path"] = identity + "-" + record["archive_digest"] + ".tgz"
      output.write_state(record["vendor_path"], raw)
      records[identity] = record
    output.write_state("sources.json", json_bytes({"schema_version": 1, "sources": records}))
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception:
    print("Pi vendor 输入不完整或不安全；未生成可发布来源记录", file=sys.stderr)
    sys.exit(2)
