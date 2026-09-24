"""原生 Git 文件选择的封闭计划；实际 Git 执行继续交给已有监督命令。"""
from pathlib import Path

from .paths import PathError, relative_path
from .schema import ConfigError
from .storage import Conflict


GIT_SELECTIONS = {"cached": ["--cached"], "others": ["--others", "--exclude-standard"],
  "ignored": ["--others", "--ignored", "--exclude-standard"]}


def requested_categories(params):
  for name in GIT_SELECTIONS:
    if name in params and type(params[name]) is not bool: raise ConfigError("readseek-git-selection")
  selected = [name for name in GIT_SELECTIONS if params.get(name, False)]
  return selected or ["cached", "others"]


def git_queries(root, params):
  value = Path(root)
  if not value.is_absolute() or ".." in value.parts: raise ConfigError("readseek-git-root")
  return {name: ["-C", str(value), "ls-files", "-z", *GIT_SELECTIONS[name]] for name in requested_categories(params)}


def decode_git_paths(body, *, max_files=10000):
  if not isinstance(body, bytes) or len(body) > 8 * 1024 * 1024 or body and not body.endswith(b"\0"):
    raise Conflict("READSEEK_SELECTION_INVALID")
  try: names = body[:-1].decode("utf-8").split("\0") if body else []
  except UnicodeError: raise Conflict("READSEEK_SELECTION_INVALID") from None
  if len(names) > max_files: raise Conflict("READSEEK_SELECTION_LIMIT")
  result = set()
  for name in names:
    try: path = relative_path(name)
    except PathError: raise Conflict("READSEEK_SELECTION_INVALID") from None
    if ".git" in path.parts or path.as_posix() != name: raise Conflict("READSEEK_SELECTION_INVALID")
    result.add(name)
  return sorted(result)


def selection_manifest(snapshot, categories):
  if not isinstance(categories, dict) or set(categories) - GIT_SELECTIONS.keys(): raise ConfigError("readseek-git-selection")
  exported = {row["path"] for row in snapshot["entries"]}
  result = {}
  selected = set()
  for name, paths in categories.items():
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths): raise ConfigError("readseek-git-selection")
    for path in paths: relative_path(path)
    selected.update(paths)
    result[name] = sorted(set(paths) & exported)
  if exported - selected: raise Conflict("READSEEK_SELECTION_EXPANDED")
  return {"schema_version": 1, "snapshot_root": snapshot["snapshot_root"], "snapshot_digest": snapshot["snapshot_digest"], "categories": result}
