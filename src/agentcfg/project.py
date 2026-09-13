"""只在指定项目集成锁定 OpenSpec；先空目录生成，再逐文件冲突检查。"""

import hashlib
import json
from pathlib import Path
import tempfile
import stat

from .dependencies import installed, runtime_root
from .deployment import json_bytes
from .process import DependencyError, checked, environment
from .storage import Conflict, Tree, ensure_private


def initialize_openspec(workspace, lock, project):
  if not project.is_dir() or project.is_symlink():
    raise Conflict("项目必须为已有真实目录")
  validate_project_root(project)
  if not installed(workspace, lock):
    raise DependencyError("锁定 OpenSpec 尚未安装，请先 sync")
  cli = runtime_root(workspace, lock) / "node_modules/@fission-ai/openspec/bin/openspec.js"
  ensure_private(workspace.cache / "projects")
  with tempfile.TemporaryDirectory(prefix="generate-", dir=workspace.cache / "projects") as temporary:
    root = Path(temporary)
    home = root / "home"
    stage = root / "project"
    home.mkdir(mode=0o700)
    stage.mkdir(mode=0o700)
    env = environment(home=home)
    env.update(OPENSPEC_TELEMETRY="0", DO_NOT_TRACK="1", OPENSPEC_NO_UPDATE_CHECK="1")
    checked(["node", str(cli), "init", "--tools", "agents", "--profile", "core", "--no-animation"], cwd=stage, env=env)
    return apply_generated(project, stage)


def validate_project_root(project):
  """DSH 在最近 Git 根查找项目技能，不能在其子目录伪报集成有效。"""
  for directory in (project, *project.parents):
    try:
      info = (directory / ".git").lstat()
    except FileNotFoundError:
      continue
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
      raise Conflict("项目 Git 根标记不是普通文件或目录")
    if directory != project:
      raise Conflict("指定路径位于另一个 Git 工作树内部；请将 --path 指向工作树根目录")
    return


def apply_generated(project, stage):
  files = {}
  with Tree(stage) as source:
    for path in sorted(stage.rglob("*")):
      if path.is_symlink():
        raise Conflict("生成器产生了符号链接，拒绝集成")
      if not path.is_file():
        continue
      relative = path.relative_to(stage).as_posix()
      if not (relative.startswith("openspec/") or relative.startswith(".agents/skills/openspec-") or relative == ".agents/skills/.openspec-target"):
        raise Conflict("生成器产物超出声明范围")
      files[relative] = source.read(relative)[0]
  if not files or not any(name.startswith(".agents/skills/openspec-") and name.endswith("/SKILL.md") for name in files):
    raise DependencyError("OpenSpec 没有生成 DSH 可发现的 agents 技能")
  marker = ".agentcfg-openspec.json"
  with Tree(project, private=False) as target:
    raw = target.read(marker)
    try:
      previous = json.loads(raw[0])["files"] if raw else {}
    except Exception:
      raise Conflict("项目集成清单无效") from None
    writes = []
    inventory = {}
    for name, data in files.items():
      digest = hashlib.sha256(data).hexdigest()
      inventory[name] = digest
      current = target.read(name)
      if current and current[0] == data:
        continue
      if current and previous.get(name) != hashlib.sha256(current[0]).hexdigest():
        raise Conflict("项目已有同名或用户修改的 OpenSpec 产物，拒绝覆盖")
      writes.append((name, data, current[2] if current else None))
    # 旧版本产物不做递归清理；升级删除需显式清单提案，保留用户项目内容。
    for name, data, expected in writes:
      target.replace(name, data, 0o600, expected=expected)
    manifest = json_bytes({"version": 1, "files": {**previous, **inventory}})
    if raw is None or raw[0] != manifest:
      target.replace(marker, manifest, expected=raw[2] if raw else None)
  return {"integration": "upstream-agents-custom", "changed": len(writes), "artifacts": sorted(files)}
