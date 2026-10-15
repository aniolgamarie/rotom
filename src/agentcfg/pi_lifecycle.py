"""Pi 稳定实例准入：锁绑定实例目录，不能通过换 state_root 绕过运行保护。"""

from contextlib import contextmanager
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
def guard(workspace, *, allow_active=False, create=True, shared=False):
  from .lifecycle import guard as physical_guard
  with physical_guard(workspace, shared=shared, create=create) as fd:
    if not allow_active:
      assert_inactive(workspace.state_root)
    yield fd
