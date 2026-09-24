"""只在指定项目集成锁定 OpenSpec；先空目录生成，再逐文件冲突检查。"""

import hashlib
import base64
from contextlib import ExitStack
import json
import re
from pathlib import Path
import tempfile
import stat

from .deployment import json_bytes
from .process import DependencyError, checked, environment
from .storage import Conflict, Tree, ensure_private
from .paths import PathError


def initialize_openspec(workspace, lock, project):
  if not project.is_dir() or project.is_symlink():
    raise Conflict("项目必须为已有真实目录")
  validate_project_root(project)
  from .runtime import runtime_identity
  if workspace.backend.status(workspace, runtime_identity(workspace, lock)) != "installed":
    raise DependencyError("锁定 OpenSpec 尚未安装，请先 sync")
  if not hasattr(workspace.backend, "openspec_argv"):
    raise DependencyError("所选工具的依赖后端未提供锁定 OpenSpec 集成")
  argv = workspace.backend.openspec_argv(workspace, lock)
  ensure_private(workspace.cache / "projects")
  with tempfile.TemporaryDirectory(prefix="generate-", dir=workspace.cache / "projects") as temporary:
    root = Path(temporary)
    home = root / "home"
    stage = root / "project"
    home.mkdir(mode=0o700)
    stage.mkdir(mode=0o700)
    env = environment(home=home)
    env.update(OPENSPEC_TELEMETRY="0", DO_NOT_TRACK="1", OPENSPEC_NO_UPDATE_CHECK="1")
    for command, expected in getattr(workspace.backend, "openspec_preflight", lambda _: [])(lock):
      if checked(command, cwd=stage, env=env) != expected:
        raise DependencyError("OpenSpec 所需工具链版本不匹配")
    checked([*argv, "init", "--tools", "agents", "--profile", "core", "--no-animation"], cwd=stage, env=env)
    from contextlib import nullcontext
    with getattr(workspace.adapter, "project_write_guard", lambda *_: nullcontext())(workspace, project):
      metadata = getattr(workspace.adapter, "project_metadata_root", lambda *_: None)(workspace, project)
      return apply_generated(project, stage, metadata_root=metadata)


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


def apply_generated(project, stage, *, metadata_root=None):
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
    raise DependencyError("OpenSpec 没有生成可发现的 agents 技能")
  marker = ".agentcfg-openspec.json"
  proposal = hashlib.sha256(json_bytes({name: hashlib.sha256(body).hexdigest() for name, body in files.items()})).hexdigest()
  with ExitStack() as stack:
    target = stack.enter_context(Tree(project, private=False))
    journal = stack.enter_context(Tree(metadata_root, create=True)) if metadata_root else target
    pending = journal.read(".agentcfg-openspec-pending.json", max_bytes=16 * 1024 * 1024)
    if pending is not None:
      return recover_generated(target, pending, proposal, journal=journal, expected_files=files)
    raw = journal.read(marker, max_bytes=16 * 1024 * 1024)
    try:
      ownership = json.loads(raw[0]) if raw else {"version": 1, "files": {}}
      if set(ownership) != {"version", "files"} or ownership["version"] != 1 or not isinstance(ownership["files"], dict): raise ValueError()
      previous = ownership["files"]
      from .paths import relative_path
      for name, checksum in previous.items():
        relative_path(name)
        if not (name.startswith("openspec/") or name.startswith(".agents/skills/openspec-") or name == ".agents/skills/.openspec-target") or not isinstance(checksum, str) or not re.fullmatch("[0-9a-f]{64}", checksum): raise ValueError()
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
    # 写前记录完整意图；失败后只完成同一批生成内容，不自动接纳用户修改。
    manifest = json_bytes({"version": 1, "files": {**previous, **inventory}})
    changes = []
    for name, data, expected in writes:
      before = target.read(name)
      if (before[2] if before else None) != expected: raise Conflict("OpenSpec 产物在准入期间发生变化")
      changes.append({"path": name, "before_digest": hashlib.sha256(before[0]).hexdigest() if before else None,
        "after": base64.b64encode(data).decode(), "after_digest": hashlib.sha256(data).hexdigest()})
    if raw is None or raw[0] != manifest:
      changes.append({"path": marker, "before_digest": hashlib.sha256(raw[0]).hexdigest() if raw else None,
        "after": base64.b64encode(manifest).decode(), "after_digest": hashlib.sha256(manifest).hexdigest()})
    if not changes: return {"integration": "upstream-agents-custom", "changed": 0, "artifacts": sorted(files)}
    document = {"schema_version": 1, "proposal_digest": proposal, "changes": changes, "artifacts": sorted(files), "changed": len(writes)}
    journal.write_new(".agentcfg-openspec-pending.json", json_bytes(document))
    return recover_generated(target, journal.read(".agentcfg-openspec-pending.json"), proposal, journal=journal, expected_files=files)


def recover_generated(target, pending, proposal, *, journal, expected_files):
  try:
    document = json.loads(pending[0])
    if (pending[1] != 0o600 or set(document) != {"schema_version", "proposal_digest", "changes", "artifacts", "changed"}
        or document["schema_version"] != 1 or document["proposal_digest"] != proposal or type(document["changed"]) is not int
        or not isinstance(document["changes"], list) or not document["changes"]
        or document["artifacts"] != sorted(expected_files) or not 0 <= document["changed"] <= len(expected_files)): raise ValueError()
    prepared = []
    names = set()
    for change in document["changes"]:
      if set(change) != {"path", "before_digest", "after", "after_digest"}: raise ValueError()
      if change["before_digest"] is not None and (not isinstance(change["before_digest"], str) or not re.fullmatch("[0-9a-f]{64}", change["before_digest"])): raise ValueError()
      name = change["path"]
      from .paths import relative_path
      relative_path(name)
      if name in names or not (name.startswith("openspec/") or name.startswith(".agents/skills/openspec-") or name in (".agentcfg-openspec.json", ".agents/skills/.openspec-target")):
        raise ValueError()
      names.add(name)
      after = base64.b64decode(change["after"], validate=True)
      if hashlib.sha256(after).hexdigest() != change["after_digest"]: raise ValueError()
      if name != ".agentcfg-openspec.json" and expected_files.get(name) != after: raise ValueError()
      destination = journal if name == ".agentcfg-openspec.json" else target
      before = destination.read(name)
      checksum = hashlib.sha256(before[0]).hexdigest() if before else None
      if checksum == change["after_digest"]: continue
      if checksum != change["before_digest"]: raise Conflict("OpenSpec 恢复遇到用户修改，保护保持生效")
      prepared.append((destination, name, after, before[2] if before else None))
  except (ValueError, TypeError, KeyError, PathError):
    raise Conflict("OpenSpec 初始化恢复记录无效或生成来源已经改变") from None
  for destination, name, body, identity in prepared: destination.replace(name, body, 0o600, expected=identity)
  journal.replace(".agentcfg-openspec-pending.json", None, expected=pending[2])
  return {"integration": "upstream-agents-custom", "changed": document["changed"], "artifacts": document["artifacts"]}
