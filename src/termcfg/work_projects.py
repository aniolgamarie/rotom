"""只读项目边界与有界发现；目录规则始终来自所选私人配置。"""
from copy import deepcopy
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import stat

from .errors import TermcfgError
from .work_config import literal


def invalid(reason="work_invalid_project_configuration"):
  return TermcfgError(2, reason, "work config check")


def directory(value, *, base=None, home=None):
  value = literal(str(value))
  if value.startswith("~/"):
    value = str(Path(home or os.environ.get("HOME", "")) / value[2:])
  path = Path(value)
  if not path.is_absolute():
    path = Path(base or Path.cwd()) / path
  try:
    path = path.resolve(strict=True)
    if not path.is_dir() or not os.access(path, os.R_OK | os.X_OK):
      raise OSError()
    return path
  except (OSError, ValueError, RuntimeError):
    raise invalid("work_existing_directory_required") from None


def _git_marker(path):
  marker = path / ".git"
  try:
    info = marker.lstat()
    if stat.S_ISDIR(info.st_mode):
      return True
    if stat.S_ISREG(info.st_mode) and info.st_size <= 8192:
      content = marker.read_text(encoding="utf-8").strip()
      return content.startswith("gitdir: ") and bool(content[8:].strip()) and "\n" not in content
  except (OSError, UnicodeError):
    pass
  return False


def canonical_boundary(path, mode):
  path = directory(path)
  if mode == "directory":
    return path
  if mode != "git":
    raise invalid()
  for candidate in (path, *path.parents):
    if _git_marker(candidate):
      return candidate
  raise invalid("work_git_checkout_required")


def normalize_work(work, *, local_path, home=None):
  from agentcfg.schema import validate_document, ConfigError
  from agentcfg.config import validate_work_input
  try:
    document = {"schema_version": 1, "machine": {"id": "validation", "work": work}}
    validate_document("local", document)
    validate_work_input(document)
  except (ConfigError, TypeError, KeyError, ValueError):
    raise invalid() from None
  value = deepcopy(work)
  base = Path(local_path).absolute().parent
  templates = value.get("templates", {})
  for template in templates.values():
    order, types = template["order"], template["tab_types"]
    if len(order) != len(set(order)) or set(order) != set(types) or template["initial"] not in types:
      raise invalid("work_invalid_template_order")
    for definition in types.values():
      literal(definition["label"])
      definition.setdefault("cwd", {"from": "workspace_start"})
  value.setdefault("include_rotom", True)
  if value["include_rotom"] or "rotom_template" in value:
    value.setdefault("rotom_template", "development")
    if value["rotom_template"] not in templates:
      raise invalid("work_unknown_template")
  sources = value.setdefault("sources", [])
  ids = set()
  for source in sources:
    if source["id"] in ids:
      raise invalid("work_duplicate_source_id")
    ids.add(source["id"])
    source["path"] = str(directory(source["path"], base=base, home=home))
    source.setdefault("depth", 1)
    source.setdefault("exclude_hidden", True)
    source.setdefault("exclude", [])
    source.setdefault("follow_symlinks", False)
    if type(source["depth"]) is not int or not 1 <= source["depth"] <= 32:
      raise invalid()
    if any("/" in glob or not glob for glob in source["exclude"]):
      raise invalid("work_exclude_requires_basename_glob")
    if source["template"] not in templates:
      raise invalid("work_unknown_template")
  named = {}
  projects = {}
  workspaces = []
  for item in value.setdefault("workspaces", []):
    if item["template"] not in templates:
      raise invalid("work_unknown_template")
    if item["kind"] == "project":
      item["path"] = str(canonical_boundary(directory(item["path"], base=base, home=home), item["mode"]))
      previous = projects.get(item["path"])
      if previous is not None:
        if previous != item:
          raise invalid("work_conflicting_project_definitions")
        continue
      projects[item["path"]] = item
    else:
      literal(item["title"])
      if "start_path" in item:
        item["start_path"] = str(directory(item["start_path"], base=base, home=home))
      previous = named.get(item["id"])
      if previous is not None:
        if previous != item:
          raise invalid("work_duplicate_named_id")
        continue
      named[item["id"]] = item
    workspaces.append(item)
  value["workspaces"] = workspaces
  return value


