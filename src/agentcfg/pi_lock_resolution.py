"""完整锁的纯 resolution 规则；数据符合不代表来源或激活资格。"""

import base64
import os
from pathlib import Path
import re

from .config import _credential_url
from .paths import relative_path


VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def validate_lock_resolution(package, resolution, piece, manifest):
  """只核锁中逻辑路径与依赖图，不读文件、不修改输入、不授予能力。"""
  failed = False
  try:
    _validate_resolution(package, resolution, piece, manifest)
  except Exception:
    failed = True
  # 只清理刚生成的固定错误，连同调用方活跃异常的隐式上下文一起丢弃。
  if failed:
    try:
      raise ValueError("pi-lock-resolution")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise


def _validate_resolution(package, resolution, piece, manifest):
  if (resolution.get("lockfileVersion") != 3 or not isinstance(package.get("dependencies"), dict)
      or resolution.get("packages", {}).get("", {}).get("dependencies") != package["dependencies"]):
    raise ValueError()
  archives = {source["vendor_path"] for source in manifest["sources"].values()
    if source["kind"] in ("npm", "local", "git") and "vendor_path" in source}
  declared = {manifest["sources"][key]["package"] for key in piece["source_ids"]
    if manifest["sources"][key]["kind"] in ("npm", "local", "git")}
  if set(package["dependencies"]) != declared:
    raise ValueError()
  def file_references(record):
    for group in ("dependencies", "optionalDependencies", "peerDependencies"):
      for reference in record.get(group, {}).values():
        if isinstance(reference, str) and reference.startswith("file:"):
          target = os.path.normpath(str(Path(piece["package_path"]).parent / reference[5:]))
          if target not in archives or Path(reference[5:]).is_absolute():
            raise ValueError()
  # 根声明与所有 resolution 记录共用同一档案白名单，不能被非 root 过滤跳过。
  file_references(package)
  for record in resolution["packages"].values():
    file_references(record)
  for version in package["dependencies"].values():
    if not isinstance(version, str):
      raise ValueError()
    if version.startswith("file:"):
      path = os.path.normpath(str(Path(piece["package_path"]).parent / version[5:]))
      if path not in archives or Path(version[5:]).is_absolute():
        raise ValueError()
    elif not VERSION.fullmatch(version):
      raise ValueError()
  for name in package["dependencies"]:
    if "node_modules/" + name not in resolution["packages"]:
      raise ValueError()
  if manifest["schema_version"] == 2:
    from .pi_modern_launcher import validate_locked_ai
    validate_locked_ai(resolution, piece)
    # 能力来源必须对应真正安装的直接依赖，不能只分别验证两个自洽清单。
    for source_id in piece["source_ids"]:
      source = manifest["sources"][source_id]
      if source["kind"] not in ("npm", "local", "git"): continue
      name = source["package"]
      wanted = package["dependencies"][name]
      actual = resolution["packages"]["node_modules/" + name]
      if actual.get("name", name) != name or actual.get("version") != source["version"]:
        raise ValueError()
      if source["kind"] == "npm":
        if (wanted != source["version"] or actual.get("resolved") != source["resolved"]
            or actual.get("integrity") != source["integrity"]):
          raise ValueError()
      else:
        for reference in (wanted, actual.get("resolved")):
          if (not isinstance(reference, str) or not reference.startswith("file:")
              or Path(reference[5:]).is_absolute()
              or os.path.normpath(str(Path(piece["package_path"]).parent / reference[5:])) != source["vendor_path"]):
            raise ValueError()
  for path, value in resolution["packages"].items():
    if not path:
      continue
    relative_path(path)
    if "node_modules" not in Path(path).parts:
      raise ValueError()
    if value.get("link"):
      # 本地源必须为已冻结归档，不允许workspace/link逃逸运行包。
      raise ValueError()
    required = set(value.get("dependencies", {})) - set(value.get("optionalDependencies", {}))
    required |= {name for name in value.get("peerDependencies", {}) if not value.get("peerDependenciesMeta", {}).get(name, {}).get("optional")}
    for name in required:
      # 按 Node 的祖先 node_modules 查找；锁中必须存在每个必需传递依赖。
      base = Path(path)
      candidates = []
      while base.parts:
        candidates.append((base / "node_modules" / name).as_posix())
        base = base.parent
      candidates.append("node_modules/" + name)
      if not any(candidate in resolution["packages"] for candidate in candidates):
        raise ValueError()
    if not value.get("inBundle"):
      if not {"version", "resolved", "integrity"} <= value.keys():
        raise ValueError()
      if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", value["integrity"]):
        raise ValueError()
      if len(base64.b64decode(value["integrity"][7:], validate=True)) != 64 or not VERSION.fullmatch(value["version"]):
        raise ValueError()
      resolved = value["resolved"]
      if resolved.startswith("file:"):
        target = os.path.normpath(str(Path(piece["package_path"]).parent / resolved[5:]))
        if target not in archives or Path(resolved[5:]).is_absolute():
          raise ValueError()
      elif not resolved.startswith("https://") or _credential_url(resolved):
        raise ValueError()
