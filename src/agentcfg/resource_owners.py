"""内部 OMP owner 关联与退出记账；不启动宿主、不生成退出证明或维护许可。"""

from copy import deepcopy
from contextlib import ExitStack, contextmanager
import hashlib
import os
import re
import stat
import time

from . import omp_identity, run_owners
from .paths import _absolute_directory
from .resource_coordination import DomainLockBusy, _boundary, _physical
from .resource_keys import resource_key
from .run_owners import Registry, _encode, record_state
from .storage import Conflict, Tree


_ERROR = "共享资源 owner 关联不能确认；保留阻塞并重新核验"
_RELEASE_LOCK_WAIT_NS = 2_000_000_000


class _ReleaseOwnerBusy(Exception):
  """只表示尚未进入退出写入的 owner 短锁竞争。"""


@contextmanager
def _release_transaction(domain, run_id, workspace):
  """Domain → owner NB；首锁竞争共用原预算，yield 后任何异常都不重放。"""
  from .stop_locks import try_locked
  deadline = time.monotonic_ns() + _RELEASE_LOCK_WAIT_NS
  while True:
    if time.monotonic_ns() >= deadline:
      raise Conflict(_ERROR)
    entered = False
    try:
      busy = False
      # owner 的关闭晚于 Domain 提交，保持跨文件提交的原锁边界。
      with ExitStack() as owners:
        try:
          with domain._transaction(write=True, deadline_ns=deadline) as state:
            entry = state["reservations"][run_id]
            registry = _registry(workspace, entry)
            tree = owners.enter_context(try_locked(registry))
            if tree is None:
              # 先异常退出 Domain，禁止空提交；owner 适配器随后正常退出。
              raise _ReleaseOwnerBusy()
            if time.monotonic_ns() >= deadline:
              raise Conflict(_ERROR)
            entered = True
            yield state, entry, registry, tree
        except _ReleaseOwnerBusy:
          if entered:
            raise
          busy = True
      if busy:
        raise _ReleaseOwnerBusy()
      return
    except (_ReleaseOwnerBusy, DomainLockBusy):
      if entered:
        raise
      left = deadline - time.monotonic_ns()
      if left <= 0:
        raise Conflict(_ERROR) from None
      # 所有元数据锁均已释放；不等待物理锁、不重试已开始的持久化阶段。
      time.sleep(min(0.01, left / 1_000_000_000))


def _digest(value):
  return hashlib.sha256(_encode(value)).hexdigest()


def _registry(workspace, entry):
  expected = {"state_root": str(workspace.state_root), "binding": workspace.binding}
  if (workspace.agent != "omp" or workspace.profile != workspace.binding["profile"]
      or entry["owner_ref"] != expected):
    raise Conflict(_ERROR)
  return Registry(workspace.state_root / "run-owners", workspace.binding)


def _runtime_resources(domain, state, entry, runtime_fds, *, workspace, instance_fd, native_home_fd, unfenced=True):
  from .resource_scopes import _verify, scope_claim_exists
  resources = domain._resources(state, entry["resources"])
  runtimes = {rid for rid in resources if state["resources"][rid]["key"]["kind"] == "runtime"}
  if len(runtimes) != 1 or type(runtime_fds) is not dict or set(runtime_fds) != runtimes:
    raise Conflict(_ERROR)
  if resources != runtimes or scope_claim_exists(workspace.instance):
    scope = _verify(state, workspace, instance_fd=instance_fd, native_home_fd=native_home_fd)
    if resources != runtimes | scope:
      raise Conflict(_ERROR)
  if unfenced:
    domain._unfenced(state, resources)
  for rid, fd in runtime_fds.items():
    resource = state["resources"][rid]
    if domain._runtime(state, resource["cache"], resource["runtime_identity"], fd) != rid:
      raise Conflict(_ERROR)


def _runtime_digest(state, entry):
  runtimes = [state["resources"][rid]["runtime_identity"] for rid in entry["resources"]
    if state["resources"][rid]["key"]["kind"] == "runtime"]
  if len(runtimes) != 1:
    raise Conflict(_ERROR)
  runtime = runtimes[0]
  # 与 run_metadata 对已部署 runtime identity 的投影保持一致。
  return runtime if re.fullmatch(r"[0-9a-f]{64}", runtime) else hashlib.sha256(runtime.encode()).hexdigest()


