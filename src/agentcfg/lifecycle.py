"""物理实例准入；共享运行与独占维护使用同一个目录 inode。"""

from contextlib import contextmanager
import sys

from .deployment import json_bytes
from .storage import Conflict, StateError, Tree, advisory_lock


@contextmanager
def guard(workspace, *, shared=False, create=True):
  if shared and create:
    raise ValueError("共享准入不能初始化实例")
  with Tree(workspace.instance, create=create) as tree:
    if tree.fd is None:
      raise Conflict("实例尚未准备；请先 apply")
    with advisory_lock(tree.fd, shared=shared, unlock=False,
        busy_message="实例目录仍被运行或其他操作保护"):
      binding = {"schema_version": 1, "state_root": str(workspace.state_root),
        "binding": getattr(workspace, "binding", {"profile": workspace.profile})}
      if create:
        tree.write_immutable(".agentcfg-instance.json", json_bytes(binding))
      else:
        raw = tree.read(".agentcfg-instance.json")
        if raw is None or raw[1] != 0o600 or raw[0] != json_bytes(binding):
          raise Conflict("实例归属缺失或不匹配；请检查配置并 apply")
      yield tree.fd


@contextmanager
def registered_run(workspace):
  """调用方持物理/状态共享租约；退出不构成全部后代释放的证据。"""
  from .run_owners import Registry, current_process_identity
  from .descendants import DescendantScope
  registry = Registry(workspace.state_root / "run-owners", workspace.binding)
  manager = current_process_identity()
  with DescendantScope(manager) as descendants:
    run_id = registry.register(manager)
    try:
      yield run_id
    finally:
      try:
        observation = descendants.observe(run_id)
        if observation is None:
          registry.mark_unknown(run_id, manager)
        else:
          registry.finish_current(run_id, manager, observation)
      except (StateError, OSError):
        # 原active记录仍阻止维护；记账失败不能替换已启动宿主的实际退出码。
        try:
          print("运行归属状态未能更新；活动保护保持生效，请检查运行归属记录。", file=sys.stderr)
        except (OSError, ValueError):
          pass
