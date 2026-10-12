"""受信单线程 PID1 worker 的 FD 准备/exec；不签发许可或启用生产后端。

调用方另行验证运行包收据、许可和租约；helper 来源不能自证授权。
普通文件/目录只绑定观察到的身份，不声称源内容或目录树永久不可变。
"""

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, field
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import re
import stat
import sys

from .activity import digest
from .paths import PathError, _absolute_directory, configured_path
from .pi_assets import binary_platform
from .pi_shell_argv import compile_argv
from .pi_shell_mounts import pin_mount_plan
from .pi_shell_script import _close_owned, sealed_data, sealed_script
from .pi_shell_seccomp import compile_filter
from .process import DependencyError
from .schema import ConfigError


_FD_EXEC_SUPPORTED = os.execve in os.supports_fd
_SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
_ACTIVE = {}


@dataclass(frozen=True)
class PreparedShellExecution:
  argv: tuple = field(repr=False)
  helper_fd: int = field(repr=False)
  pass_fds: tuple = field(repr=False)
  script_fd: int = field(repr=False)
  seccomp_fd: int = field(repr=False)
  mask_fds: tuple = field(repr=False)
  snapshots: tuple = field(repr=False)


def _invalid():
  raise ConfigError("pi-shell-execution")


def _exec_invalid():
  raise ConfigError("pi-shell-exec-unavailable")


