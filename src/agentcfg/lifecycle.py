"""物理实例准入；共享运行与独占维护使用同一个目录 inode。"""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
import time

from .deployment import json_bytes
from .storage import Conflict, StateError, Tree, advisory_lock


@dataclass(frozen=True)
class CooperativeRunLease:
  """适配器可信上下文；只传递闭包和 fd，不证明覆盖或授予控制许可。"""

  physical_fd: int
  package_guard: Callable
  owner_guard: Callable
  observer_factory: Callable | None = None

  def __post_init__(self):
    if (type(self.physical_fd) is not int or self.physical_fd < 0
        or not callable(self.package_guard) or not callable(self.owner_guard)
        or self.observer_factory is not None and not callable(self.observer_factory)):
      from .process import DependencyError
      raise DependencyError("可信运行租约上下文无效；不能启动原生宿主")


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
def inactive_guard(workspace, *, physical=None):
  """普通适配器维护先取物理 EX，再检查持久归属；核实仍用纯物理 guard。"""
  from .run_owners import Registry
  with (physical if physical is not None else guard(workspace)) as fd:
    Registry(workspace.state_root / "run-owners", workspace.binding).assert_inactive()
    yield fd


def observation_guard(workspace, *, shared=True):
  """只打开已有物理归属；查询不创建实例、锁文件或所有权标记。"""
  if workspace.agent == "omp":
    from .resource_scopes import scope_claim_exists
    if scope_claim_exists(workspace.instance):
      from .omp_observation import guard as observe_scope
      return observe_scope(workspace, shared=shared)
    from .omp_identity import lifecycle_guard
    return lifecycle_guard(workspace, create=False, shared=shared)
  return guard(workspace, create=False, shared=shared)


@contextmanager
def registered_run(workspace, *, metadata=None):
  """调用方持物理/状态共享租约；退出不构成全部后代释放的证据。"""
  from .run_owners import Registry, current_process_identity
  from .descendants import DescendantScope
  if metadata is not None and sys.platform != "linux" and workspace.agent == "dsh":
    # 不收窄旧DSH普通启动；Pi保留既有身份准入，不能借新登记绕开平台边界。
    try:
      print("当前平台未登记可核验进程身份；保留原运行租约，实例身份与自动控制能力未知。", file=sys.stderr)
    except (OSError, ValueError):
      pass
    yield None
    return
  registry = Registry(workspace.state_root / "run-owners", workspace.binding)
  manager = current_process_identity()
  with DescendantScope(manager) as descendants:
    run_id = registry.register(manager) if metadata is None else registry.register_v2(manager, metadata)
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


# 仅可信 Python 调用；此接缝不启用日常 OMP，也不签发维护许可。
_OMP_LAUNCH_ERROR = "OMP 启动预留不能确认；保留保护并重新核验"


def _omp_path(value):
  import unicodedata
  if not isinstance(value, (str, Path)):
    raise Conflict(_OMP_LAUNCH_ERROR)
  raw = str(value)
  path = Path(raw)
  if (not path.is_absolute() or path == Path("/") or raw.startswith("//") or "\\" in raw or str(path) != raw
      or any(part in (".", "..") for part in raw.split("/"))
      or any(unicodedata.category(char) == "Cc" for char in raw)):
    raise Conflict(_OMP_LAUNCH_ERROR)
  return path


def _omp_launch_context(workspace):
  import hashlib
  from .paths import safe_id
  raw = workspace.resolved.data["machine"]["paths"]["state_root"]
  if type(raw) is not str:
    raise Conflict(_OMP_LAUNCH_ERROR)
  root = _omp_path(raw) / "lifecycle"
  profile = safe_id(workspace.profile)
  if (workspace.agent != "omp" or profile != workspace.binding["profile"]
      or _omp_path(workspace.state_root) != root.parent / "omp" / profile):
    raise Conflict(_OMP_LAUNCH_ERROR)
  _omp_path(workspace.instance)
  _omp_path(workspace.cache)
  owner = {"state_root": str(workspace.state_root), "binding": workspace.binding.copy()}
  return root, owner, hashlib.sha256(json_bytes(owner)).hexdigest()


