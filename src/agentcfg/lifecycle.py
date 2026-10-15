"""物理实例准入；共享运行与独占维护使用同一个目录 inode。"""

from contextlib import contextmanager
import fcntl

from .deployment import json_bytes
from .storage import Conflict, Tree


@contextmanager
def guard(workspace, *, shared=False, create=True):
  if shared and create:
    raise ValueError("共享准入不能初始化实例")
  with Tree(workspace.instance, create=create) as tree:
    if tree.fd is None:
      raise Conflict("实例尚未准备；请先 apply")
    try:
      fcntl.flock(tree.fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    except OSError:
      raise Conflict("实例目录仍被运行或其他操作保护") from None
    try:
      binding = {"schema_version": 1, "state_root": str(workspace.state_root),
        "binding": getattr(workspace, "binding", {"profile": workspace.profile})}
      if create:
        tree.write_immutable(".agentcfg-instance.json", json_bytes(binding))
      else:
        raw = tree.read(".agentcfg-instance.json")
        if raw is None or raw[1] != 0o600 or raw[0] != json_bytes(binding):
          raise Conflict("实例归属缺失或不匹配；请检查配置并 apply")
      yield tree.fd
    finally:
      fcntl.flock(tree.fd, fcntl.LOCK_UN)
