"""HOME 目标类型与祖先检查；此层不读取旧文件正文。"""

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import secrets
import stat

from .errors import TermcfgError


@dataclass(frozen=True)
class TargetIdentity:
  kind: str
  uid: int | None = None
  dev: int | None = None
  ino: int | None = None
  mode: int | None = None
  mtime_ns: int | None = None
  size: int | None = None
  digest: str | None = None
  link: str | None = None

  def as_dict(self) -> dict:
    return {key: value for key, value in vars(self).items() if value is not None}


def inspect_target(home: Path, relative: Path) -> TargetIdentity:
  if not relative.parts or relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
    raise TermcfgError(2, "invalid_target_path")
  if home.is_symlink() or not home.is_dir() or home.stat().st_uid != os.getuid():
    raise TermcfgError(4, "unsafe_home")
  parent = home
  for part in relative.parts[:-1]:
    parent = parent / part
    try:
      info = parent.lstat()
    except FileNotFoundError:
      return TargetIdentity("absent")
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
      raise TermcfgError(4, "unsafe_target_parent")
  path = home / relative
  try:
    info = path.lstat()
  except FileNotFoundError:
    return TargetIdentity("absent")
  if info.st_uid != os.getuid():
    raise TermcfgError(4, "target_owner_conflict")
  common = dict(uid=info.st_uid, dev=info.st_dev, ino=info.st_ino,
                mode=stat.S_IMODE(info.st_mode), mtime_ns=info.st_mtime_ns,
                size=info.st_size)
  if stat.S_ISLNK(info.st_mode):
    return TargetIdentity("symlink", link=os.readlink(path), **common)
  if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
    return TargetIdentity("file", **common)
  raise TermcfgError(4, "unsupported_target_type")


def read_regular(home: Path, relative: Path, identity: TargetIdentity) -> bytes:
  if identity.kind != "file":
    raise TermcfgError(4, "target_changed")
  path = home / relative
  flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
  fd = os.open(path, flags)
  try:
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) != (identity.dev, identity.ino, identity.mtime_ns, identity.size) or info.st_nlink != 1:
      raise TermcfgError(4, "target_changed")
    data = os.read(fd, info.st_size + 1)
    checked = os.fstat(fd)
    if len(data) != info.st_size or (checked.st_mtime_ns, checked.st_size) != (info.st_mtime_ns, info.st_size):
      raise TermcfgError(4, "target_changed")
    return data
  finally:
    os.close(fd)


@contextmanager
def target_parent_fd(home: Path, relative: Path, *, create: bool):
  """固定祖先 dirfd，避免检查与写入之间的链接替换。"""
  if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
    raise TermcfgError(2, "invalid_target_path")
  fds = []
  try:
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    fds.append(fd)
    if os.fstat(fd).st_uid != os.getuid():
      raise TermcfgError(4, "unsafe_home")
    for part in relative.parts[:-1]:
      try:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
      except FileNotFoundError:
        if not create:
          raise
        os.mkdir(part, 0o700, dir_fd=fd)
        os.fsync(fd)
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
      info = os.fstat(child)
      if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise TermcfgError(4, "unsafe_target_parent")
      fds.append(child)
      fd = child
    yield fd, relative.parts[-1]
  finally:
    for fd in reversed(fds):
      os.close(fd)


def _check_expected(directory_fd: int, name: str, expected: dict | None) -> None:
  if expected is None:
    return
  try:
    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
  except FileNotFoundError:
    if expected["kind"] == "absent":
      return
    raise TermcfgError(4, "target_changed_during_write")
  if expected["kind"] == "absent":
    raise TermcfgError(4, "target_changed_during_write")
  kind = "symlink" if stat.S_ISLNK(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
  observed = {"kind": kind, "uid": info.st_uid, "dev": info.st_dev,
              "ino": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
              "mtime_ns": info.st_mtime_ns, "size": info.st_size}
  if kind == "symlink":
    observed["link"] = os.readlink(name, dir_fd=directory_fd)
  if any(observed.get(key) != value for key, value in expected.items() if key != "digest"):
    raise TermcfgError(4, "target_changed_during_write")


def atomic_target_bytes(home: Path, relative: Path, data: bytes, mode: int, *, before_replace=None,
                        expected: dict | None = None) -> None:
  with target_parent_fd(home, relative, create=True) as (directory_fd, name):
    temporary = f".termcfg-{secrets.token_hex(12)}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                 mode, dir_fd=directory_fd)
    try:
      os.fchmod(fd, mode)
      with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
      if before_replace is not None:
        info = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
        before_replace(TargetIdentity("file", uid=info.st_uid, dev=info.st_dev,
                                      ino=info.st_ino, mode=stat.S_IMODE(info.st_mode),
                                      mtime_ns=info.st_mtime_ns, size=info.st_size,
                                      digest=hashlib.sha256(data).hexdigest()).as_dict())
      _check_expected(directory_fd, name, expected)
      os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
      os.fsync(directory_fd)
    finally:
      try:
        os.unlink(temporary, dir_fd=directory_fd)
      except FileNotFoundError:
        pass


def atomic_target_link(home: Path, relative: Path, link: str, *, before_replace=None,
                       expected: dict | None = None) -> None:
  with target_parent_fd(home, relative, create=True) as (directory_fd, name):
    temporary = f".termcfg-{secrets.token_hex(12)}"
    try:
      os.symlink(link, temporary, dir_fd=directory_fd)
      if before_replace is not None:
        info = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
        before_replace(TargetIdentity("symlink", uid=info.st_uid, dev=info.st_dev,
                                      ino=info.st_ino, mode=stat.S_IMODE(info.st_mode),
                                      mtime_ns=info.st_mtime_ns, size=info.st_size,
                                      link=link).as_dict())
      _check_expected(directory_fd, name, expected)
      os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
      os.fsync(directory_fd)
    finally:
      try:
        os.unlink(temporary, dir_fd=directory_fd)
      except FileNotFoundError:
        pass


def remove_target(home: Path, relative: Path, *, before_remove=None,
                  expected: dict | None = None) -> None:
  with target_parent_fd(home, relative, create=False) as (directory_fd, name):
    if before_remove is not None:
      before_remove({"kind": "absent"})
    _check_expected(directory_fd, name, expected)
    os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)
