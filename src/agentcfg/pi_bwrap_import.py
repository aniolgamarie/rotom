"""显式导入经验证本地候选；不构建、不执行，不提交或激活部署声明。"""
import hashlib
import json
from pathlib import Path

from . import pi_built_assets as assets, pi_bwrap_build as build
from .pi_lock_layout import dependency_layout
from .schema import ConfigError
from .storage import Tree


LICENSE_PATHS = ["agents/pi/build/licenses/bubblewrap-0.13.0/COPYING", "agents/pi/build/licenses/libcap-2.77/License"]


def _read(tree, name, limit):
  record = tree.read(name, max_bytes=limit)
  if record is None: raise ValueError()
  return record[0]


def import_candidate(repository: Path, candidate: Path, sources: Path):
  """全量校验、全量目标预检后排他新建；中断片段可重试，不是跨文件事务。"""
  try:
    with Tree(candidate, private=False) as tree:
      raw_record = _read(tree, "candidate.json", 1024 * 1024)
      # 先读JSON只用于构造闭合引用；此后必须验证完整记录，才能读固定归档名。
      value = json.loads(raw_record, object_pairs_hook=assets._object, parse_constant=assets._constant)
      digest = hashlib.sha256(raw_record).hexdigest()
      archive_digest = assets._sha(value["archive_sha256"])
      source = {"kind": "asset", "format": "tar.gz", "platform": "linux-x86_64", "target": "bin/pi-bwrap",
        "archive_member": "bin/pi-bwrap", "archive_digest": archive_digest,
        "vendor_path": "vendor/pi-bwrap-" + archive_digest + ".tar.gz",
        "build_record": {"recipe": "bubblewrap-v1", "path": "build-records/" + digest + ".json", "digest": digest},
        "license_files": list(LICENSE_PATHS)}
      record = assets.parse_record(raw_record, source)
      archive = _read(tree, "pi-bwrap-linux-x86_64.tar.gz", assets.MAX_ARCHIVE)
    contents = assets.archive_contents(archive, source, record)
    layout = dependency_layout(family="modern")
    targets = {layout.lock_directory + "/" + source["build_record"]["path"]: raw_record,
      layout.lock_directory + "/" + source["vendor_path"]: archive}
    with Tree(sources, private=False) as tree:
      for item in build.INPUTS.values():
        raw = _read(tree, item["name"], build.MAX_ARCHIVE)
        if hashlib.sha256(raw).hexdigest() != item["sha256"]: raise ValueError()
        targets[layout.lock_directory + "/build-inputs/" + item["sha256"] + "/" + item["name"]] = raw
    for path, name in zip(LICENSE_PATHS, ("bubblewrap-COPYING", "libcap-License")):
      targets[path] = contents["licenses/" + name]
    with Tree(repository, private=False) as tree:
      if tree.fd is None: raise ValueError()
      existing = {}
      for name, raw in targets.items():
        previous = tree.read(name, max_bytes=len(raw))
        if previous is not None:
          if previous[0] != raw or previous[1] not in (0o600, 0o644): raise ValueError()
          existing[name] = previous
      for name, raw in targets.items():
        if name in existing:
          if tree.read(name, max_bytes=len(raw)) != existing[name]: raise ValueError()
        else:
          tree.write_new(name, raw)
    return source
  except Exception:
    raise ConfigError("pi-bwrap-import-invalid") from None
