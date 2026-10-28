"""固定 Linux DSH 组合的停止服务；旧运行不补绑控制。

通道描述和历史记录不是批准或活句柄。工厂仅借用原两 SH 与原 SpawnedHost；
每次请求仍须通过已审阅 stop_only 快照、当前部署和原服务期限核验。
"""
from copy import deepcopy
import os
import sys
import time

from . import dsh_stop_scope, run_owners, stop_locks
from .spawned_host import SpawnedHost
from .stop_dispatches import StopDispatches
from .stop_inbox import StopInbox
from .stop_service import StopService
from .storage import Conflict


_ERROR = "DSH 停止通道或当前运行现场不能确认；保留事实且不重试"
_RUNTIMES = frozenset({
  "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d",
  "a4e31cef17c6a08e99dac3c42a0ba2985458720dd924010b01ba75d04b438353",
})


def _same(left, right):
  return run_owners._encode(left) == run_owners._encode(right)


def _registry(workspace):
  return run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)


def _record(workspace, record):
  if type(record) is not dict:
    raise ValueError()
  _registry(workspace)._validate_record(record["run_id"] + ".json", record)
  if (record["schema_version"] != 2 or record["agent"] not in ("dsh", "pi", "omp")
      or record["backend"] != "managed"
      or (record["coordination_domain"] is not None) != (record["agent"] == "omp")):
    raise ValueError()


def _fds(instance_fd, state_fd):
  for fd in (instance_fd, state_fd):
    if type(fd) is not int or fd < 0:
      raise ValueError()
    os.fstat(fd)


def _stores(workspace, run_id, *, wait_for_lock=False):
  return (StopInbox(workspace.state_root / "stop-inboxes" / run_id, workspace.binding),
    StopDispatches(workspace.state_root / "stop-dispatches", workspace.binding, wait_for_lock=wait_for_lock))


def channel_state(workspace, record, *, deadline_ns=None):
  """调用方持 owner 锁；只读历史通道，不要求当前 manager，不产生权限。"""
  try:
    _record(workspace, record)
    descriptor = record["protocol"]["control"]
    if record["agent"] == "dsh" and (descriptor is None or descriptor["kind"] != "linux-pidfd-stop-v1"):
      raise ValueError()
    inbox, journal = _stores(workspace, record["run_id"])
    guard = (inbox._registry._locked(nonblocking=True) if deadline_ns is None
      else stop_locks.locked(inbox._registry, deadline_ns))
    with guard as tree:
      endpoint, requests = inbox._load(tree)
      if descriptor is not None:
        inbox._expected(descriptor["endpoint"], endpoint)
      elif (endpoint is None or endpoint["run_id"] != record["run_id"]
          or endpoint["manager_identity"] != record["manager_identity"]
          or record["host_identity"] is None or endpoint["host_identity"] != record["host_identity"]["identity"]):
        raise ValueError()
      inbox._registry._verify_root(tree)
    options = {} if deadline_ns is None else {"deadline_ns": deadline_ns}
    dispatch = journal.read(record["run_id"], **options)
    return deepcopy({"endpoint": endpoint, "requests": [requests[key] for key in sorted(requests)],
      "dispatch": dispatch})
  except Exception:
    raise Conflict(_ERROR) from None


def supported(record):
  """仅内部精确组合声明；不注册服务、不证明当前可控制。"""
  try:
    return (sys.platform == "linux" and type(record) is dict
      and type(record.get("schema_version")) is int and record["schema_version"] == 2
      and record["agent"] in ("dsh", "pi", "omp") and record["backend"] == "managed"
      and (record["coordination_domain"] is not None) == (record["agent"] == "omp")
      and (record["agent"] != "dsh" or record["deployed_identity"]["runtime"] in _RUNTIMES))
  except Exception:
    return False