def _snapshot(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
    info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _sha(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value): _invalid()


def _helper(path, expected):
  if type(path) is not str or len(path) > 4096 or any(0xD800 <= ord(char) <= 0xDFFF for char in path): _invalid()
  literal = configured_path(path)
  if str(literal) != path or literal == Path("/"): _invalid()
  with _absolute_directory(literal.parent) as parent:
    before = os.stat(literal.name, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o700): _invalid()
    fd = os.open(literal.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
      if _snapshot(os.fstat(fd)) != _snapshot(before): _invalid()
      header = os.read(fd, 64)
      if binary_platform(header) != "linux-x86_64": _invalid()
      sha = hashlib.sha256(header)
      while block := os.read(fd, 1024 * 1024): sha.update(block)
      if (sha.hexdigest() != expected or _snapshot(os.fstat(fd)) != _snapshot(before)
          or _snapshot(os.stat(literal.name, dir_fd=parent, follow_symlinks=False)) != _snapshot(before)):
        _invalid()
      os.lseek(fd, 0, os.SEEK_SET)
      return fd, (before.st_dev, before.st_ino)
    except BaseException:
      _close_owned(fd, (before.st_dev, before.st_ino))
      raise


@contextmanager
def prepare_shell_execution(public, command, *, helper_path, helper_identity, plan_digest,
    system_roots=("/usr", "/bin", "/lib", "/lib64"), mountinfo=None):
  """持有核验后的所有源/密封 FD；仅作用域内构造的对象可以尝试 exec 一次。"""
  with ExitStack() as stack:
    try:
      _sha(helper_identity); _sha(plan_digest)
      pinned = stack.enter_context(pin_mount_plan(public, system_roots=system_roots, mountinfo=mountinfo))
      plan = pinned["plan"]
      if digest(plan) != plan_digest: _invalid()
      helper_fd, helper_identity_snapshot = _helper(helper_path, helper_identity)
      stack.callback(_close_owned, helper_fd, helper_identity_snapshot)
      script_fd = stack.enter_context(sealed_script(command))
      seccomp_fd = stack.enter_context(sealed_data(compile_filter(plan["platform"])))
      masks = {row["path"]: stack.enter_context(sealed_data(b"")) for row in plan["masks"] if row["kind"] == "file"}
      tail = compile_argv(plan, source_fds=pinned["source_fds"], script_fd=script_fd,
        seccomp_fd=seccomp_fd, mask_fds=masks)
      pass_fds = tuple([*pinned["source_fds"].values(), script_fd, seccomp_fd, *masks.values()])
      descriptors = (helper_fd, *pass_fds)
      if len(set(descriptors)) != len(descriptors) or any(os.get_inheritable(fd) for fd in descriptors): _invalid()
      value = PreparedShellExecution(argv=(helper_path, *tail), helper_fd=helper_fd, pass_fds=pass_fds,
        script_fd=script_fd, seccomp_fd=seccomp_fd, mask_fds=tuple(masks.values()),
        snapshots=tuple((fd, _snapshot(os.fstat(fd))) for fd in descriptors))
    except (OSError, PathError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, DependencyError):
      raise ConfigError("pi-shell-execution") from None
    _ACTIVE[id(value)] = {"value": value, "attempted": False, "exportable": True, "plan_digest": plan_digest}
    try: yield value
    finally: _ACTIVE.pop(id(value), None)


def _task_ids():
  return tuple(os.listdir("/proc/self/task"))


def _fd_inventory():
  with os.scandir("/proc/self/fd") as entries:
    names = [entry.name for entry in entries]
  if any(not name.isdigit() for name in names): _exec_invalid()
  return tuple(sorted(int(name) for name in names))


def _exec_fd(fd, argv, environment):
  os.execve(fd, argv, environment)


def _verify(value):
  for fd, expected in value.snapshots:
    if _snapshot(os.fstat(fd)) != expected: _exec_invalid()
  for fd in (value.script_fd, value.seccomp_fd, *value.mask_fds):
    if (fcntl.fcntl(fd, fcntl.F_GET_SEALS) & _SEALS != _SEALS
        or os.lseek(fd, 0, os.SEEK_CUR) != 0): _exec_invalid()


def _stdio():
  for fd in (0, 1, 2):
    mode = os.fstat(fd).st_mode
    if stat.S_ISDIR(mode) or stat.S_ISSOCK(mode): _exec_invalid()


def _require_worker_context():
  if (sys.platform != "linux" or platform.machine() != "x86_64" or os.getpid() != 1
      or len(_task_ids()) != 1 or not _FD_EXEC_SUPPORTED): _exec_invalid()


def _export_prepared(value):
  """仅供受信FD交接；第一次尝试即耗尽原对象执行/export资格。"""
  entry = _ACTIVE.get(id(value))
  if type(value) is not PreparedShellExecution or entry is None or entry["value"] is not value or entry["attempted"] or not entry["exportable"]:
    _invalid()
  entry["attempted"] = True
  _verify(value)
  return value, entry["plan_digest"]


@contextmanager
def _adopt_prepared(value, *, plan_digest):
  """仅供已完成同FD验证的内部consumer，不对RPC开放构造权限。"""
  if type(value) is not PreparedShellExecution or id(value) in _ACTIVE: _invalid()
  _ACTIVE[id(value)] = {"value": value, "attempted": False, "exportable": False, "plan_digest": plan_digest}
  try: yield value
  finally: _ACTIVE.pop(id(value), None)


def exec_prepared(value):
  """只允许受信单线程 PID1 直接 fd-exec；失败不能重试或返回成功。"""
  entry = _ACTIVE.get(id(value))
  if type(value) is not PreparedShellExecution or entry is None or entry["value"] is not value or entry["attempted"]:
    _exec_invalid()
  entry["attempted"] = True
  try:
    _require_worker_context()
    _verify(value); _stdio()
    if os.get_inheritable(value.helper_fd): _exec_invalid()
    for fd in value.pass_fds: os.set_inheritable(fd, True)
    keep = {0, 1, 2, value.helper_fd, *value.pass_fds}
    for fd in _fd_inventory():
      if type(fd) is not int or fd < 0: _exec_invalid()
      if fd in keep: continue
      try: os.close(fd)
      except OSError as error:
        if error.errno != errno.EBADF: raise
    _verify(value); _stdio()
    if os.get_inheritable(value.helper_fd) or any(not os.get_inheritable(fd) for fd in value.pass_fds): _exec_invalid()
    for fd in _fd_inventory():
      if type(fd) is not int or fd < 0: _exec_invalid()
      try: os.fstat(fd)
      except OSError as error:
        if error.errno == errno.EBADF: continue
        raise
      if fd not in keep: _exec_invalid()
    _exec_fd(value.helper_fd, value.argv, {})
  except Exception:
    raise ConfigError("pi-shell-exec-unavailable") from None
  # 成功 exec 不会返回；测试替身返回也必须按失败处理。
  _exec_invalid()