def _evidence(workspace, tree, *, instance_fd, native_home_fd):
  native = omp_identity.native_identity(workspace.profile, workspace.instance)
  omp_identity.validate_layout(native)
  if (tree is None or not stat.S_ISREG(os.fstat(instance_fd).st_mode)
      or not stat.S_ISDIR(os.fstat(native_home_fd).st_mode)):
    raise Conflict(_ERROR)
  instance_path = workspace.instance / ".agentcfg-omp.lock"
  instance_key = resource_key("instance", instance_path, lease_fd=instance_fd).as_dict()
  home_key = resource_key("native-home", native.home, lease_fd=native_home_fd).as_dict()
  with Tree(workspace.instance) as instance:
    raw = instance.read(".agentcfg-omp-owner.json", max_bytes=65536)
    if raw is None:
      raise Conflict(_ERROR)
    omp_identity._validate_saved_owner(raw, omp_identity.ownership(workspace))
    ownership_digest = hashlib.sha256(raw[0]).hexdigest()
  return {"registry_physical": _physical(tree.fd),
    "instance": {"path": str(instance_path), "key": instance_key},
    "native_home": {"path": str(native.home), "key": home_key},
    "ownership_digest": ownership_digest}


def _coordination(state, entry, evidence):
  # 摘要绑定完整 scope、run/op、包资源和物理观察；不把路径摘要当成物理身份。
  link = {key: deepcopy(entry[key]) for key in ("run_id", "op_id", "owner_ref", "resources")}
  if "generation" in entry:
    link["generation"] = entry["generation"]
  link.update(domain_id=state["domain_id"], domain_physical=state["physical"], evidence=evidence)
  return {"protocol": "rotom-owner-link-v1", "domain_id": state["domain_id"],
    "domain_physical": deepcopy(state["physical"]), "op_id": entry["op_id"],
    "link_digest": _digest(link)}


def _check_link(domain, state, entry, workspace, registry, tree, record, *,
    instance_fd, native_home_fd, runtime_fds, expected_state="active", expected_digest=None, unfenced=True):
  _runtime_resources(domain, state, entry, runtime_fds, workspace=workspace,
    instance_fd=instance_fd, native_home_fd=native_home_fd, unfenced=unfenced)
  registry._verify_root(tree)
  evidence = _evidence(workspace, tree, instance_fd=instance_fd, native_home_fd=native_home_fd)
  link = entry["owner_link"]
  if (evidence != {key: value for key, value in link.items() if key != "record_digest"}
      or record is None or record_state(record) != expected_state
      or record["run_id"] != entry["run_id"] or record["agent"] != "omp"
      or record["backend"] != "managed" or record["deployed_identity"]["runtime"] != _runtime_digest(state, entry)
      or record["native_home_ref"]["path"] != evidence["native_home"]["path"]
      or record["coordination_domain"] != _coordination(state, entry, evidence)
      or _digest(record) != (expected_digest or link["record_digest"])):
    raise Conflict(_ERROR)


def attach_owner(domain, run_id, *, workspace, manager_identity, metadata,
    instance_fd, native_home_fd, runtime_fds, expected_reservation=None):
  """先 durable pending，再发布同 ID owner；部分提交只保留阻塞，无自动重试。

  仅供可信内部调用：调用者须按既有顺序持续持有实例、状态、包 SH；HOME fd
  只固定目录身份，未假称是额外的物理锁。每个短事务均按协调 → owner NB 排序。
  """
  with _boundary():
    if (type(metadata) is not dict or metadata.get("coordination_domain") is not None
        or metadata.get("agent") != "omp" or metadata.get("backend") != "managed"):
      raise Conflict(_ERROR)
    # 第一事务不得写 owner。只有其 fsync 成功返回，才允许进入第二事务。
    with ExitStack() as owners, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if expected_reservation is not None:
        from .lifecycle import _check_omp_reservation
        if _check_omp_reservation(state, expected_reservation, workspace, phase="reserved") is not entry:
          raise Conflict(_ERROR)
      if entry["phase"] != "reserved" or "owner_link" in entry:
        raise Conflict(_ERROR)
      registry = _registry(workspace, entry)
      _runtime_resources(domain, state, entry, runtime_fds, workspace=workspace,
        instance_fd=instance_fd, native_home_fd=native_home_fd)
      tree = owners.enter_context(registry._locked(create=True, nonblocking=True))
      records, _ = registry._records(tree)
      if run_id in records:
        raise Conflict(_ERROR)
      evidence = _evidence(workspace, tree, instance_fd=instance_fd, native_home_fd=native_home_fd)
      supplied = deepcopy(metadata)
      supplied["coordination_domain"] = _coordination(state, entry, evidence)
      record = registry._prepare_v2(run_id, manager_identity, supplied)
      if (record["native_home_ref"]["path"] != evidence["native_home"]["path"]
          or record["deployed_identity"]["runtime"] != _runtime_digest(state, entry)):
        raise Conflict(_ERROR)
      entry["owner_link"] = {**evidence, "record_digest": _digest(record)}
      entry["phase"] = "owner_pending"
      pending = deepcopy(entry)

    with ExitStack() as owners, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if entry != pending:
        raise Conflict(_ERROR)
      registry = _registry(workspace, entry)
      # 不创建替代目录；pending 中固定的 owner 根丢失后必须保留阻塞。
      tree = owners.enter_context(registry._locked(nonblocking=True))
      if tree is None:
        raise Conflict(_ERROR)
      records, _ = registry._records(tree)
      if run_id in records:
        raise Conflict(_ERROR)
      _check_link(domain, state, entry, workspace, registry, tree, record,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds)
      registry._publish_record(tree, record)
      records, _ = registry._records(tree)
      _check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds)
      entry["phase"] = "owner_attached"
  return run_id