def available_locked(workspace, record, *, deadline_ns=None):
  """调用方持 owner 锁且已核实当前记录；观察失败不证明退出或释放。"""
  try:
    _record(workspace, record)
    if record["lifecycle_state"] != "active" or not supported(record) or record["host_identity"] is None:
      return False
    identities = (record["manager_identity"], record["host_identity"]["identity"])
    if any(not _same(run_owners.observed_process_identity(item["pid"]), item) for item in identities):
      return False
    options = {} if deadline_ns is None else {"deadline_ns": deadline_ns}
    state = channel_state(workspace, record, **options)
    if any(not _same(run_owners.observed_process_identity(item["pid"]), item) for item in identities):
      return False
    return not state["requests"] and state["dispatch"] is None
  except Exception:
    return False


def available(workspace, record):
  """取得 owner 短 NB 锁核实当前记录后读取候选能力；不产生授权。"""
  try:
    _record(workspace, record)
    registry = _registry(workspace)
    with registry._locked(nonblocking=True) as tree:
      current, _ = registry._records(tree)
      if not _same(current.get(record["run_id"]), record):
        return False
      return available_locked(workspace, record)
  except Exception:
    return False


def _current(registry, run_id):
  with stop_locks.locked(registry, time.monotonic_ns() + 2_000_000_000) as tree:
    records, _ = registry._records(tree)
    return records[run_id]


def factory_for(workspace, *, instance_fd, state_fd):
  """可信 Python 工厂；借入 FD 不关闭，不从 flags/env 或旧 JSON 重建服务。"""
  try:
    _fds(instance_fd, state_fd)
  except Exception:
    raise Conflict(_ERROR) from None

  def factory(*, run_id, host):
    service = None
    try:
      # 必须先检查借入 fd，避免关闭号码被后续 schema/目录读取复用。
      _fds(instance_fd, state_fd)
      run_owners._run_id(run_id)
      if type(host) is not SpawnedHost:
        raise ValueError()
      registry = _registry(workspace)
      record = _current(registry, run_id)
      _record(workspace, record)
      if (record["lifecycle_state"] != "active" or not supported(record)
          or record["protocol"]["control"] is not None or not _same(record["host_identity"], host.snapshot())):
        raise ValueError()
      layout = deepcopy(dsh_stop_scope.inspect_deployment(workspace, record,
        instance_fd=instance_fd, state_fd=state_fd))
      registered = None

      def verify(request):
        current = dsh_stop_scope.inspect_stop_request(workspace, request,
          instance_fd=instance_fd, state_fd=state_fd, expected_layout=layout, require_reviewed_stop=True)
        if registered is None or not _same(current, registered):
          raise Conflict(_ERROR)
        return True

      inbox, journal = _stores(workspace, run_id, wait_for_lock=True)
      service = StopService(run_id, host, inbox=inbox, journal=journal, verify=verify)
      if record["agent"] == "dsh":
        registry.bind_current_control(run_id, host, service,
          deadline_ns=time.monotonic_ns() + 2_000_000_000)
      registered = _current(registry, run_id)
      expected = deepcopy(record)
      if record["agent"] == "dsh":
        expected["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": service.describe()}
      else:
        # 独立 inbox 不改 owner；旧 manager 可继续读取同一 Registry/Domain 并收尾。
        endpoint = channel_state(workspace, registered)["endpoint"]
        if endpoint != service.describe():
          raise ValueError()
      if (not _same(registered, expected) or not _same(registered["host_identity"], host.snapshot())
          or service.belongs_to(run_id, host) is not True):
        raise ValueError()
      return service
    except BaseException as error:
      if service is not None:
        # 仅撤销此服务，不关闭原 host、不覆盖已提交记录、不重试。
        service.close()
      if not isinstance(error, Exception):
        raise
      raise Conflict(_ERROR) from None

  return factory


def default_factory(workspace, record, *, instance_fd, state_fd):
  """仅已验收固定组合的新启动登记端点；旧进程不补绑、不迁移。"""
  try:
    _record(workspace, record)
    if not supported(record):
      return None
    return factory_for(workspace, instance_fd=instance_fd, state_fd=state_fd)
  except Exception:
    # 可选控制不可用不能阻止原生启动；运行记录保留 control=null。
    return None