@dataclass(frozen=True)
class Candidate:
  kind: str
  key: str
  title: str
  template: str
  origin: str
  mode: str | None = None
  start_path: str | None = None


@dataclass(frozen=True)
class Discovery:
  candidates: tuple
  diagnostics: tuple


def source_paths(source, diagnostics):
  root = Path(source["path"])
  visited = {root}
  pending = [(root, 0)]
  examined = 0
  while pending:
    parent, depth = pending.pop()
    try:
      children = sorted(parent.iterdir(), key=lambda item: item.name)
    except OSError:
      diagnostics.append({"source": source["id"], "reason": "work_source_unreadable"})
      continue
    for child in children:
      examined += 1
      if examined > 20000:
        raise invalid("work_source_discovery_limit")
      if ((source["exclude_hidden"] and child.name.startswith(".")) or
          any(fnmatch.fnmatchcase(child.name, pattern) for pattern in source["exclude"])):
        continue
      try:
        if child.is_symlink() and not source["follow_symlinks"]:
          continue
        canonical = child.resolve(strict=True)
        if not canonical.is_relative_to(root) or canonical in visited or not canonical.is_dir():
          continue
        visited.add(canonical)
      except (OSError, RuntimeError):
        continue
      checkout = _git_marker(canonical)
      if source["mode"] == "directory" or checkout:
        yield canonical
      if depth + 1 < source["depth"] and not (source["mode"] == "git" and checkout):
        pending.append((canonical, depth + 1))


def _executing_root(root):
  from .work_config import ROOT
  root = Path(root).resolve()
  return root == ROOT.resolve() and all((root / name).is_file() for name in
    ("work", "pyproject.toml", "src/termcfg/work.py"))


def discover(settings):
  if settings.model != "structured-v1":
    raise invalid("work_structured_opt_in_required")
  value = normalize_work(settings.structured, local_path=settings.local_path)
  selected, diagnostics = {}, []
  def add(candidate, priority):
    key = (candidate.kind, candidate.key)
    old = selected.get(key)
    if old is None or priority > old[0]:
      selected[key] = (priority, candidate)
    elif priority == old[0] and (candidate.template, candidate.mode, candidate.start_path) != (
        old[1].template, old[1].mode, old[1].start_path):
      raise invalid("work_conflicting_project_definitions")
  if value["include_rotom"]:
    if _executing_root(settings.repo_root):
      path = str(Path(settings.repo_root).resolve())
      add(Candidate("project", path, Path(path).name, value["rotom_template"], "builtin", "directory", path), (0, 0))
    else:
      diagnostics.append({"origin": "builtin", "reason": "work_executing_root_unverified"})
  for source in value["sources"]:
    for path in source_paths(source, diagnostics):
      add(Candidate("project", str(path), path.name, source["template"], "source:" + source["id"],
        source["mode"], str(path)), (1, len(Path(source["path"]).parts)))
  for item in value["workspaces"]:
    if item["kind"] == "named":
      add(Candidate("named", item["id"], item["title"], item["template"], "explicit", start_path=item.get("start_path")), (2, 0))
    else:
      path = item["path"]
      add(Candidate("project", path, Path(path).name, item["template"], "explicit", item["mode"], path), (2, 0))
  return Discovery(tuple(item[1] for _, item in sorted(selected.items())), tuple(diagnostics))


def resolve_project(settings, path):
  actual = directory(path)
  candidates = [item for item in discover(settings).candidates if item.kind == "project"]
  exact = [item for item in candidates if Path(item.key) == actual]
  if len(exact) == 1:
    return exact[0]
  covered = [item for item in candidates if actual.is_relative_to(Path(item.key))]
  if covered:
    deepest = max(len(Path(item.key).parts) for item in covered)
    covered = [item for item in covered if len(Path(item.key).parts) == deepest]
  if len(covered) != 1:
    raise invalid("work_project_not_uniquely_registered")
  return covered[0]
