"""DSH 普通停止的显式收尾；保留清单与事实，不重发控制或授予维护许可。"""
from copy import deepcopy
import json

from . import lifecycle, run_owners, run_stop_fence, run_stop_snapshot, stop_locks, storage
from .omp_lifecycle import _same_file
from .resource_keys import resource_key
from .stop_dispatches import StopDispatches
from .stop_inbox import StopInbox
from .storage import Conflict, Tree, instance_lock


_ERROR = "停止收尾尚未确认；保留清单和运行保护，请查询原操作"
_FIELDS = {"schema_version", "kind", "binding_digest", "batch_id", "plan_id", "fence",
  "reason", "records"}


def close_name(registry, batch_id):
  run_stop_fence._name(registry)
  run_owners._run_id(batch_id)
  return registry.root.name + ".stop-close-" + batch_id + ".json"


def _unchanged(before, current):
  ignored = {"lifecycle_state", "process_observation"}
  return run_owners._encode({k: v for k, v in before.items() if k not in ignored}) == run_owners._encode(
    {k: v for k, v in current.items() if k not in ignored})


def _snapshot(registry, owner, parent, fence):
  if type(fence) is not dict or fence.get("schema_version") != 2:
    raise ValueError()
  # 复用 fence reader 的严格格式检查；历史收尾保留相同格式而不重建执行许可。
  if (set(fence) != run_stop_fence._FIELDS | {"snapshot_digest"}
      or fence["kind"] != "run-stop-fence" or fence["binding_digest"] != registry.binding_digest
      or fence["registry_physical"] != run_stop_fence._physical(owner)):
    raise ValueError()
  run_stop_snapshot._physical(fence["registry_physical"])
  for field in ("plan_id", "records_digest", "snapshot_digest"):
    run_stop_snapshot._hex64(fence[field])
  snapshot = run_stop_fence._check_snapshot_link(parent, registry, owner, fence)
  if (snapshot["schema_version"] != 2 or snapshot["plan"]["operation"] != "stop_only"
      or snapshot["plan"]["readiness"] != "ready"):
    raise ValueError()
  return snapshot


def _read_close(registry, owner, parent, batch_id):
  raw = parent.read(close_name(registry, batch_id), max_bytes=run_stop_snapshot._MAX_BYTES)
  if raw is None:
    return None
  if raw[1] != 0o600:
    raise ValueError()
  value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
    parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
  run_stop_snapshot._shape(value)
  if (type(value) is not dict or set(value) != _FIELDS or type(value["schema_version"]) is not int
      or value["schema_version"] != 1 or value["kind"] != "run-stop-close"
      or value["binding_digest"] != registry.binding_digest or value["batch_id"] != batch_id
      or value["reason"] not in ("stopped", "cancelled")
      or value["plan_id"] != value["fence"]["plan_id"] or batch_id != value["fence"]["batch_id"]):
    raise ValueError()
  snapshot = _snapshot(registry, owner, parent, value["fence"])
  if type(value["records"]) is not dict or set(value["records"]) != set(snapshot["selected_runs"]):
    raise ValueError()
  for run, record in value["records"].items():
    registry._validate_record(run + ".json", record)
    if (not _unchanged(snapshot["records"][run], record)
        or record["lifecycle_state"] not in (("idle_confirmed",) if value["reason"] == "stopped"
          else ("active", "idle_confirmed"))):
      raise ValueError()
  registry._verify_root(owner)
  return value


def read_close(registry, batch_id):
  """只读历史收尾；close 存在不证明当前 fence 已删除，更不证明共享资源空闲。"""
  try:
    with registry._locked(nonblocking=True) as owner, Tree(registry.root.parent) as parent:
      return _read_close(registry, owner, parent, batch_id)
  except Exception:
    raise Conflict(_ERROR) from None


def unposted(workspace, record):
  """调用方持 owner 锁；规范 inbox 和 journal 读取完即释放，不跟随记录路径。"""
  from .dsh_stop_control import channel_state
  channel = channel_state(workspace, record)
  return not channel["requests"] and channel["dispatch"] is None


