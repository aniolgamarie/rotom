#!/usr/bin/env python3
"""从已冻结 Git 对象生成可审阅补丁；不联网、不修改来源 checkout。"""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--source", type=Path, required=True)
  args = parser.parse_args()
  root = Path(__file__).resolve().parents[1]
  provenance = json.loads((root / "agents/pi/migration/subagents-manifest.json").read_text())
  source = root / "agents/pi/packages/subagents-vendor"
  output = root / "agents/pi/packages/subagents-patch"
  commit = subprocess.run(["git", "-C", str(args.source), "rev-parse", provenance["commit"] + "^{commit}"], capture_output=True, check=True, text=True).stdout.strip()
  if commit != provenance["commit"]:
    raise ValueError("source commit mismatch")
  original = {}
  # 批量读取对象，不执行源码；来源清单的 blob/hash 同时核对。
  blobs = [row["git_blob"] for row in provenance["files"]]
  raw = subprocess.run(["git", "-C", str(args.source), "cat-file", "--batch"],
    input=("\n".join(blobs) + "\n").encode(), capture_output=True, check=True).stdout
  offset = 0
  for row in provenance["files"]:
    end = raw.index(b"\n", offset)
    blob, kind, size = raw[offset:end].decode().split()
    size = int(size)
    content = raw[end + 1:end + 1 + size]
    offset = end + 2 + size
    if blob != row["git_blob"] or kind != "blob" or hashlib.sha256(content).hexdigest() != row["import_sha256"]:
      raise ValueError("source blob mismatch")
    original[row["source_path"]] = content
  current = {}
  for file in sorted(source.rglob("*")):
    if file.is_symlink():
      raise ValueError("source symlink")
    if file.is_file():
      current[file.relative_to(source).as_posix()] = file.read_bytes()
  patch = []
  records = []
  for name in sorted(original.keys() | current.keys()):
    before, after = original.get(name, b""), current.get(name, b"")
    if before == after:
      continue
    patch.extend(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
      fromfile="a/" + name if name in original else "/dev/null", tofile="b/" + name if name in current else "/dev/null"))
    records.append({"path": name, "before_sha256": hashlib.sha256(before).hexdigest() if name in original else None,
      "after_sha256": hashlib.sha256(after).hexdigest() if name in current else None})
  data = "".join(patch).encode()
  output.mkdir(parents=True, exist_ok=True)
  (output / "managed-executor.patch").write_bytes(data)
  (output / "manifest.json").write_text(json.dumps({"schema_version": 1, "source_url": provenance["source_url"],
    "source_commit": commit, "source_version": "0.19.0", "derived_version": "0.19.0-agentcfg.1",
    "protocol": "agentcfg-managed-executor-v1", "patch": "managed-executor.patch",
    "patch_sha256": hashlib.sha256(data).hexdigest(), "files": records,
    "validation": {"mock": "see docs/acceptance/pi-managed-mock.md", "native": "not-run", "live": "not-run"}}, ensure_ascii=False, indent=2) + "\n")
  print(f"{len(records)} changed files; patch sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
  main()
