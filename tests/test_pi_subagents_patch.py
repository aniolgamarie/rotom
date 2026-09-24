"""冻结来源与派生补丁的一致性；只读取仓库源码，不执行宿主或源码脚本。"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vendor_tree_matches_frozen_sources_plus_explicit_patch():
  source = json.loads((ROOT / "agents/pi/migration/subagents-manifest.json").read_text())
  directory = ROOT / "agents/pi/packages/subagents-patch"
  patch = json.loads((directory / "manifest.json").read_text())
  assert patch["source_commit"] == source["commit"]
  assert hashlib.sha256((directory / patch["patch"]).read_bytes()).hexdigest() == patch["patch_sha256"]
  original = {row["source_path"]: row["import_sha256"] for row in source["files"]}
  expected = dict(original)
  for change in patch["files"]:
    assert change["before_sha256"] == original.get(change["path"])
    if change["after_sha256"] is None:
      expected.pop(change["path"])
    else:
      expected[change["path"]] = change["after_sha256"]
  vendor = ROOT / "agents/pi/packages/subagents-vendor"
  actual = {path.relative_to(vendor).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in vendor.rglob("*") if path.is_file()}
  assert actual == expected
  assert patch["validation"]["native"] == "not-run"
  assert patch["validation"]["live"] == "not-run"