def close_stop(workspace, *, batch_id, plan_id, reason, deadline_ns=None):
  """先持原两 SH，再以 owner CAS 保存收尾、撤销本 fence；不触碰 owner。

  cancelled 只接受仍无请求/派发的 active 项或已确证退出项；unknown/已投稿的活动项
  继续受保护。所有客户投稿必须在相同 owner 锁内复核 fence 和 close 标记。
  响应丢失后的显式重入只对账原收尾，不重发、不覆盖旧清单、不删除其它操作的 fence。
  给定原停止截止点时，只在进入首个收尾写入前等待 owner 短锁；body 仍只执行一次。
  """
  try:
    run_owners._run_id(batch_id)
    run_stop_snapshot._hex64(plan_id)
    if workspace.agent not in ("dsh", "pi", "omp") or reason not in ("stopped", "cancelled"):
      raise ValueError()
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    with lifecycle.observation_guard(workspace) as instance_fd, Tree(workspace.state_root) as parent:
      owner_guard = (registry._locked(nonblocking=True) if deadline_ns is None
        else stop_locks.locked(registry, deadline_ns))
      with instance_lock(parent, shared=True, create=False) as state_fd, owner_guard as owner:
        prior = _read_close(registry, owner, parent, batch_id)
        fence = run_stop_fence._read_locked(registry, owner, parent)
        if prior is not None:
          if prior["plan_id"] != plan_id or prior["reason"] != reason:
            raise ValueError()
          if fence is None or fence["batch_id"] != batch_id:
            return deepcopy(prior)
          if run_owners._encode(prior["fence"]) != run_owners._encode(fence):
            raise ValueError()
        if fence is None or fence["batch_id"] != batch_id or fence["plan_id"] != plan_id:
          raise ValueError()
        snapshot = _snapshot(registry, owner, parent, fence)
        expected_instance = next(item["key"] for item in snapshot["plan"]["resources"]
          if item["key"]["kind"] == "instance")
        instance_path = workspace.instance / ".agentcfg-omp.lock" if workspace.agent == "omp" else workspace.instance
        if resource_key("instance", instance_path, lease_fd=instance_fd).as_dict() != expected_instance:
          raise ValueError()
        _same_file(parent, "instance.lock", state_fd)
        records, _ = registry._records(owner)
        selected = {}
        for run in snapshot["selected_runs"]:
          record = records.get(run)
          if record is None or not _unchanged(snapshot["records"][run], record):
            raise ValueError()
          state = record["lifecycle_state"]
          if state != "idle_confirmed" and (reason != "cancelled" or state != "active" or not unposted(workspace, record)):
            raise ValueError()
          selected[run] = record
        fence_raw = parent.read(run_stop_fence._name(registry), max_bytes=16384)
        if fence_raw is None or fence_raw[0] != run_owners._encode(fence):
          raise ValueError()
        value = prior or {"schema_version": 1, "kind": "run-stop-close", "binding_digest": registry.binding_digest,
          "batch_id": batch_id, "plan_id": plan_id, "fence": deepcopy(fence), "reason": reason,
          "records": deepcopy(selected)}
        if prior is None:
          parent.write_new(close_name(registry, batch_id), run_stop_snapshot._encoded(value))
          storage.sync_directory_ancestors(parent.root)
        if _read_close(registry, owner, parent, batch_id) != value:
          raise ValueError()
        fresh, _ = registry._records(owner)
        if run_owners._encode(fresh) != run_owners._encode(records):
          raise ValueError()
        _same_file(parent, "instance.lock", state_fd)
        registry._verify_root(owner)
        # 原 close 已持久化；删除或其 fsync 失败不回滚记录，不重试本次调用。
        parent.replace(run_stop_fence._name(registry), None, expected=fence_raw[2])
        run_stop_fence._assert_missing(parent, run_stop_fence._name(registry))
        registry._verify_root(owner)
        return deepcopy(value)
  except Exception:
    raise Conflict(_ERROR) from None
