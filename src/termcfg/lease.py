"""机器互斥锁及跨机器仓库读写锁。"""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import stat

from .config import MACHINE_ID, xdg_path
from .errors import TermcfgError


def _private_dir(path: Path) -> None:
  parent = path.parent
  if parent != path and parent.name in {"termcfg", "leases", "machines", "repos"}:
    _private_dir(parent)
  if path.exists() or path.is_symlink():
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise TermcfgError(4, "unsafe_lease_directory")
  else:
    try:
      path.mkdir(mode=0o700)
    except FileExistsError:
      info = path.lstat()
      if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise TermcfgError(4, "unsafe_lease_directory")


@contextmanager
def _lease(path: Path, *, exclusive: bool):
  _private_dir(path.parent)
  flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
  fd = -1
  try:
    try:
      fd = os.open(path, flags, 0o600)
      info = os.fstat(fd)
      if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise TermcfgError(4, "unsafe_lease_file")
      try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
      except BlockingIOError as exc:
        raise TermcfgError(4, "operation_busy") from exc
    except OSError as exc:
      raise TermcfgError(4, "lease_unavailable") from exc
    yield
  finally:
    if fd >= 0:
      os.close(fd)


def operation_lease(machine_id: str):
  if not MACHINE_ID.fullmatch(machine_id):
    raise TermcfgError(2, "invalid_machine_id")
  path = xdg_path("XDG_STATE_HOME") / "termcfg" / "leases" / "machines" / f"{machine_id}.lock"
  return _lease(path, exclusive=True)


def repository_lease(repo_root: Path, *, exclusive: bool):
  digest = hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()
  path = xdg_path("XDG_STATE_HOME") / "termcfg" / "leases" / "repos" / f"repo-{digest[:32]}.lock"
  return _lease(path, exclusive=exclusive)
