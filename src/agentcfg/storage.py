"""私人文件边界：固定目录句柄、no-follow、原子替换；不授予文件所有权。"""

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import stat
import uuid

from .paths import (PathError, _DIRECTORY_FLAGS, _check_ancestor, _check_private,
                    _create_directory, _open_directory, relative_path)


class StateError(Exception):
  exit_code = 6

  def __init__(self, message="私人文件操作失败；请检查路径、权限与磁盘空间"):
    super().__init__(message)


class Conflict(StateError):
  exit_code = 4


def identity(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
          info.st_mtime_ns, info.st_ctime_ns)


def ensure_private(path: Path):
  """创建缺失容器，已有的系统/用户祖先只检查，最后一层严格 0700。"""
  if not path.is_absolute() or ".." in path.parts or path == Path("/"):
    raise Conflict("私人目录路径无效")
  fd = os.open("/", _DIRECTORY_FLAGS)
  try:
    _check_ancestor(fd)
    for name in path.parts[1:]:
      try:
        child = _open_directory(fd, name)
      except FileNotFoundError:
        info = os.fstat(fd)
        if (info.st_uid != os.geteuid() or info.st_mode & 0o022) and not info.st_mode & stat.S_ISVTX:
          raise Conflict("不能在不安全目录下创建私人容器")
        child = _create_directory(fd, name)
      os.close(fd)
      fd = child
      _check_ancestor(fd)
    _check_private(fd)
  finally:
    os.close(fd)


