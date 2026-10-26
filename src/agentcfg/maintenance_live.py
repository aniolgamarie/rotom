"""停止接受前的只读物理/owner核验；不授予控制权，不执行或持久化动作。"""
import os

from . import maintenance, omp_observation, resource_owners as owners, resource_scopes, run_owners
from .omp_lifecycle import _same_file
from .storage import Conflict, Tree


_ERROR = "停止接受前的物理租约或运行归属不能确认；保留现有保护"
_KEYS = {"workspace", "instance_fd", "state_fd", "native_home_fd", "runtime_fds"}


def _fd(fd):
  if type(fd) is not int or fd < 0:
    raise ValueError()
  os.fstat(fd)


def hold_stop_owners(domain, state, *, acceptance, leases, stack):
  """调用方已持物理 SH 和当前协调锁；owner NB 锁交给外层 stack 持续到提交后。

  不从快照追踪路径，不取物理锁，不关闭借入 fd；数据和 fd 核验不证明进程存活。
  """
  from .maintenance_store import _snapshot_matches
  try:
    value = maintenance.decode_stop_acceptance(maintenance.encode_stop_acceptance(acceptance))
    plan = value["batch"]["plan"]
    if (type(leases) is not dict or set(leases) != set(plan["selected_runs"])
        or value["expected_revision"] != state["revision"]):
      raise ValueError()
    _snapshot_matches(domain, state, value)
    domain._unfenced(state, {resource["resource_id"] for resource in plan["resources"]})
    groups, selected = {}, {}
    for run in sorted(leases):
      item = leases[run]
      if type(item) is not dict or set(item) != _KEYS or type(item["runtime_fds"]) is not dict:
        raise ValueError()
      for fd in (item["instance_fd"], item["state_fd"], item["native_home_fd"], *item["runtime_fds"].values()):
        _fd(fd)
      workspace = item["workspace"]
      entry = state["reservations"][run]
      scope = resource_scopes._verify(state, workspace, instance_fd=item["instance_fd"],
        native_home_fd=item["native_home_fd"])
      with Tree(workspace.state_root) as tree:
        _same_file(tree, "instance.lock", item["state_fd"])
      runtimes = set(entry["resources"]) - scope
      if (len(runtimes) != 1 or set(item["runtime_fds"]) != runtimes
          or any(state["resources"][rid]["key"]["kind"] != "runtime"
            or state["resources"][rid]["cache"] != str(workspace.cache) for rid in runtimes)):
        raise ValueError()
      registry = owners._registry(workspace, entry)
      key = (str(registry.root), registry.binding_digest)
      if key in groups and groups[key][3] != scope:
        raise ValueError()
      groups.setdefault(key, (registry, workspace, item, scope))
      selected[run] = (key, workspace, item)
    for key in sorted(groups):
      registry, workspace, item, scope = groups[key]
      # 所有 owner 锁均 NB；不得在协调短锁内等待，亦不得在此释放调用方 stack。
      tree = stack.enter_context(registry._locked(nonblocking=True))
      records, _ = registry._records(tree)
      related = {run: entry for run, entry in state["reservations"].items()
        if scope.intersection(entry["resources"])}
      for run, record in records.items():
        if record.get("coordination_domain") is None or run not in related:
          raise ValueError()
        omp_observation._record_link(state, related[run], workspace, registry, tree,
          record, scope, item["instance_fd"], item["native_home_fd"])
      expected = {"dispatched": "active", "released": "idle_confirmed"}
      for run, entry in related.items():
        if entry["phase"] == "cancelled" and run not in records:
          continue
        if run not in records or expected.get(entry["phase"]) != run_owners.record_state(records[run]):
          raise ValueError()
      for run, (group, chosen_workspace, chosen) in selected.items():
        if group != key:
          continue
        record = records.get(run)
        if run_owners._encode(record) != run_owners._encode(value["records"][run]):
          raise ValueError()
        owners._check_link(domain, state, state["reservations"][run], chosen_workspace,
          registry, tree, record, instance_fd=chosen["instance_fd"], native_home_fd=chosen["native_home_fd"],
          runtime_fds=chosen["runtime_fds"])
        # owner 锁内再次核对命名状态锁；首次物理核验到元数据锁之间可发生替换。
        with Tree(chosen_workspace.state_root) as state_tree:
          _same_file(state_tree, "instance.lock", chosen["state_fd"])
  except Exception:
    raise Conflict(_ERROR) from None