def dispatch_owner(domain, run_id, *, workspace, instance_fd, native_home_fd, runtime_fds, expected_reservation=None):
  """派发前重核双向引用并持久化 dispatched；此函数不执行启动。"""
  with _boundary(), ExitStack() as owners, domain._transaction(write=True) as state:
    entry = state["reservations"][run_id]
    if expected_reservation is not None:
      from .lifecycle import _check_omp_reservation
      if _check_omp_reservation(state, expected_reservation, workspace, phase="owner_attached") is not entry:
        raise Conflict(_ERROR)
    if entry["phase"] != "owner_attached":
      raise Conflict(_ERROR)
    registry = _registry(workspace, entry)
    tree = owners.enter_context(registry._locked(nonblocking=True))
    if tree is None:
      raise Conflict(_ERROR)
    records, _ = registry._records(tree)
    _check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
      instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds)
    entry["phase"] = "dispatched"


def _release_manager(run_id, observation):
  # 观察仍来自可信内部调用；序列化的标志、旧 receipt 或包 EX 不是新退出证明。
  if (type(observation) is not run_owners.ReleaseObservation or observation.run_id != run_id
      or observation.all_related_exited is not True or observation.complete is not True):
    raise Conflict(_ERROR)
  manager = run_owners._manager(observation.manager_identity)
  if _encode(run_owners.current_process_identity()) != _encode(manager):
    raise Conflict(_ERROR)
  return manager


def mark_owner_unknown(domain, run_id, *, workspace, manager_identity,
    instance_fd, native_home_fd, runtime_fds):
  """当前 manager 的不完整观察：先保存域 unknown，再更新同一 owner。

  调用者仍持原 SH；不推导释放、不删除引用或意图。部分提交保留阻塞，不重试；
  pending 关联或释放另有其原记账事实，本入口不把它们覆盖成一次成功退出。
  """
  with _boundary():
    manager = run_owners._manager(manager_identity)
    if _encode(run_owners.current_process_identity()) != _encode(manager):
      raise Conflict(_ERROR)
    with ExitStack() as owners, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if entry["phase"] not in ("owner_attached", "dispatched") or "release_receipt" in entry:
        raise Conflict(_ERROR)
      registry = _registry(workspace, entry)
      tree = owners.enter_context(registry._locked(nonblocking=True))
      if tree is None:
        raise Conflict(_ERROR)
      records, _ = registry._records(tree)
      record = records.get(run_id)
      _check_link(domain, state, entry, workspace, registry, tree, record,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds, unfenced=False)
      if _encode(record["manager_identity"]) != _encode(manager):
        raise Conflict(_ERROR)
      unknown = deepcopy(record)
      run_owners._set_state(unknown, "unknown")
      registry._validate_record(run_id + ".json", unknown)
      entry["phase"] = "unknown"
      pending = deepcopy(entry)

    with ExitStack() as owners, domain._transaction(write=True) as state:
      entry = state["reservations"][run_id]
      if entry != pending or _encode(run_owners.current_process_identity()) != _encode(manager):
        raise Conflict(_ERROR)
      registry = _registry(workspace, entry)
      tree = owners.enter_context(registry._locked(nonblocking=True))
      if tree is None:
        raise Conflict(_ERROR)
      records, originals = registry._records(tree)
      _check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds, unfenced=False)
      tree.replace(run_id + ".json", _encode(unknown), expected=originals[run_id][2])
      records, _ = registry._records(tree)
      digest = _digest(unknown)
      _check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds,
        expected_state="unknown", expected_digest=digest, unfenced=False)
      entry["owner_link"]["record_digest"] = digest
  return run_id


