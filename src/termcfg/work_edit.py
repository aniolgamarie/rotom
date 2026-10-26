"""协作锁下只修改 machine.work；秘密正文仅在内存与必要原子发布中存在。"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import stat
import uuid

import tomlkit

from agentcfg.storage import Tree, StateError, instance_lock, identity
from .errors import TermcfgError
from .work_config import resolve_executable, settings_from_document
from .work_projects import canonical_boundary, directory, discover


@dataclass(frozen=True, repr=False)
class Proposal:
  settings: object
  original: bytes
  identity: tuple
  mode: int
  output: bytes
  fragment: str
  changed: bool
  discovery: object


@dataclass(frozen=True)
class SaveResult:
  changed: bool
  fragment: str


def _state_root():
  from .work_state import default_root
  return default_root().parent / "config-locks"


@contextmanager
def config_lock(path, *, timeout=5):
  key = hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()
  try:
    with Tree(_state_root() / key, create=True) as tree:
      with instance_lock(tree, timeout=timeout):
        yield
  except TermcfgError:
    raise
  except StateError as error:
    raise TermcfgError(error.exit_code, "work_config_lock_conflict", "work config check") from None
  except OSError:
    raise TermcfgError(6, "work_config_lock_failed", "work config check") from None


def _read(settings):
  path = settings.local_path
  try:
    with Tree(path.parent) as tree:
      with tree.open_read(path.name, max_bytes=4 * 1024 * 1024) as (stream, opened):
        if stat.S_IMODE(opened.st_mode) != 0o600:
          raise TermcfgError(4, "work_unsafe_local_configuration", "work config check")
        data = stream.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
          raise TermcfgError(4, "work_unsafe_local_configuration", "work config check")
        return data, 0o600, identity(opened)
  except FileNotFoundError:
    raise TermcfgError(4, "work_unsafe_local_configuration", "work config check") from None
  except StateError as error:
    raise TermcfgError(error.exit_code, "work_unsafe_local_configuration", "work config check") from None


def manual_fragment(operation=None, values=None, *, settings=None):
  """拒绝时只使用显式输入或先前已验证的普通字段，绝不重读不安全配置。"""
  header = ("# Merge manually; do not replace the selected local file with this fragment.\n"
    "# Existing template references and conflicts are unverified; run work config check after editing.\n")
  if operation is None and settings is not None and settings.structured is not None:
    return header + tomlkit.dumps(settings.structured)
  if operation not in ("source-add", "project-add", "named-add"):
    return header + "# [machine.work]\n# Review and edit existing workspace settings manually; no editor was launched.\n"
  entry = deepcopy(values)
  key = "sources" if operation == "source-add" else "workspaces"
  if operation != "source-add":
    entry["kind"] = "project" if operation == "project-add" else "named"
  try:
    if "path" in entry:
      entry["path"] = str(canonical_boundary(entry["path"], entry["mode"]) if operation == "project-add"
        else directory(entry["path"]))
    if "start_path" in entry:
      entry["start_path"] = str(directory(entry["start_path"]))
    # 临时模板只用于复用条目结构/目录校验；不输出它，也不声称真实引用已通过。
    from .work_projects import normalize_work
    checked = normalize_work({"model": "structured-v1", "include_rotom": False,
      "herdr_binary": "herdr", "session": "manual", "templates": {entry["template"]: {
        "order": ["shell"], "initial": "shell", "tab_types": {"shell": {"label": "Shell", "launcher": "shell"}}}},
      key: [entry]}, local_path=Path.cwd() / "fragment.toml")
    return header + tomlkit.dumps({"machine": {"work": {key: checked[key]}}})
  except (TermcfgError, ValueError, KeyError, TypeError, OSError):
    return header + "# [machine.work]\n# No entry generated: correct explicit inputs before manual editing.\n"


def _validated(document, settings):
  from agentcfg.schema import separate_local, ConfigError
  ordinary, _ = separate_local(document)
  try:
    return settings_from_document(ordinary, local=settings.local_path, repo_root=settings.repo_root)
  except TermcfgError:
    # 与普通读取相同，只在确有 adapter 字段时加载公共 schema；不加载凭据。
    if not ordinary.get("overrides"):
      raise
    from agentcfg.workspace import load_public_catalog
    try:
      catalog, _ = load_public_catalog(repository=settings.repo_root)
      return settings_from_document(ordinary, local=settings.local_path, repo_root=settings.repo_root,
        adapter_schemas=catalog.adapter_schemas)
    except ConfigError:
      raise TermcfgError(2, "work_invalid_configuration", "work config check") from None


def _merge(current, proposed):
  # 相等节点完全保留；表内增量修改保留原有注释和非工作区内容。
  for key in list(current):
    if key not in proposed:
      del current[key]
  for key, value in proposed.items():
    if key in current and current[key] == value:
      continue
    if key in current and isinstance(value, dict) and hasattr(current[key], "items"):
      _merge(current[key], value)
    elif key in current and isinstance(value, list) and isinstance(current[key], list):
      original = current[key]
      for index, item in enumerate(value[:len(original)]):
        if original[index] == item:
          continue
        if isinstance(item, dict) and hasattr(original[index], "items"):
          _merge(original[index], item)
        else:
          original[index] = item
      while len(original) > len(value):
        original.pop()
      for item in value[len(original):]:
        original.append(item)
    else:
      current[key] = value


def _proposal(settings, before, work):
  try:
    doc = tomlkit.parse(before[0].decode("utf-8"))
    _merge(doc["machine"]["work"], work)
    proposed = _validated(doc.unwrap(), settings)
    discovery = discover(proposed)
    output = tomlkit.dumps(doc).encode("utf-8")
    fragment = tomlkit.dumps(doc["machine"]["work"].unwrap())
    return Proposal(proposed, before[0], before[2], before[1], output, fragment, output != before[0], discovery)
  except TermcfgError:
    raise
  except (ValueError, TypeError, KeyError, UnicodeError):
    raise TermcfgError(2, "work_invalid_configuration", "work config check") from None


def preview(settings, operation, values):
  try:
    before = _read(settings)
  except TermcfgError as error:
    error.fragment = manual_fragment(operation, values)
    raise
  try:
    doc = tomlkit.parse(before[0].decode("utf-8")).unwrap()
    fresh = _validated(doc, settings)
    if fresh.model != "structured-v1":
      raise TermcfgError(2, "work_structured_opt_in_required", "work config check")
    work = deepcopy(doc["machine"]["work"])
    entry = deepcopy(values)
    if operation == "source-add":
      entry["path"] = str(directory(entry["path"]))
      entries = work.setdefault("sources", [])
      existing = [item for item in entries if item["id"] == entry["id"]]
    elif operation == "project-add":
      entry["path"] = str(canonical_boundary(entry["path"], entry["mode"]))
      entry["kind"] = "project"
      entries = work.setdefault("workspaces", [])
      existing = [item for item in entries if item.get("kind") == "project" and
        str(canonical_boundary(directory(item["path"], base=settings.local_path.parent), item["mode"])) == entry["path"]]
    elif operation in ("named-add", "named-rename"):
      entries = work.setdefault("workspaces", [])
      existing = [item for item in entries if item.get("kind") == "named" and item["id"] == entry["id"]]
      if operation == "named-rename":
        if len(existing) != 1:
          raise TermcfgError(2, "work_named_not_registered", "work list")
        existing[0]["title"] = entry["title"]
        return _proposal(settings, before, work)
      entry["kind"] = "named"
      if "start_path" in entry:
        entry["start_path"] = str(directory(entry["start_path"]))
    else:
      raise TermcfgError(2, "work_invalid_registration", "work --help")
    if existing:
      if len(existing) != 1 or existing[0] != entry:
        # 缺省 source 字段按规范化后比较，兼容 CLI 与手工声明。
        candidate = deepcopy(work)
        target = candidate["sources" if operation == "source-add" else "workspaces"]
        target[target.index(existing[0])] = entry
        proposed = _proposal(settings, before, candidate)
        if proposed.settings.structured != fresh.structured:
          raise TermcfgError(2, "work_registration_conflict", "work config check")
      return _proposal(settings, before, work)
    entries.append(entry)
    return _proposal(settings, before, work)
  except TermcfgError:
    raise
  except (ValueError, TypeError, KeyError, UnicodeError):
    raise TermcfgError(2, "work_invalid_registration", "work --help") from None


def _publish(proposal):
  try:
    current = _read(proposal.settings)
    if current[0] != proposal.original or current[2] != proposal.identity:
      raise TermcfgError(4, "work_config_changed_before_save", "work config check")
    if not proposal.changed:
      return SaveResult(False, proposal.fragment)
    with Tree(proposal.settings.local_path.parent) as tree:
      tree.replace(proposal.settings.local_path.name, proposal.output, mode=proposal.mode, expected=proposal.identity)
    return SaveResult(True, proposal.fragment)
  except TermcfgError:
    raise
  except StateError as error:
    result = TermcfgError(error.exit_code, "work_config_save_failed_or_uncertain", "work config check")
    result.fragment = proposal.fragment
    raise result from None
  except OSError:
    result = TermcfgError(6, "work_config_save_failed_or_uncertain", "work config check")
    result.fragment = proposal.fragment
    raise result from None


def save(proposal):
  try:
    with config_lock(proposal.settings.local_path):
      return _publish(proposal)
  except TermcfgError as error:
    error.fragment = proposal.fragment
    raise


def edit(settings, *, run=None, context=None):
  from rotom.context import require_input
  require_input(context)
  try:
    # 先拒绝初始不安全输入，再创建协作锁；锁内仍重新读取最新内容。
    _read(settings)
    return _edit(settings, run=run, **({"context": context} if context is not None else {}))
  except TermcfgError as error:
    if not getattr(error, "fragment", None):
      error.fragment = manual_fragment(settings=settings)
    raise


def _edit(settings, *, run=None, context=None):
  def publish(proposal):
    if context is not None and proposal.changed:
      from .work_ui import present_proposal, confirm
      present_proposal(proposal, context=context)
      confirm("Save the reviewed workspace configuration", context=context)
    return _publish(proposal)
  if settings.editor is None:
    raise TermcfgError(2, "work_editor_choice_required", "work --help")
  executable = resolve_executable(settings.editor)
  with config_lock(settings.local_path):
    before = _read(settings)
    try:
      doc = tomlkit.parse(before[0].decode("utf-8"))
      original_fragment = tomlkit.dumps(doc["machine"]["work"].unwrap())
      name = uuid.uuid4().hex + ".toml"
      with Tree(_state_root().parent / "editor", create=True) as tree:
        tree.write_new(name, original_fragment.encode("utf-8"))
        try:
          result = (run or subprocess.run)([executable, str(tree.root / name)], check=False)
          if result.returncode:
            raise TermcfgError(result.returncode, "work_fragment_editor_failed", "work config edit")
          after = tree.read(name, max_bytes=1024 * 1024)
          if after is None or after[1] != 0o600:
            raise TermcfgError(4, "work_unsafe_edited_fragment", "work config edit")
          if after[0] == original_fragment.encode("utf-8"):
            return publish(_proposal(settings, before, doc["machine"]["work"].unwrap()))
          fragment = tomlkit.parse(after[0].decode("utf-8")).unwrap()
          return publish(_proposal(settings, before, fragment))
        finally:
          # 清理只需要目录句柄与文件身份，拒绝超限时也不能无界读回正文。
          with tree.parent(name) as (parent, filename):
            try:
              remaining = os.stat(filename, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
              remaining = None
            if remaining is not None:
              if not stat.S_ISREG(remaining.st_mode) or remaining.st_uid != os.geteuid() or remaining.st_nlink != 1:
                raise TermcfgError(4, "work_unsafe_edited_fragment", "work config edit")
              os.unlink(filename, dir_fd=parent)
              os.fsync(parent)
    except TermcfgError:
      raise
    except StateError as error:
      raise TermcfgError(error.exit_code, "work_fragment_editor_io_failed", "work config edit") from None
    except (ValueError, TypeError, KeyError, UnicodeError):
      raise TermcfgError(2, "work_invalid_edited_fragment", "work config edit") from None
