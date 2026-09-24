#!/usr/bin/env python3
"""从已验证原始源码生成可审阅的权限插件补丁；不执行上游脚本。"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--source", type=Path, required=True)
  args = parser.parse_args()
  root = Path(__file__).resolve().parents[1]
  original = json.loads((root / "agents/pi/migration/permission-system-manifest.json").read_text())
  before = {row["path"]: row["import_sha256"] for row in original["files"]}
  target = root / "agents/pi/packages/permission-system-vendor"
  after = {path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in target.rglob("*") if path.is_file()}
  patch, changes = [], []
  for name in sorted(before.keys() | after.keys()):
    old = (args.source / name).read_bytes() if name in before else b""
    if name in before and hashlib.sha256(old).hexdigest() != before[name]:
      raise ValueError("source does not match imported integrity tree")
    if before.get(name) == after.get(name):
      continue
    new = (target / name).read_bytes() if name in after else b""
    lines = difflib.unified_diff(old.decode().splitlines(keepends=True), new.decode().splitlines(keepends=True),
      fromfile="a/" + name if name in before else "/dev/null", tofile="b/" + name if name in after else "/dev/null")
    for line in lines:
      patch.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    changes.append({"path": name, "before_sha256": before.get(name), "after_sha256": after.get(name)})
  raw = "".join(patch).encode()
  directory = root / "agents/pi/build"
  (directory / "permission-system.patch").write_bytes(raw)
  manifest = {"schema_version": 1, "source_package": original["package"], "source_version": original["version"], "source_integrity": original["integrity"],
    "patch": "permission-system.patch", "patch_sha256": hashlib.sha256(raw).hexdigest(), "files": changes, "native": "not-run", "live": "not-run"}
  (directory / "permission-system-patch.json").write_text(json.dumps(manifest, indent=2) + "\n")
  print(str(len(changes)) + " changed permission-system files")


if __name__ == "__main__":
  main()