def _write_new_at(fd, target, data):
  temporary = ".agentcfg-" + uuid.uuid4().hex
  output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
  try:
    with os.fdopen(output, "wb") as stream:
      os.fchmod(stream.fileno(), 0o600)
      stream.write(data); stream.flush(); os.fsync(stream.fileno())
    try:
      os.link(temporary, target, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    except FileExistsError:
      raise Conflict("新文件目标已存在，拒绝覆盖") from None
  finally:
    os.unlink(temporary, dir_fd=fd)
    os.fsync(fd)


def create_new_private_file(path, data):
  """在明确指定的位置创建 0600 新文件；允许系统 sticky 临时目录。"""
  from .paths import _absolute_directory
  path = Path(path).absolute()
  relative_path(path.name)
  with _absolute_directory(path.parent) as fd:
    _write_new_at(fd, path.name, data)


class Tree:
  """一次操作固定根句柄；允许原生非私有模式文件读取，但从不跟随链接。"""

  def __init__(self, root: Path, *, create=False, private=True):
    from .paths import _absolute_directory, trusted_source_directory
    if create:
      ensure_private(root)
    self.root = root
    self.private = private
    self.fd = None
    if root.exists() or root.is_symlink():
      with (_absolute_directory(root) if private else trusted_source_directory(root)) as fd:
        if private:
          _check_private(fd)
        self.fd = os.dup(fd)

  def close(self):
    if self.fd is not None:
      fd, self.fd = self.fd, None
      os.close(fd)

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    self.close()

  @contextmanager
  def parent(self, value, *, create=False):
    path = relative_path(value)
    if self.fd is None:
      raise FileNotFoundError()
    from .paths import _absolute_directory, trusted_source_directory
    opener = _absolute_directory if self.private else trusted_source_directory
    with opener(self.root) as current_root:
      original, current = os.fstat(self.fd), os.fstat(current_root)
      if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
        raise Conflict("操作期间根目录身份发生变化")
    fd = os.dup(self.fd)
    try:
      for part in path.parts[:-1]:
        try:
          child = _open_directory(fd, part)
        except FileNotFoundError:
          if not create:
            raise
          child = _create_directory(fd, part)
        os.close(fd)
        fd = child
        _check_ancestor(fd)
      yield fd, path.name
    finally:
      os.close(fd)

  @contextmanager
  def open_read(self, path, *, max_bytes=None):
    """固定单文件身份的流读取；大资产不必一次装入内存，缺失仍由调用方处理。"""
    try:
      with self.parent(path) as (fd, name):
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid():
          raise Conflict("目标必须为普通单链接文件")
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(source, "rb") as stream:
          opened = os.fstat(stream.fileno())
          if identity(opened) != identity(before):
            raise Conflict("目标在读取前发生变化")
          if max_bytes is not None and opened.st_size > max_bytes:
            raise Conflict("文件超过本次操作允许的大小")
          yield stream, opened
          if identity(opened) != identity(os.fstat(stream.fileno())):
            raise Conflict("目标在读取时发生变化")
        try: current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError: raise Conflict("目标路径在读取时发生变化") from None
        if identity(opened) != identity(current):
          raise Conflict("目标路径在读取时发生变化")
    except FileNotFoundError:
      raise
    except (OSError, PathError):
      raise Conflict("无法安全读取目标；请检查路径与权限") from None

  def read(self, path, *, max_bytes=None):
    """返回 bytes/mode/身份；缺失返回 None，不将原生内容放进异常。"""
    try:
      with self.open_read(path, max_bytes=max_bytes) as (stream, opened):
        data = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
        if max_bytes is not None and len(data) > max_bytes:
          raise Conflict("文件超过本次操作允许的大小")
      return data, stat.S_IMODE(opened.st_mode), identity(opened)
    except FileNotFoundError:
      return None

  def replace(self, path, data, mode=0o600, *, expected):
    """expected 是刚读的身份；调用者负责所有权、三方合并和 journal。"""
    current = self.read(path)
    if (current[2] if current else None) != expected:
      raise Conflict("目标在写入前发生变化，请重新计划")
    with self.parent(path, create=data is not None) as (fd, name):
      if data is None:
        if current is not None:
          if identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != expected:
            raise Conflict("删除前目标发生变化")
          os.unlink(name, dir_fd=fd)
          os.fsync(fd)
        return
      temp = ".agentcfg-" + uuid.uuid4().hex
      created = False
      try:
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                      mode, dir_fd=fd)
        created = True
        with os.fdopen(out, "wb") as stream:
          os.fchmod(stream.fileno(), mode)
          stream.write(data)
          stream.flush()
          os.fsync(stream.fileno())
        # 写完暂存文件后再次检查目标，尽量缩短不可避免的外部进程竞争窗口。
        latest = self.read(path)
        if (latest[2] if latest else None) != expected:
          raise Conflict("目标在原子替换前发生变化")
        with self.parent(path) as (fresh_parent, _):
          old_parent, new_parent = os.fstat(fd), os.fstat(fresh_parent)
          if (old_parent.st_dev, old_parent.st_ino) != (new_parent.st_dev, new_parent.st_ino):
            raise Conflict("目标父目录在原子替换前发生变化")
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        created = False
        os.fsync(fd)
      finally:
        if created:
          os.unlink(temp, dir_fd=fd)

  def write_state(self, name, data):
    before = self.read(name)
    self.replace(name, data, expected=before[2] if before else None)

  def write_new(self, name, data):
    """原子发布新的私人文件；并发同名创建也绝不覆盖。"""
    with self.parent(name, create=True) as (fd, target):
      _write_new_at(fd, target, data)

  def write_immutable(self, name, data):
    """证据正文不能被重放或修复路径覆盖；相同正文幂等复用。"""
    before = self.read(name)
    if before is not None:
      if before[0] != data or before[1] != 0o600:
        raise Conflict("不可变证据已改变；不能覆盖旧记录")
      return
    self.replace(name, data, expected=None)


@contextmanager
def instance_lock(state: Tree):
  """锁持有期间禁止 apply/sync/rollback/run 并发；不替换或删除锁文件。"""
  with state.parent("instance.lock") as (parent, name):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
  try:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
      raise Conflict("实例锁文件不安全")
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
      if error.errno in (errno.EAGAIN, errno.EACCES):
        raise Conflict("实例正在运行或有其他操作；退出后重试") from None
      raise
    yield fd
  finally:
    os.close(fd)
