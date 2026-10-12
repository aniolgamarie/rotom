"""受信 Shell 计划的纯 bwrap argv 编译；不打开 FD、不执行或启用后端。

源与密封脚本/过滤器 FD 的实际身份由执行组装验证，这里仅检查封闭形状及唯一性。
尾部要求已批准程序遵守 Bash --noprofile/--norc 契约，实际正控制仍待独立验收。
"""

from pathlib import PurePosixPath
import re

from .schema import ConfigError


PRIVATE = "/.rotom-shell"
SCRIPT = PRIVATE + "/script"
RESERVED = tuple(PurePosixPath(path) for path in (PRIVATE, "/proc", "/dev", "/sys"))


def _invalid():
  raise ConfigError("pi-shell-argv")


def _closed(value, keys):
  if type(value) is not dict or set(value) != set(keys): _invalid()


def _sha(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value): _invalid()


def _path(value):
  if (type(value) is not str or not value or len(value) > 4096 or "\\" in value
      or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
    _invalid()
  path = PurePosixPath(value)
  if not path.is_absolute() or str(path) != value or value.startswith("//") or ".." in path.parts or path == PurePosixPath("/"):
    _invalid()
  return path


def _overlap(left, right):
  return left.is_relative_to(right) or right.is_relative_to(left)


def _destination(value):
  path = _path(value)
  if path == PurePosixPath("/tmp") or any(_overlap(path, root) for root in RESERVED): _invalid()
  return path


def _fd(value):
  if type(value) is not int or value <= 2: _invalid()


def compile_argv(plan, *, source_fds, script_fd, seccomp_fd, mask_fds):
  """返回不含 helper argv0 的固定尾部；调用者只可显式继承核验过的 FD。"""
  _closed(plan, ("schema_version", "platform", "network", "mounts", "symlinks", "masks", "cwd", "seccomp_digest"))
  if type(plan["schema_version"]) is not int or plan["schema_version"] != 1 or plan["platform"] != "linux-x86_64" or plan["network"] != "deny":
    _invalid()
  _sha(plan["seccomp_digest"])
  for key in ("mounts", "symlinks", "masks"):
    if type(plan[key]) is not list: _invalid()
  mounts, executable = {}, None
  for row in plan["mounts"]:
    _closed(row, ("path", "kind", "identity", "writable", "role"))
    path = _destination(row["path"])
    if (path in mounts or type(row["writable"]) is not bool
        or any(type(row[key]) is not str for key in ("kind", "role"))): _invalid()
    if row["kind"] == "directory":
      _sha(row["identity"])
      if row["role"] not in ("system", "workspace") or row["role"] == "system" and row["writable"]: _invalid()
    elif row["kind"] == "file":
      if row["role"] != "executable" or row["writable"] or executable is not None: _invalid()
      identity = row["identity"]
      _closed(identity, ("path", "device", "inode", "uid", "sha256"))
      if _path(identity["path"]) != path: _invalid()
      _sha(identity["sha256"])
      if any(type(identity[key]) is not int or identity[key] < 0 for key in ("device", "inode", "uid")): _invalid()
      executable = path
    else: _invalid()
    mounts[path] = row
  if executable is None: _invalid()
  directories = [path for path, row in mounts.items() if row["kind"] == "directory"]
  system = [path for path, row in mounts.items() if row["kind"] == "directory" and row["role"] == "system"]
  _closed(plan["cwd"], ("path", "identity"))
  cwd = _path(plan["cwd"]["path"]); _sha(plan["cwd"]["identity"])
  if not any(cwd.is_relative_to(path) and mounts[path]["role"] == "workspace" for path in directories): _invalid()
  masks = {}
  for row in plan["masks"]:
    _closed(row, ("path", "kind", "identity"))
    path = _destination(row["path"]); _sha(row["identity"])
    if row["kind"] not in ("directory", "file") or any(_overlap(path, mask) for mask in masks): _invalid()
    if not any(path.is_relative_to(root) for root in directories): _invalid()
    if any(target.is_relative_to(path) for target in (cwd, *mounts)): _invalid()
    masks[path] = row
  aliases = {}
  for row in plan["symlinks"]:
    _closed(row, ("path", "target"))
    path, target = _destination(row["path"]), _path(row["target"])
    if path in aliases or any(_overlap(path, source) for source in mounts): _invalid()
    if any(_overlap(path, alias) for alias in aliases): _invalid()
    if not any(target.is_relative_to(root) for root in system): _invalid()
    if any(target.is_relative_to(mask) for mask in masks): _invalid()
    aliases[path] = target
  if type(source_fds) is not dict or set(source_fds) != {str(path) for path in mounts}: _invalid()
  file_masks = {str(path) for path, row in masks.items() if row["kind"] == "file"}
  if type(mask_fds) is not dict or set(mask_fds) != file_masks: _invalid()
  descriptors = [*source_fds.values(), *mask_fds.values(), script_fd, seccomp_fd]
  for fd in descriptors: _fd(fd)
  if len(set(descriptors)) != len(descriptors): _invalid()
  argv = ["--unshare-user", "--disable-userns", "--assert-userns-disabled", "--unshare-pid", "--unshare-net",
    "--unshare-ipc", "--unshare-uts", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
  for name, value in (("HOME", PRIVATE + "/home"), ("TMPDIR", "/tmp"), ("PATH", "/usr/bin:/bin"),
      ("LANG", "C.UTF-8"), ("LC_ALL", "C.UTF-8"), ("TERM", "dumb")):
    argv.extend(("--setenv", name, value))
  argv.extend(("--perms", "0700", "--tmpfs", PRIVATE, "--perms", "0700", "--dir", PRIVATE + "/home",
    "--perms", "1777", "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev"))
  for path, target in sorted(aliases.items(), key=lambda pair: str(pair[0])):
    argv.extend(("--symlink", str(target), str(path)))
  for path, row in sorted(mounts.items(), key=lambda pair: (len(pair[0].parts), str(pair[0]))):
    argv.extend(("--bind-fd" if row["writable"] else "--ro-bind-fd", str(source_fds[str(path)]), str(path)))
  argv.extend(("--perms", "0400", "--ro-bind-data", str(script_fd), SCRIPT, "--seccomp", str(seccomp_fd)))
  for path, row in sorted(masks.items(), key=lambda pair: (len(pair[0].parts), str(pair[0]))):
    if row["kind"] == "directory": argv.extend(("--perms", "0000", "--tmpfs", str(path), "--remount-ro", str(path)))
    else: argv.extend(("--perms", "0000", "--ro-bind-data", str(mask_fds[str(path)]), str(path)))
  argv.extend(("--chdir", str(cwd), "--", str(executable), "--noprofile", "--norc", SCRIPT))
  return tuple(argv)