def _completed_record(record, *, observed_at_ns=None):
  completed = deepcopy(record)
  run_owners._set_state(completed, "idle_confirmed")
  if observed_at_ns is not None:
    completed["process_observation"]["observed_at_ns"] = observed_at_ns
  return completed


def _sync_completed_owner(registry, tree, run_id):
  # 前次可能已经 replace，却在 fsync/响应时失败；仅凭可读文件不能补记成功。
  with tree.open_read(run_id + ".json", max_bytes=65536) as (stream, _):
    os.fsync(stream.fileno())
  os.fsync(tree.fd)
  ancestor = tree.root.parent
  while True:
    with _absolute_directory(ancestor) as parent:
      os.fsync(parent)
    if ancestor == ancestor.parent:
      break
    ancestor = ancestor.parent
  registry._verify_root(tree)


def finish_owner(domain, run_id, *, observation, workspace,
    instance_fd, native_home_fd, runtime_fds):
  """同一存活 manager 的完整观察：先 pending，再 owner idle，最后 released。

  调用者仍持实例/状态/包 SH。这里只结束已关联的本次 run；其它 owner、意图、
  全局归属和原生 writer 不由这次观察清除。未知运行不能使用本入口。
  """
  with _boundary():
    manager = _release_manager(run_id, observation)
    with _release_transaction(domain, run_id, workspace) as (state, entry, registry, tree):
      if entry["phase"] != "dispatched" or "release_receipt" in entry:
        raise Conflict(_ERROR)
      records, _ = registry._records(tree)
      record = records.get(run_id)
      _check_link(domain, state, entry, workspace, registry, tree, record,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds, unfenced=False)
      if _encode(record["manager_identity"]) != _encode(manager):
        raise Conflict(_ERROR)
      completed = _completed_record(record)
      registry._validate_record(run_id + ".json", completed)
      entry["release_receipt"] = {"observed_at_ns": completed["process_observation"]["observed_at_ns"],
        "owner_record_digest": _digest(completed)}
      entry["phase"] = "release_pending"
    return reconcile_owner_release(domain, run_id, observation=observation, workspace=workspace,
      instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds)


def reconcile_owner_release(domain, run_id, *, observation, workspace,
    instance_fd, native_home_fd, runtime_fds):
  """补完本 manager 的 pending，或重新同步 released；再次要求完整观察。

  manager 改变、owner unknown 或来源损坏均保持阻塞；本方法不是旧 unknown 的 EX 核实器。
  receipt 固定末态与时间。released 仅重核并同步，不能重写 owner、重发启动或生成新退出事实。
  """
  with _boundary():
    manager = _release_manager(run_id, observation)
    with _release_transaction(domain, run_id, workspace) as (state, entry, registry, tree):
      if entry["phase"] not in ("release_pending", "released"):
        raise Conflict(_ERROR)
      records, originals = registry._records(tree)
      record = records.get(run_id)
      if record is None or _encode(record["manager_identity"]) != _encode(manager):
        raise Conflict(_ERROR)
      receipt = entry["release_receipt"]
      current_state = record_state(record)
      if current_state not in ("active", "idle_confirmed"):
        raise Conflict(_ERROR)
      if entry["phase"] == "released" and current_state != "idle_confirmed":
        raise Conflict(_ERROR)
      if (current_state == "idle_confirmed"
          and record["process_observation"]["observed_at_ns"] != receipt["observed_at_ns"]):
        raise Conflict(_ERROR)
      expected = receipt["owner_record_digest"] if current_state == "idle_confirmed" else None
      _check_link(domain, state, entry, workspace, registry, tree, record,
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds,
        expected_state=current_state, expected_digest=expected, unfenced=False)
      if current_state == "active":
        record = _completed_record(record, observed_at_ns=receipt["observed_at_ns"])
        if _digest(record) != receipt["owner_record_digest"]:
          raise Conflict(_ERROR)
        registry._validate_record(run_id + ".json", record)
        tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])
      _sync_completed_owner(registry, tree, run_id)
      records, _ = registry._records(tree)
      _check_link(domain, state, entry, workspace, registry, tree, records.get(run_id),
        instance_fd=instance_fd, native_home_fd=native_home_fd, runtime_fds=runtime_fds,
        expected_state="idle_confirmed", expected_digest=receipt["owner_record_digest"], unfenced=False)
      entry["phase"] = "released"
  return run_id
