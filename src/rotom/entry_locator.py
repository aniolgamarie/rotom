"""安装入口的标准库定位协议；本文件完整嵌入公开 launcher。"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys


PROTOCOL_SOURCES = (
  "rotom", "src/rotom/entry.py", "src/rotom/entry_locator.py",
  "schemas/rotom/entry-binding.schema.json", "terminals/zsh/rotom",
)
MAX_BYTES = 1024 * 1024


class LocatorError(Exception):
  def __init__(self, code, reason):
    self.code = code
    self.reason = reason
    super().__init__(reason)


def _fail(code, reason):
  raise LocatorError(code, reason)


def _absolute(value):
  if not isinstance(value, str) or not value or "\x00" in value:
    _fail(2, "invalid_entry_binding")
  path = Path(value)
  if not path.is_absolute() or str(path) != value or any(part in (".", "..") for part in value.split("/")):
    _fail(2, "invalid_entry_binding")
  return path


def _directory(path, *, private=False):
  """逐级 nofollow 打开；不信任检查后又被换成链接的祖先。"""
  path = _absolute(str(path))
  fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  try:
    for part in (None, *path.parts[1:]):
      if part is not None:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = child
      info = os.fstat(fd)
      if info.st_uid not in (0, os.getuid()):
        _fail(4, "unsafe_entry_directory")
      # 系统临时根允许 root 的 sticky 目录；其子目录仍逐级验证。
      if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
        _fail(4, "unsafe_entry_directory")
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
      _fail(4, "unsafe_entry_directory")
    return fd
  except BaseException:
    os.close(fd)
    raise


def _identity(info):
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
    "mode": stat.S_IMODE(info.st_mode)}


def _file(path, *, mode=None, executable=False):
  limit = 64 * MAX_BYTES if executable else MAX_BYTES
  parent = _directory(path.parent)
  try:
    fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
      info = os.fstat(fd)
      if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid not in (0, os.getuid())
          or info.st_mode & 0o022 or mode is not None and
          (stat.S_IMODE(info.st_mode) != mode or info.st_uid != os.getuid())):
        _fail(4, "unsafe_entry_file")
      if executable and not info.st_mode & 0o111:
        _fail(5, "prepared_entry_python_missing")
      if info.st_size > limit:
        _fail(2, "invalid_entry_binding")
      data = b""
      while len(data) <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - len(data)))
        if not chunk:
          break
        data += chunk
      after = os.fstat(fd)
      visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
      fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
      if any(getattr(info, key) != getattr(after, key) or getattr(info, key) != getattr(visible, key) for key in fields):
        _fail(4, "entry_source_changed")
      result = _identity(info)
      result.update(size=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
        sha256=hashlib.sha256(data).hexdigest())
      return data, result
    finally:
      os.close(fd)
  finally:
    os.close(parent)


def _root_identity(path):
  fd = _directory(path)
  try:
    return _identity(os.fstat(fd))
  finally:
    os.close(fd)


def _resolve_trusted(path):
  """跟随正常 venv 链接，同时核实链接经过的每个目录和链接所有者。"""
  pending = list(_absolute(str(path)).parts[1:])
  current = Path("/")
  links = []
  while pending:
    part = pending.pop(0)
    if part in ("", "."):
      continue
    if part == "..":
      current = current.parent
      continue
    parent = _directory(current)
    try:
      info = os.stat(part, dir_fd=parent, follow_symlinks=False)
      if stat.S_ISLNK(info.st_mode):
        if len(links) >= 40 or info.st_uid not in (0, os.getuid()) or info.st_nlink != 1:
          _fail(4, "unsafe_prepared_python_link")
        target = os.readlink(part, dir_fd=parent)
        observed = os.stat(part, dir_fd=parent, follow_symlinks=False)
        if _identity(info) != _identity(observed) or info.st_ctime_ns != observed.st_ctime_ns:
          _fail(4, "entry_source_changed")
        links.append({"path": str(current / part), "identity": _identity(info), "target": target})
        pending = list(Path(target).parts[1:] if target.startswith("/") else Path(target).parts) + pending
        if target.startswith("/"):
          current = Path("/")
      else:
        current = current / part
        if pending:
          fd = _directory(current)
          os.close(fd)
    finally:
      os.close(parent)
  return current, links


def source_snapshot(repository):
  root = _absolute(str(repository))
  try:
    identity = _root_identity(root)
    sources = {relative: _file(root / relative)[1] for relative in PROTOCOL_SOURCES}
    environment, environment_links = _resolve_trusted(root / ".venv")
    environment_identity = _root_identity(environment)
    config = _file(environment / "pyvenv.cfg")[1]
    interpreter, python_links = _resolve_trusted(environment / "bin/python")
    # 解释器可以是正常 venv 符号链接；只接受明确准备环境解析出的可信物理文件。
    python = _file(interpreter, executable=True)[1]
    if _root_identity(root) != identity:
      _fail(4, "entry_source_changed")
    return {"root": identity, "sources": sources, "environment": {
      "path": str(environment), "identity": environment_identity, "config": config,
      "python_path": str(interpreter), "python": python,
      "environment_links": environment_links, "python_links": python_links}}
  except LocatorError:
    raise
  except FileNotFoundError:
    _fail(5, "prepared_entry_source_missing")
  except OSError:
    _fail(4, "unsafe_entry_source")


def _pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      _fail(2, "invalid_entry_binding")
    result[key] = value
  return result


def _shape(value, fields):
  if not isinstance(value, dict) or set(value) != set(fields):
    _fail(2, "invalid_entry_binding")


def _stat_shape(value, *, file=False):
  fields = ("device", "inode", "uid", "mode")
  _shape(value, (*fields, "size", "mtime_ns", "ctime_ns", "sha256") if file else fields)
  for key in fields + (("size", "mtime_ns", "ctime_ns") if file else ()):
    if type(value[key]) is not int or value[key] < 0:
      _fail(2, "invalid_entry_binding")
  if value["mode"] > 0o7777:
    _fail(2, "invalid_entry_binding")
  if file and (not isinstance(value["sha256"], str) or len(value["sha256"]) != 64
      or any(c not in "0123456789abcdef" for c in value["sha256"])):
    _fail(2, "invalid_entry_binding")


def parse_binding(data, *, check_source=True):
  try:
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
      _fail(2, "invalid_entry_binding")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
      parse_constant=lambda _: _fail(2, "invalid_entry_binding"))
    _shape(value, ("schema_version", "launcher_protocol", "repository", "repository_identity", "entry_relative", "python_relative"))
    if any(type(value[key]) is not int or value[key] != 1 for key in ("schema_version", "launcher_protocol")):
      _fail(2, "invalid_entry_binding")
    root = _absolute(value["repository"])
    if value["entry_relative"] != "rotom" or value["python_relative"] != ".venv/bin/python":
      _fail(2, "invalid_entry_binding")
    snapshot = value["repository_identity"]
    _shape(snapshot, ("root", "sources", "environment"))
    _stat_shape(snapshot["root"])
    _shape(snapshot["sources"], PROTOCOL_SOURCES)
    for source in snapshot["sources"].values():
      _stat_shape(source, file=True)
    environment = snapshot["environment"]
    _shape(environment, ("path", "identity", "config", "python_path", "python", "environment_links", "python_links"))
    _absolute(environment["path"])
    _absolute(environment["python_path"])
    _stat_shape(environment["identity"])
    _stat_shape(environment["config"], file=True)
    _stat_shape(environment["python"], file=True)
    for name in ("environment_links", "python_links"):
      if not isinstance(environment[name], list) or len(environment[name]) > 40:
        _fail(2, "invalid_entry_binding")
      for link in environment[name]:
        _shape(link, ("path", "identity", "target"))
        _absolute(link["path"])
        _stat_shape(link["identity"])
        if not isinstance(link["target"], str) or not link["target"] or "\x00" in link["target"]:
          _fail(2, "invalid_entry_binding")
    if check_source and source_snapshot(root) != snapshot:
      _fail(4, "entry_source_changed")
    return value
  except LocatorError:
    raise
  except (ValueError, UnicodeError, TypeError, KeyError, RecursionError):
    _fail(2, "invalid_entry_binding")


def resolve_installed_invocation(installed, args):
  path = _absolute(str(installed))
  if path.parts[-3:] != (".local", "bin", "rotom"):
    _fail(4, "unsupported_entry_layout")
  try:
    _file(path, mode=0o700)
    home = path.parents[2]
    directory = home / ".local/share/rotom"
    fd = _directory(directory, private=True)
    os.close(fd)
    data, _ = _file(directory / "entry.json", mode=0o600)
    binding = parse_binding(data)
    repository = Path(binding["repository"])
    python = str(repository / ".venv/bin/python")
    return python, (python, "-I", "-B", str(repository / "rotom"), *args)
  except LocatorError:
    raise
  except FileNotFoundError:
    _fail(5, "prepared_entry_source_missing")
  except OSError:
    _fail(4, "unsafe_installed_entry")


def main(argv=None):
  values = sys.argv[1:] if argv is None else argv
  if not values:
    _fail(2, "installed_entry_required")
  python, args = resolve_installed_invocation(values[0], values[1:])
  os.execv(python, args)


if __name__ == "__main__":
  try:
    main()
  except LocatorError as error:
    print("rotom: " + error.reason + "; use reviewed rotom term plan/apply --entry-repo to repair", file=sys.stderr)
    raise SystemExit(error.code)
