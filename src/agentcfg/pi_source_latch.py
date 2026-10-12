"""固定实例来源 latch；端点核对不构成持续 SourceHold 或交接权限。"""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat

from .paths import PathError
from .storage import Conflict, Tree


def _identity(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
          info.st_gid, info.st_nlink, info.st_size)


def _directory_identity(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _anchor(info):
  if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
      or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
      or info.st_size != 0):
    raise Conflict("来源 latch 文件无效")
  return _identity(info)


def _check(tree, source, original, root):
  with tree.parent("source.lock") as (parent, name):
    if _directory_identity(os.fstat(tree.fd)) != root:
      raise Conflict("来源 latch 根身份发生变化")
    held = _anchor(os.fstat(source))
    named = _anchor(os.stat(name, dir_fd=parent, follow_symlinks=False))
    if held != original or named != original:
      raise Conflict("来源 latch 文件身份发生变化")


class _SourceResources:
  """仅自有共用原语持有；不接FD/权限DTO，不给public context泄露资源。"""

  __slots__ = ("tree", "source", "original", "root", "source_close", "tree_close")

  def __init__(self):
    self.tree = None
    self.source = None
    self.original = None
    self.root = None
    # 旧context保留动态global；独立reader可保存本次原方法/receiver。
    self.source_close = None
    self.tree_close = None


def _cleanup(resources):
  # 保持原嵌套finally：Tree关闭失败仍可覆盖source/body/endpoint失败。
  try:
    if resources.source is not None:
      fd, resources.source = resources.source, None
      try:
        (resources.source_close or os.close)(fd)
      except OSError:
        raise Conflict("来源 latch 关闭失败") from None
  finally:
    if resources.tree is not None:
      tree, resources.tree = resources.tree, None
      try:
        if resources.tree_close is None:
          tree.close()
        else:
          resources.tree_close()
      except (OSError, PathError):
        raise Conflict("来源 latch 根关闭失败") from None


def _acquire(workspace, *, shared=False, create=False):
  if type(shared) is not bool or type(create) is not bool:
    raise Conflict("来源 latch 参数无效")
  instance = workspace.instance
  if (not isinstance(instance, Path) or not instance.is_absolute()
      or ".." in instance.parts or instance == Path("/")):
    raise Conflict("来源 latch 实例无效")
  resources = _SourceResources()
  try:
    try:
      resources.tree = Tree(instance, create=False, private=True)
      with resources.tree.parent("source.lock") as (parent, name):
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
          before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
          if not create:
            raise
          # 首次创建只发布空 anchor；竞态同名存在则重新严格打开。
          try:
            resources.source = os.open(name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
          except FileExistsError:
            pass
          before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        resources.original = _anchor(before)
        if resources.source is None:
          resources.source = os.open(name, flags, dir_fd=parent)
        if _anchor(os.fstat(resources.source)) != resources.original:
          raise Conflict("来源 latch 文件身份发生变化")
      fcntl.flock(resources.source, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
      resources.root = _directory_identity(os.fstat(resources.tree.fd))
      _check(resources.tree, resources.source, resources.original, resources.root)
    except (OSError, PathError):
      raise Conflict("无法取得来源 latch") from None
    return resources
  except BaseException:
    _cleanup(resources)
    raise


@contextmanager
def source_latch(workspace, *, shared=False, create=False):
  """仅当前作用域持有非阻塞锁；不泄露 fd，不解锁后重取。"""
  resources = _acquire(workspace, shared=shared, create=create)
  try:
    try:
      yield None
    finally:
      try:
        # 旧context有意仍观察当前global；保持after-body故障控制。
        _check(resources.tree, resources.source, resources.original, resources.root)
      except (OSError, PathError, Conflict):
        raise Conflict("来源 latch 端点核对失败") from None
  finally:
    _cleanup(resources)
