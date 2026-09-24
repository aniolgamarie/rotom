"""Pi 稳定实例准入：锁绑定实例目录，不能通过换 state_root 绕过运行保护。"""

from contextlib import contextmanager
import fcntl
from pathlib import Path

from .deployment import json_bytes
from .storage import Conflict, Tree


def assert_inactive(state_root):
  from .activity import ExecutionStore, OWNER_KEYS, protected
  from .pi_catalog import validate
  import json
  directory = Path(state_root) / "activity/leases"
  if not directory.exists() and not directory.is_symlink():
    return
  with Tree(directory) as tree:
    import os
    for name in os.listdir(tree.fd):
      if not name.endswith(".json"):
        raise Conflict("实例存在未知执行记录，不能修改")
      raw = tree.read(name)
      try:
        lease = json.loads(raw[0])
        validate("execution-lease", lease)
        owner = {key: lease[key] for key in OWNER_KEYS}
        checker = ExecutionStore(state_root, owner, None)
        checker._validate(lease)
        if raw[1] != 0o600 or name != lease["lease_id"] + ".json":
          raise ValueError()
      except Exception:
        raise Conflict("实例执行记录损坏，保护保持生效") from None
      if protected(lease):
        raise Conflict("实例仍有活动或未知执行；不能修改其配置和运行包")


@contextmanager
def guard(workspace, *, allow_active=False, create=True):
  with Tree(workspace.instance, create=create) as tree:
    if tree.fd is None:
      raise Conflict("Pi实例不存在，不能建立恢复控制")
    try:
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
      raise Conflict("Pi实例目录仍被运行或其他操作保护") from None
    try:
      binding = {"schema_version": 1, "state_root": str(workspace.state_root),
        "binding": getattr(workspace, "binding", {"profile": workspace.profile})}
      if create:
        tree.write_immutable(".agentcfg-instance.json", json_bytes(binding))
      else:
        raw = tree.read(".agentcfg-instance.json")
        if raw is None or raw[1] != 0o600 or raw[0] != json_bytes(binding):
          raise Conflict("保存的实例归属与恢复目标不匹配")
      if not allow_active:
        assert_inactive(workspace.state_root)
      yield tree.fd
    finally:
      fcntl.flock(tree.fd, fcntl.LOCK_UN)
