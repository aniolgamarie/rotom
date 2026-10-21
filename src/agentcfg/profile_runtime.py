"""包拥有的固定 DSH profile；只选择已安装运行包，不调用原生安装器。"""

import json
import os
from pathlib import Path
import stat
import uuid

from .deployment import json_bytes
from .storage import Conflict, Tree, ensure_private
from .dsh_ssh import SSH_BUNDLES, SSH_PROJECTIONS, is_ssh
from .dsh_optional import TEAM_BUNDLE, TEAM_SELECTION_FILE


PROFILE_PROJECTIONS = ("@deepseek-harness-tui/dsh-tui", "rotom-dsh-cursor-terminal",
  "dsh-auto-review", "rotom-dsh-review-context", "rotom-dsh-execution-environment",
  "@deepseek-ai/dsh-tmux-context", "@deepseek-ai/dsh-experimental-worktree",
  "@deepseek-ai/dsh-experimental-tool-worktree", TEAM_BUNDLE,
  "@deepseek-ai/dsh-experimental-agent-team", "@deepseek-ai/dsh-experimental-tool-agent-team",
  "@deepseek-ai/dsh-experimental-client-ui-agent-team")
LEGACY_BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-harness-tui/dsh-tui"]
PROFILE_BUNDLES = ["@deepseek-ai/dsh-base", "rotom-dsh-review-context", "dsh-auto-review",
  "@deepseek-harness-tui/dsh-tui"]


def profile_layout(workspace, *, deployed=False):
  if is_ssh(workspace.resolved.data):
    return SSH_PROJECTIONS, SSH_BUNDLES
  enabled = "agent-teams" in workspace.resolved.data["plugins"]
  if deployed:
    with Tree(workspace.instance) as tree:
      selection = tree.read(TEAM_SELECTION_FILE)
    # 旧部署没有 Teams；不能借未部署配置将它开启。
    enabled = False
    if selection is not None:
      try:
        value = json.loads(selection[0])
        if (selection[1] != 0o600 or not isinstance(value, dict)
            or set(value) != {"schema_version", "agent_teams"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["agent_teams"]) is not bool):
          raise ValueError()
        enabled = value["agent_teams"]
      except (ValueError, TypeError):
        raise Conflict("受管 Teams 开关无效；请检查 plan/apply") from None
  return PROFILE_PROJECTIONS, [*PROFILE_BUNDLES, *([TEAM_BUNDLE] if enabled else [])]


def package_manifest(bundles):
  return {"name": "agentcfg-managed-profile", "version": "1.0.0", "private": True,
    "dsh": {"profile": {"bundles": bundles}}}


def verify(workspace, runtime):
  """共享启动不修复资源；所有权不完整、漂移或旧布局均要求显式 apply。"""
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  packages, bundles = profile_layout(workspace, deployed=True)
  projections = {name: str(runtime / "node_modules" / Path(name)) for name in packages}
  expected = {"binding": workspace.binding, "modules": "isolated", "projections": projections, "bundles": bundles}
  manifest = package_manifest(bundles)
  try:
    with Tree(profile) as tree:
      owner, package = tree.read(".agentcfg-package-owner.json"), tree.read("package.json")
      if (owner is None or owner[1] != 0o600 or json.loads(owner[0]) != expected
          or package is None or package[0] != json_bytes(manifest) or package[1] != 0o600):
        raise ValueError()
      for name, target in projections.items():
        with tree.parent("node_modules/" + name) as (fd, leaf):
          info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
          if (not stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid()
              or os.readlink(leaf, dir_fd=fd) != target):
            raise ValueError()
  except (OSError, ValueError, TypeError):
    raise Conflict("DSH启动资源未准备完成或发生漂移；请先 plan/apply，不会在 run 中修复") from None
  return profile


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
  packages, bundles = profile_layout(workspace, deployed=True)
  manifest = package_manifest(bundles)
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
    allowed = [expected_package]
    known = (LEGACY_BUNDLES, PROFILE_BUNDLES, [*PROFILE_BUNDLES, TEAM_BUNDLE], SSH_BUNDLES)
    if "bundles" in record:
      for key in ("bundles", "pending_bundles"):
        previous = record.get(key)
        if previous is None and (key == "pending_bundles" or "pending_bundles" in record):
          continue
        if previous not in known:
          raise Conflict("包拥有的 profile bundle 记录无效")
        allowed.append(json_bytes(package_manifest(previous)))
    else:
      # 旧所有权记录只允许已知历史布局，不能接管任意原生 bundle。
      allowed.extend(json_bytes(package_manifest(previous)) for previous in (LEGACY_BUNDLES, PROFILE_BUNDLES))
    if package is not None and package[0] not in allowed:
      raise Conflict("包拥有的 profile 配置已被修改")
    observed_bundles = json.loads(package[0])["dsh"]["profile"]["bundles"] if package else None
    projections = {name: str(runtime / "node_modules" / Path(name)) for name in packages}
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
      observed = {}
      if isolated:
        # 恢复也可能再次中断：先验证并保存各链接的实际前值，不能抹掉上一 pending。
        for module, target in projections.items():
          try:
            with tree.parent("node_modules/" + module) as (parent, leaf):
              info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
              if not stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
                raise Conflict("原生 profile 必需模块不是受管链接")
              value = os.readlink(leaf, dir_fd=parent)
          except FileNotFoundError:
            continue
          if value not in {record.get("projections", {}).get(module), record.get("pending_projections", {}).get(module), target}:
            raise Conflict("原生 profile 必需模块链接已被外部修改")
          observed[module] = value
      # 先记录允许的前后值；中断后只能恢复明确归本次准备所有的目录。
      pending = {"binding": workspace.binding, "modules": record.get("modules"), "pending_modules": "isolated",
        "projections": observed, "pending_projections": projections,
        "bundles": observed_bundles, "pending_bundles": bundles}
      if old is not None:
        pending.update({"runtime": old, "pending_runtime": old})
      tree.write_state(".agentcfg-package-owner.json", json_bytes(pending))
      if package is None or package[0] != expected_package:
        tree.write_state("package.json", expected_package)
      if not isolated:
        if old is not None:
          os.unlink(name, dir_fd=fd)
        os.mkdir(name, mode=0o700, dir_fd=fd)
        os.fsync(fd)
    project_runtime_modules(profile, runtime, record, projections)
    tree.write_state(".agentcfg-package-owner.json", json_bytes({"binding": workspace.binding,
      "modules": "isolated", "projections": projections, "bundles": bundles}))
  return profile
