"""只读资源身份；不证明租约模式、writer 排他、历史覆盖、域归属或维护准入。"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

from .paths import PathError
from .storage import Conflict, Tree


_KINDS = frozenset(("instance", "runtime", "native-home"))
_FIELDS = frozenset(("kind", "device", "inode", "key_id"))
_ERROR = "无法核验资源物理身份"


def _kind(value):
  return type(value) is str and value in _KINDS


def _identity(info):
  return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))


def _private_file(info):
  if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
      or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
    raise Conflict(_ERROR)
  return _identity(info)


@dataclass(frozen=True)
class ResourceKey:
  kind: str
  device: int
  inode: int

  def __post_init__(self):
    if (not _kind(self.kind) or type(self.device) is not int or self.device < 0
        or type(self.inode) is not int or self.inode <= 0):
      raise Conflict(_ERROR)

  def as_dict(self):
    physical = {"kind": self.kind, "device": self.device, "inode": self.inode}
    # 规范 JSON 只含物理字段；路径、profile 和请求上下文均不参与摘要。
    canonical = json.dumps(physical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {**physical, "key_id": hashlib.sha256(canonical).hexdigest()}

  @classmethod
  def from_dict(cls, value):
    if type(value) is not dict or value.keys() != _FIELDS:
      raise Conflict(_ERROR)
    key = cls(value["kind"], value["device"], value["inode"])
    if type(value["key_id"]) is not str or value["key_id"] != key.as_dict()["key_id"]:
      raise Conflict(_ERROR)
    return key


def _file_key(kind, path, lease_fd, lease):
  expected = _private_file(lease)
  with Tree(path.parent) as tree, tree.parent(path.name) as (parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _private_file(before) != expected:
      raise Conflict(_ERROR)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
      opened = os.fstat(fd)
      if _private_file(opened) != expected:
        raise Conflict(_ERROR)
      # 不读取正文；末次 no-follow 检查拒绝打开期间的替换、链接或权限变化。
      with tree.parent(path.name) as (current_parent, current_name):
        current = os.stat(current_name, dir_fd=current_parent, follow_symlinks=False)
        if _private_file(current) != expected or _private_file(os.fstat(lease_fd)) != expected:
          raise Conflict(_ERROR)
      return ResourceKey(kind, opened.st_dev, opened.st_ino)
    finally:
      os.close(fd)


def resource_key(kind, path, *, lease_fd):
  """安全固定现存私人目录或 0600 单链接租约文件，并核对调用方 fd。

  调用方负责租约取得、锁模式和持续持有；这里只证明当前物理身份。
  不创建资源、不取得锁、不读取租约文件或原生正文，也不关闭调用方 fd。
  """
  try:
    if not _kind(kind) or type(lease_fd) is not int or lease_fd < 0:
      raise Conflict(_ERROR)
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
      raise Conflict(_ERROR)
    lease = os.fstat(lease_fd)
    if stat.S_ISREG(lease.st_mode):
      return _file_key(kind, path, lease_fd, lease)
    if not stat.S_ISDIR(lease.st_mode):
      raise Conflict(_ERROR)
    with Tree(path) as tree:
      if tree.fd is None:
        raise Conflict(_ERROR)
      target = os.fstat(tree.fd)
      # 再次安全打开当前命名根；只核验此刻身份，不承诺阻止后续 rename。
      with Tree(path) as current_tree:
        if current_tree.fd is None:
          raise Conflict(_ERROR)
        current = os.fstat(current_tree.fd)
        if (_identity(target) != _identity(current) or _identity(target) != _identity(lease)
            or _identity(target) != _identity(os.fstat(lease_fd))):
          raise Conflict(_ERROR)
      return ResourceKey(kind, target.st_dev, target.st_ino)
  except (Conflict, PathError, OSError, TypeError, ValueError):
    raise Conflict(_ERROR) from None
