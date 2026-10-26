"""OMP 原始 child/停止端点登记；先持久化待更新事实，再同步 owner 双向摘要。"""
from contextlib import ExitStack
from copy import deepcopy

from . import resource_owners as owners, run_owners
from .spawned_host import SpawnedHost
from .storage import Conflict


_ERROR = "OMP 当前宿主观察未能完整登记；保留原运行与协调保护，不重试"


def _observed(host, record, run_id, service):
  if type(host) is not SpawnedHost:
    raise ValueError()
  observed = host.snapshot()
  manager = record["manager_identity"]
  if (run_owners.current_process_identity() != manager
      or observed["manager_identity"] != manager or observed["identity"]["pid"] == manager["pid"]
      or observed["source"] != "linux-spawn-pidfd"
      or observed["relationship"] != "reported-by-current-run"):
    raise ValueError()
  changed = deepcopy(record)
  if service is None:
    if record["host_identity"] is not None or record["protocol"]["control"] is not None:
      raise ValueError()
    changed["host_identity"] = observed
  else:
    from .stop_service import StopService
    if (type(service) is not StopService or service.belongs_to(run_id, host) is not True
        or record["host_identity"] != observed or record["protocol"]["control"] is not None):
      raise ValueError()
    changed["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": service.describe()}
  run_owners._set_state(changed, "active")
  return changed


def _bind(domain, run_id, *, workspace, instance_fd, native_home_fd, runtime_fds, host, service=None):
  """借用原 SH；Domain → owner NB → inbox。任何半写入都保留 pending，不自行恢复。"""
  try:
    with ExitStack() as locks, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if entry["phase"] != "dispatched" or "release_receipt" in entry:
        raise ValueError()
      registry = owners._registry(workspace, entry)
      tree = locks.enter_context(registry._locked(nonblocking=True))
      records, _ = registry._records(tree)
      record = records.get(run_id)
      owners._check_link(domain, state, entry, workspace, registry, tree, record,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds)
      changed = _observed(host, record, run_id, service)
      registry._validate_record(run_id + ".json", changed)
      before_digest = owners._digest(record)
      # 复用既有 pending 格式；旧 checkout 能继续解码同一域并完成自己的退出。
      # pending 指向目标摘要；旧 owner 尚未匹配时仅本 run 保持不可准入。
      entry["owner_link"]["record_digest"] = owners._digest(changed)
      entry["phase"] = "owner_pending"
      pending = deepcopy(entry)
    # pending 的 fsync 必须成功返回才写 owner；不把可读文件当成前次成功响应。
    with ExitStack() as locks, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if entry != pending:
        raise ValueError()
      registry = owners._registry(workspace, entry)
      tree = locks.enter_context(registry._locked(nonblocking=True))
      records, originals = registry._records(tree)
      current = records.get(run_id)
      owners._check_link(domain, state, entry, workspace, registry, tree, current,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds,
        expected_digest=before_digest)
      fresh = _observed(host, current, run_id, service)
      # 新读取只重核原句柄和端点；保留首次冻结的观察时间，不生成另一条更新。
      fresh["process_observation"]["observed_at_ns"] = changed["process_observation"]["observed_at_ns"]
      if fresh != changed or owners._digest(changed) != pending["owner_link"]["record_digest"]:
        raise ValueError()
      tree.replace(run_id + ".json", run_owners._encode(changed), expected=originals[run_id][2])
      records, _ = registry._records(tree)
      owners._check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds,
        expected_digest=owners._digest(changed))
      entry["phase"] = "dispatched"
    return run_id
  except Exception:
    raise Conflict(_ERROR) from None


def bind_current_host(domain, run_id, *, host, **lease):
  return _bind(domain, run_id, host=host, **lease)


def bind_current_control(domain, run_id, *, host, service, **lease):
  return _bind(domain, run_id, host=host, service=service, **lease)