@dataclass(frozen=True)
class OmpLaunchReservation:
  """只含不可变标识的预留候选；并非物理覆盖、owner 或维护许可。"""

  domain_root: Path
  domain_id: str
  domain_physical: tuple[int, int]
  run_id: str
  op_id: str
  generation: int
  resources: tuple[str, ...]
  runtime_resource_id: str
  runtime_identity: str
  owner_ref_digest: str

  def __post_init__(self):
    import re
    from .paths import safe_id
    if (not isinstance(self.domain_root, Path) or _omp_path(self.domain_root) != self.domain_root
        or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None
          for value in (self.domain_id, self.run_id, self.op_id, self.runtime_resource_id))
        or type(self.domain_physical) is not tuple or len(self.domain_physical) != 2
        or any(type(value) is not int for value in self.domain_physical)
        or self.domain_physical[0] < 0 or self.domain_physical[1] <= 0
        or type(self.generation) is not int or self.generation <= 0
        or type(self.resources) is not tuple or len(self.resources) != 3
        or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None for value in self.resources)
        or tuple(sorted(set(self.resources))) != self.resources or self.runtime_resource_id not in self.resources
        or type(self.runtime_identity) is not str or safe_id(self.runtime_identity) != self.runtime_identity
        or type(self.owner_ref_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", self.owner_ref_digest) is None):
      raise Conflict(_OMP_LAUNCH_ERROR)


def reserve_omp_launch(workspace, runtime_identity):
  """不取物理 SH；声明/anchor 选择与预留在同一 Domain 写事务中完成。"""
  from . import resource_coordination as coordination, resource_scopes as scopes
  from .paths import safe_id
  from .resource_protocol import decode
  import uuid
  try:
    root, owner, digest = _omp_launch_context(workspace)
    safe_id(runtime_identity)
    domain = coordination.Domain(root)
    with domain._transaction(write=True) as state:
      with Tree(workspace.instance) as instance, Tree(workspace.instance / "user-home") as home:
        if instance.fd is None or home.fd is None:
          raise Conflict(_OMP_LAUNCH_ERROR)
      with Tree(workspace.instance.parent / scopes._CLAIMS) as claims:
        raw = claims.read(scopes._claim_name(workspace.instance), max_bytes=scopes._LIMIT)
        if raw is None or raw[1] != 0o600:
          raise Conflict(_OMP_LAUNCH_ERROR)
        claim = decode(raw[0], kind="scope-claim")
      if (claim["domain_id"] != state["domain_id"] or claim["domain_physical"] != state["physical"]
          or claim["owner_ref"] != owner or claim["instance_path"] != str(workspace.instance)
          or not coordination.runtime_claim_exists(workspace.cache, runtime_identity)):
        raise Conflict(_OMP_LAUNCH_ERROR)
      runtime_claim = coordination._read_runtime_claim(workspace.cache, runtime_identity)
      chosen = []
      for kind, path in (("instance", workspace.instance / ".agentcfg-omp.lock"),
          ("native-home", workspace.instance / "user-home")):
        matches = [record for record in state["resources"].values()
          if record["status"] == "ready" and record["key"]["kind"] == kind and record.get("path") == str(path)]
        if len(matches) != 1 or matches[0]["scope_id"] != claim["scope_id"]:
          raise Conflict(_OMP_LAUNCH_ERROR)
        chosen.append(matches[0])
      if chosen[0]["anchor_digest"] != chosen[1]["anchor_digest"]:
        raise Conflict(_OMP_LAUNCH_ERROR)
      runtimes = [record for record in state["resources"].values()
        if record["status"] == "ready" and record["key"]["kind"] == "runtime"
        and record.get("cache") == str(workspace.cache) and record.get("runtime_identity") == runtime_identity]
      if (len(runtimes) != 1 or runtime_claim["domain_id"] != state["domain_id"]
          or runtime_claim["domain_physical"] != state["physical"]
          or runtime_claim["resource_id"] != runtimes[0]["resource_id"]
          or runtime_claim["resource_key"] != runtimes[0]["key"]):
        raise Conflict(_OMP_LAUNCH_ERROR)
      resources = sorted([record["resource_id"] for record in chosen] + [runtimes[0]["resource_id"]])
      if any("generation" not in entry and set(resources).intersection(entry["resources"])
          for entry in state["reservations"].values()):
        raise Conflict(_OMP_LAUNCH_ERROR)
      receipt = domain._reserve_locked(state, run_id=uuid.uuid4().hex, op_id=uuid.uuid4().hex, owner_ref=owner,
        resources=resources, expected_revision=state["revision"])
    return OmpLaunchReservation(root, state["domain_id"],
      (state["physical"]["device"], state["physical"]["inode"]), receipt["run_id"], receipt["op_id"],
      receipt["generation"], tuple(receipt["resources"]), runtimes[0]["resource_id"], runtime_identity, digest)
  except Exception:
    raise Conflict(_OMP_LAUNCH_ERROR) from None


def _check_omp_reservation(state, reservation, workspace, *, phase):
  """调用方已持短协调锁；把候选绑定核验与实际提交放在同一事务。"""
  root, owner, digest = _omp_launch_context(workspace)
  if (type(reservation) is not OmpLaunchReservation or reservation.domain_root != root
      or reservation.owner_ref_digest != digest):
    raise Conflict(_OMP_LAUNCH_ERROR)
  record = state["reservations"].get(reservation.run_id)
  runtime = state["resources"].get(reservation.runtime_resource_id)
  if (state["domain_id"] != reservation.domain_id
      or (state["physical"]["device"], state["physical"]["inode"]) != reservation.domain_physical
      or record is None or record["phase"] != phase or record["op_id"] != reservation.op_id
      or record.get("generation") != reservation.generation
      or tuple(record["resources"]) != reservation.resources or record["owner_ref"] != owner
      or runtime is None or runtime["key"]["kind"] != "runtime"
      or runtime["runtime_identity"] != reservation.runtime_identity or runtime["cache"] != str(workspace.cache)):
    raise Conflict(_OMP_LAUNCH_ERROR)
  return record


def check_omp_launch(reservation, workspace, *, instance_fd, native_home_fd, package_fd):
  """调用方已持原顺序 SH；单个短协调事务内重核，不在此等待物理锁。"""
  from . import resource_coordination as coordination, resource_scopes as scopes
  try:
    root, _, _ = _omp_launch_context(workspace)
    domain = coordination.Domain(root)
    with domain._transaction(deadline_ns=time.monotonic_ns() + 2_000_000_000) as state:
      _check_omp_reservation(state, reservation, workspace, phase="reserved")
      scope_resources = scopes._verify(state, workspace, instance_fd=instance_fd, native_home_fd=native_home_fd)
      runtime_resource = domain._runtime(state, workspace.cache, reservation.runtime_identity, package_fd)
      if (runtime_resource != reservation.runtime_resource_id
          or scope_resources | {runtime_resource} != set(reservation.resources)):
        raise Conflict(_OMP_LAUNCH_ERROR)
      domain._unfenced(state, set(reservation.resources))
  except Exception:
    raise Conflict(_OMP_LAUNCH_ERROR) from None


def cancel_omp_launch(reservation, workspace):
  """仅可信启动器在未尝试关联 owner 时调用；精确 reserved 候选可取消。"""
  from .resource_coordination import Domain
  try:
    root, _, _ = _omp_launch_context(workspace)
    with Domain(root)._transaction(write=True) as state:
      record = _check_omp_reservation(state, reservation, workspace, phase="reserved")
      if "owner_link" in record:
        raise Conflict(_OMP_LAUNCH_ERROR)
      record["phase"] = "cancelled"
  except Exception:
    raise Conflict(_OMP_LAUNCH_ERROR) from None


@contextmanager
def omp_scope_write_guard(workspace, *, maintenance=None, stage=None):
  """只保护已登记实例和 HOME 的显式写入；不授予共享包维护或首次采用。"""
  from contextlib import ExitStack
  import os
  from .resource_coordination import Domain
  from .resource_keys import resource_key
  from .resource_scopes import _verify
  from .run_owners import Registry, record_state
  with ExitStack() as stack:
    try:
      root, _, _ = _omp_launch_context(workspace)
      instance = stack.enter_context(Tree(workspace.instance))
      if instance.fd is None:
        raise ValueError()
      with instance.parent(".agentcfg-omp.lock") as (parent, name):
        fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
      stack.callback(os.close, fd)
      resource_key("instance", workspace.instance / ".agentcfg-omp.lock", lease_fd=fd)
      stack.enter_context(advisory_lock(fd, unlock=False))
      home = stack.enter_context(Tree(workspace.instance / "user-home"))
      if home.fd is None:
        raise ValueError()
      domain = Domain(root)
      with domain._transaction() as state:
        resources = _verify(state, workspace, instance_fd=fd, native_home_fd=home.fd)
        if maintenance is None:
          domain._unfenced(state, resources)
        else:
          from .maintenance_execution import require_execution
          require_execution(maintenance).check_scope(domain, state, workspace, resources, stage=stage)
        if any(entry["phase"] not in ("cancelled", "released")
            and resources.intersection(entry["resources"]) for entry in state["reservations"].values()):
          raise ValueError()
        # 域 → owner NB；不在协调锁内等待 Registry，也不忽略未关联的活动旧记录。
        registry = Registry(workspace.state_root / "run-owners", workspace.binding)
        with registry._locked(nonblocking=True) as owners:
          from .run_stop_fence import assert_unfenced
          assert_unfenced(registry)
          records, _ = registry._records(owners)
          if any(record_state(record) != "idle_confirmed" for record in records.values()):
            raise ValueError()
    except Exception:
      raise Conflict("OMP实例或原生目录仍受保护，或其协调归属不能确认；未开始写入") from None
    # 仅持物理 EX 和 HOME 身份；后续部署沿原顺序取得状态 EX，协调锁已经释放。
    yield fd
