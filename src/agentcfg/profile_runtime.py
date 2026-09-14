"""包拥有的固定 DSH profile；只选择已安装运行包，不调用原生安装器。"""

import json
import os
from pathlib import Path
import stat
import uuid

from .deployment import json_bytes
from .storage import Conflict, Tree, ensure_private


PROFILE_PROJECTIONS = ("@deepseek-harness-tui/dsh-tui", "dsh-plugin-oauth-subs")


def project_runtime_modules(profile, runtime, record, expected):
  """只投影 profile 直接加载的包；DSH 的 fallback 仍写入 profile 自己的目录。"""
  previous = record.get("projections", {})
  pending = record.get("pending_projections", {})
  for package, target in expected.items():
    link = profile / "node_modules" / package
    parent = link.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
      raise Conflict("原生 profile 模块命名空间不是受管目录")
    try:
      info = link.lstat()
    except FileNotFoundError:
      info = None
    old = os.readlink(link) if info is not None and stat.S_ISLNK(info.st_mode) else None
    if info is not None and old is None:
      raise Conflict("原生 profile 必需模块不是受管链接")
    allowed = {value for value in (previous.get(package), pending.get(package), target) if value is not None}
    if old is not None and old not in allowed:
      raise Conflict("原生 profile 必需模块链接已被外部修改")
    if old == target:
      continue
    temporary = parent / (".agentcfg-module-" + uuid.uuid4().hex)
    temporary.symlink_to(target)
    try:
      os.replace(temporary, link)
    finally:
      temporary.unlink(missing_ok=True)


def prepare(workspace, runtime):
  """调用者持实例锁。原生 cordis.yml/会话保持运行时拥有，不参与配置回滚。"""
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  ensure_private(profile)
  manifest = {"name": "agentcfg-managed-profile", "version": "1.0.0", "private": True,
    "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-harness-tui/dsh-tui"]}}}
  with Tree(profile) as tree:
    owner = tree.read(".agentcfg-package-owner.json")
    package = tree.read("package.json")
    if owner is None and package is not None:
      raise Conflict("原生 profile 存在未接管的 package.json")
    record = json.loads(owner[0]) if owner else {"runtime": None, "binding": workspace.binding}
    if owner is not None and owner[1] != 0o600:
      raise Conflict("原生 profile 所有权记录必须为 0600")
    if record["binding"] != workspace.binding:
      raise Conflict("原生 profile 属于另一份机器配置")
    expected_package = json_bytes(manifest)
    if package is not None and package[0] != expected_package:
      raise Conflict("包拥有的 profile 配置已被修改")
    projections = {name: str(runtime / "node_modules" / Path(name)) for name in PROFILE_PROJECTIONS}
    with tree.parent("node_modules") as (fd, name):
      try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
      except FileNotFoundError:
        info = None
      old = os.readlink(name, dir_fd=fd) if info is not None and stat.S_ISLNK(info.st_mode) else None
      isolated = info is not None and stat.S_ISDIR(info.st_mode)
      if info is not None and old is None and not isolated:
        raise Conflict("原生 profile node_modules 不是受管目录")
      if old is not None and (owner is None or old not in (record.get("runtime"), record.get("pending_runtime"))):
        raise Conflict("原生 profile 运行包链接已被外部修改")
      if isolated and (owner is None or "isolated" not in (record.get("modules"), record.get("pending_modules"))):
        raise Conflict("原生 profile node_modules 目录没有隔离所有权记录")
      # 先记录允许的前后值；中断后只能恢复明确归本次准备所有的目录。
      pending = {"binding": workspace.binding, "modules": record.get("modules"), "pending_modules": "isolated",
        "projections": record.get("projections", {}), "pending_projections": projections}
      if old is not None:
        pending.update({"runtime": old, "pending_runtime": old})
      tree.write_state(".agentcfg-package-owner.json", json_bytes(pending))
      if package is None:
        tree.write_state("package.json", expected_package)
      if not isolated:
        if old is not None:
          os.unlink(name, dir_fd=fd)
        os.mkdir(name, mode=0o700, dir_fd=fd)
        os.fsync(fd)
    project_runtime_modules(profile, runtime, record, projections)
    tree.write_state(".agentcfg-package-owner.json", json_bytes({"binding": workspace.binding,
      "modules": "isolated", "projections": projections}))
  return profile
