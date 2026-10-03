"""只生成原生规则基线的隔离输入，不执行固定样本中的命令。"""

import hashlib
import json
from pathlib import Path
import tomllib

from agentcfg.deployment import json_bytes


FROZEN_DIGEST = "4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6"


def prepare_baseline_input(root: Path, work: Path):
  fixtures = root / "tests/fixtures/omp/permission-control"
  digest = hashlib.sha256()
  for name in ("fixture-schema.json", "cases.jsonl", "labels.json"):
    digest.update(name.encode() + b"\0" + (fixtures / name).read_bytes() + b"\0")
  if digest.hexdigest() != FROZEN_DIGEST:
    raise AssertionError("frozen permission fixture changed")
  runtime = tomllib.loads((root / "profiles/omp-kernel.toml").read_text())["agent_options"]["runtime"]
  settings = {name: runtime[name.split(".")[0]][name.split(".")[1]] for name in (
    "tools.approvalMode", "tools.approval", "bash.allowCompoundCommands", "bash.patterns")}
  cases = [json.loads(line) for line in (fixtures / "cases.jsonl").read_text().splitlines()]
  if len(cases) != 240:
    raise AssertionError("frozen permission fixture changed")
  value = {"settings": settings, "cases": cases, "fixtureDigest": FROZEN_DIGEST,
    "recipeDigest": hashlib.sha256(json_bytes(settings)).hexdigest()}
  measured = json.loads((fixtures / "native-baseline.json").read_bytes())
  if measured["fixtureDigest"] != value["fixtureDigest"] or measured["recipeDigest"] != value["recipeDigest"]:
    raise AssertionError("native baseline input changed; explicitly remeasure before updating evidence")
  value["measuredCounts"] = measured["counts"]
  value["measuredResults"] = measured["results"]
  target = work / "permission-test-fixtures/baseline-input.json"
  target.parent.mkdir(exist_ok=True)
  target.write_bytes(json_bytes(value))
  return value
