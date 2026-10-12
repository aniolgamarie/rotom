"""为后续Shell挂载持有已批准源的FD；不是完整挂载计划或可执行授权。

仅消费受信准备器的公开投影，不接收脚本、模型路径或任意FD。
固定bwrap的bind-fd仍会解析proc路径并在挂载后核对inode，且递归包含子挂载。
调用者必须另外验证所选helper、系统根、deny/子挂载/别名/socket边界和最终挂载顺序。
本模块不构造可启动argv，不修改继承位、不执行helper或开放生产后端。
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat

from .activity import digest
from .paths import PathError, _absolute_directory, configured_path
from .schema import ConfigError
from .storage import Conflict


def _invalid():
  raise ConfigError("pi-shell-sources")


def _closed(value, keys):
  if type(value) is not dict or set(value) != set(keys): _invalid()


def _sha(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value): _invalid()


def _path(value):
  if type(value) is not str or len(value) > 4096 or any(0xD800 <= ord(c) <= 0xDFFF for c in value): _invalid()
  path = configured_path(value)
  if str(path) != value or path == Path("/"): _invalid()
  return path


def _directory_identity(info):
  return digest({"device": str(info.st_dev), "inode": str(info.st_ino), "uid": str(info.st_uid)})


def _directory(path, expected):
  with _absolute_directory(path) as fd:
    if _directory_identity(os.fstat(fd)) != expected: raise Conflict("ROOT_IDENTITY")
    return os.dup(fd)


def _file_snapshot(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
    info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _executable(expected):
  path = _path(expected["path"])
  with _absolute_directory(path.parent) as parent:
    before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_mode & 0o6022
        or before.st_uid not in (0, os.geteuid()) or not os.access(path, os.X_OK)):
      raise Conflict("SHELL_SOURCE_IDENTITY")
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
      if _file_snapshot(os.fstat(fd)) != _file_snapshot(before): raise Conflict("SHELL_SOURCE_IDENTITY")
      sha = hashlib.sha256()
      while block := os.read(fd, 1024 * 1024): sha.update(block)
      actual = {"path": str(path), "device": before.st_dev, "inode": before.st_ino, "uid": before.st_uid, "sha256": sha.hexdigest()}
      if (actual != expected or _file_snapshot(os.fstat(fd)) != _file_snapshot(before)
          or _file_snapshot(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != _file_snapshot(before)):
        raise Conflict("SHELL_SOURCE_IDENTITY")
      os.lseek(fd, 0, os.SEEK_SET)
      return fd
    except BaseException:
      os.close(fd)
      raise


def _projection(value):
  # 只核对本原语需要的封闭身份；策略/许可和完整后端证明仍由外层负责。
  _closed(value, ("resolution", "physical"))
  resolved, physical = value["resolution"], value["physical"]
  _closed(resolved, ("kind", "tool_name", "target", "read_roots", "write_roots", "workspace_keys", "network", "services", "backend", "policy"))
  _closed(physical, ("cwd", "cwd_identity", "executable_identity", "denied_paths", "readonly_paths", "read_roots", "write_roots", "timeout_seconds"))
  if (resolved["kind"] != "shell-command" or resolved["tool_name"] != "bash"
      or resolved["backend"] != "linux-bwrap-v1" or resolved["network"] != "deny" or resolved["services"] != []): _invalid()
  policy = resolved["policy"]
  fields = {"generation", "policy_digest", "ceiling_digest", "hard_policy", "requires_human"}
  if type(policy) is not dict or set(policy) not in (fields, fields | {"approval"}): _invalid()
  _sha(policy["policy_digest"]); _sha(policy["ceiling_digest"])
  if (type(policy["generation"]) is not int or not 1 <= policy["generation"] <= 2**53 - 1
      or policy["hard_policy"] != "allow" or type(policy["requires_human"]) is not bool): _invalid()
  if "approval" in policy:
    if (type(policy["approval"]) is not str or policy["approval"] not in ("human", "reviewer", "deterministic-policy")
        or policy["requires_human"] != (policy["approval"] == "human")): _invalid()
  elif policy["requires_human"] is not True:
    # Shell旧投影只有人工语义；缺等级不能从False推断新的自动准入。
    _invalid()
  if type(resolved["workspace_keys"]) is not list: _invalid()
  for key in resolved["workspace_keys"]: _sha(key)
  if len(set(resolved["workspace_keys"])) != len(resolved["workspace_keys"]): _invalid()
  _closed(resolved["target"], ("command_ref", "executable", "timeout_ms"))
  command_ref = resolved["target"]["command_ref"]
  if type(command_ref) is not str or not re.fullmatch(r"tool:[a-z][a-z0-9_-]{0,63}", command_ref): _invalid()
  executable = physical["executable_identity"]
  _closed(executable, ("path", "device", "inode", "uid", "sha256"))
  _path(executable["path"]); _sha(executable["sha256"])
  if any(type(executable[key]) is not int or executable[key] < 0 for key in ("device", "inode", "uid")): _invalid()
  if resolved["target"]["executable"] != executable: _invalid()
  timeout = physical["timeout_seconds"]
  if (type(timeout) is not int or not 1 <= timeout <= (2**53 - 1) // 1000
      or type(resolved["target"]["timeout_ms"]) is not int or resolved["target"]["timeout_ms"] != timeout * 1000): _invalid()
  cwd = _path(physical["cwd"]); _sha(physical["cwd_identity"])
  for key in ("denied_paths", "readonly_paths"):
    if type(physical[key]) is not list: _invalid()
    for path in physical[key]: _path(path)
  roots = {}
  for key in ("read_roots", "write_roots"):
    rows = resolved[key]
    if type(rows) is not list or type(physical[key]) is not list: _invalid()
    paths = []
    for row in rows:
      _closed(row, ("path", "identity")); _path(row["path"]); _sha(row["identity"])
      if row["path"] in paths: _invalid()
      paths.append(row["path"])
      old = roots.get(row["path"])
      if old is not None and old["identity"] != row["identity"]: raise Conflict("ROOT_IDENTITY")
      roots[row["path"]] = {**row, "writable": key == "write_roots" or old is not None and old["writable"]}
    if paths != physical[key]: _invalid()
  if not resolved["read_roots"] or not any(cwd.is_relative_to(Path(row["path"])) for row in resolved["read_roots"]): _invalid()
  return roots, physical


@contextmanager
def pin_shell_sources(public):
  """持有只读/CLOEXEC源FD直至退出；writable只描述将来挂载的权限，不授权写入。"""
  owned = []
  def keep(fd):
    try: info = os.fstat(fd)
    except BaseException:
      os.close(fd)
      raise
    owned.append((fd, (info.st_dev, info.st_ino)))
    return fd
  try:
    try:
      roots, physical = _projection(deepcopy(public))
      mounted = [{"path": path, "writable": row["writable"], "fd": keep(_directory(Path(path), row["identity"]))}
        for path, row in sorted(roots.items(), key=lambda pair: (len(Path(pair[0]).parts), pair[0]))]
      cwd_fd = keep(_directory(Path(physical["cwd"]), physical["cwd_identity"]))
      executable_fd = keep(_executable(physical["executable_identity"]))
      # 完成所有打开后重验目录名字；交付后使用持有的FD，不能重新按字符串打开源。
      for path, row in roots.items():
        with _absolute_directory(Path(path)) as current:
          if _directory_identity(os.fstat(current)) != row["identity"]: raise Conflict("ROOT_IDENTITY")
      with _absolute_directory(Path(physical["cwd"])) as current:
        if _directory_identity(os.fstat(current)) != physical["cwd_identity"]: raise Conflict("ROOT_IDENTITY")
    except (OSError, PathError, ValueError, TypeError, KeyError):
      raise ConfigError("pi-shell-sources") from None
    yield {"roots": mounted, "cwd_fd": cwd_fd, "executable_fd": executable_fd}
  finally:
    for fd, identity in reversed(owned):
      try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == identity: os.close(fd)
      except OSError:
        pass
