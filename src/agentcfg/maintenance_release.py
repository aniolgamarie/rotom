"""setup 批次的物理释放确认；不是执行许可，不用于 stop_only 完成判定。

必须自行取得原实例/状态/包 EX，并核实已释放 owner；保存的事实只是本次观察，
后续 setup 仍须在其原副作用门禁重新核验。不会清意图、修复 unknown 或执行宿主。
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass

from . import maintenance, maintenance_progress, omp_observation, resource_owners, resource_scopes
from .maintenance_deployment import check_stop_deployment
from .control_deadline import ControlDeadline
from .omp_lifecycle import _same_file
from .paths import safe_id
from .resource_protocol import TERMINAL_INTENT_PHASES
from .run_owners import record_state
from .storage import Conflict, Tree, advisory_lock, instance_lock


_ERROR = "维护资源释放不能确认；保留原批次事实和保护，不执行 setup"


@dataclass(frozen=True)
class SetupReleaseWaitResult:
  """退出观察与本次明确返回的物理释放事实；返回前锁已释放，不是 setup 许可。"""

  confirmed_runs: tuple[str, ...]
  pending_runs: tuple[str, ...]
  release_confirmed: bool
  revision: int
  exit_code: int
  reason: str | None


def _budget_reason(deadline):
  try:
    return "deadline-expired" if deadline.expired() else None
  except Exception:
    return "clock-unconfirmed"


def wait_for_setup_release(domain, batch_id, *, deadline, observe, workspaces):
  """同一原预算先保存退出观察，再单次尝试原 EX 确认；不执行维护。

  observe 必须可信且非阻塞。确认事务的 I/O/fsync 可以跨截止点，只有调用前后
  检查预算，不提供硬实时中断。响应不明不读回、不重新签 CAS、不重试或清保护。
  """
  try:
    if (type(deadline) is not ControlDeadline or not callable(observe)
        or type(workspaces) is not dict):
      raise ValueError()
    selected = dict(workspaces)
    with domain._transaction() as state:
      saved, batch = maintenance_progress._load(domain, state, batch_id)
      if (saved["intent"]["phase"] not in ("active", "dispatched")
          or batch["phase"] not in ("accepted", "stop_requested") or batch["operation"] != "setup"
          or set(selected) != set(batch["accepted_runs"])):
        raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None
  confirmed = tuple(sorted(item["run_id"] for item in batch["items"] if item["facts"]["exit_confirmed"]))
  pending = tuple(sorted(set(batch["accepted_runs"]) - set(confirmed)))
  revision = batch["revision"]

  def result(reason=None, *, release_confirmed=False):
    return SetupReleaseWaitResult(confirmed, pending, release_confirmed, revision, 4 if reason else 0, reason)

  reason = _budget_reason(deadline)
  if reason:
    return result(reason)
  observed = maintenance_progress.wait_for_batch_release(domain, batch_id, deadline=deadline, observe=observe)
  confirmed, pending, revision = observed.confirmed_runs, observed.pending_runs, observed.revision
  if observed.exit_code != 0:
    return SetupReleaseWaitResult(confirmed, pending, False, revision, observed.exit_code, observed.reason)
  reason = _budget_reason(deadline)
  if reason:
    return result(reason)
  try:
    committed = confirm_setup_release(domain, batch_id, expected_revision=revision, workspaces=selected)
  except Conflict:
    return result("release-unconfirmed")
  revision = committed["revision"]
  return result(_budget_reason(deadline), release_confirmed=True)


def _load(domain, state, batch_id, expected_revision):
  saved, batch = maintenance_progress._load(domain, state, batch_id)
  if (type(expected_revision) is not int or batch["revision"] != expected_revision
      or saved["intent"]["phase"] not in ("active", "dispatched")
      or batch["operation"] != "setup" or batch["phase"] not in ("accepted", "stop_requested")
      or any(not item["facts"]["exit_confirmed"] or item["facts"]["resources_released"]
        or item["stop_phase"] not in ("accepted", "stop_requested") for item in batch["items"])):
    raise ValueError()
  return saved, batch


def _exclusive_file(stack, tree, name):
  stream, _ = stack.enter_context(tree.open_read(name, max_bytes=65536))
  fd = stream.fileno()
  _same_file(tree, name, fd)
  stack.enter_context(advisory_lock(fd))
  return fd


def _leases(stack, state, batch, workspaces):
  # 路径只能来自本次可信配置解析；记录只用于比对，不能引导打开其它实例。
  if type(workspaces) is not dict or set(workspaces) != set(batch["accepted_runs"]):
    raise ValueError()
  groups, leases, packages = {}, {}, {}
  for run in batch["accepted_runs"]:
    ws, entry = workspaces[run], state["reservations"][run]
    resource_owners._registry(ws, entry)
    key = (str(ws.instance), str(ws.state_root))
    if key in groups and groups[key].binding != ws.binding:
      raise ValueError()
    groups.setdefault(key, ws)
  held = {}
  for key, ws in sorted(groups.items()):
    target = stack.enter_context(Tree(ws.instance))
    instance_fd = _exclusive_file(stack, target, ".agentcfg-omp.lock")
    state_tree = stack.enter_context(Tree(ws.state_root))
    state_fd = stack.enter_context(instance_lock(state_tree, create=False))
    home = stack.enter_context(Tree(ws.instance / "user-home"))
    if home.fd is None:
      raise ValueError()
    held[key] = {"instance_fd": instance_fd, "state_fd": state_fd, "native_home_fd": home.fd}
  for run in batch["accepted_runs"]:
    ws, entry = workspaces[run], state["reservations"][run]
    runtimes = [rid for rid in entry["resources"] if state["resources"][rid]["key"]["kind"] == "runtime"]
    if len(runtimes) != 1:
      raise ValueError()
    rid = runtimes[0]
    resource = state["resources"][rid]
    if resource["cache"] != str(ws.cache):
      raise ValueError()
    if rid not in packages:
      cache = stack.enter_context(Tree(ws.cache))
      name = "leases/" + safe_id(resource["runtime_identity"]) + ".lock"
      packages[rid] = _exclusive_file(stack, cache, name)
    leases[run] = {**held[(str(ws.instance), str(ws.state_root))], "runtime_fds": {rid: packages[rid]}}
  return leases


def _hold_released(domain, state, saved, batch, workspaces, leases, stack):
  plan = batch["plan"]
  resources = domain._resources(state, [item["resource_id"] for item in plan["resources"]])
  if any(item["key"] != state["resources"][item["resource_id"]]["key"] for item in plan["resources"]):
    raise ValueError()
  if any(entry["phase"] not in ("released", "cancelled") and resources.intersection(entry["resources"])
      for entry in state["reservations"].values()):
    raise ValueError()
  if any(key != batch["batch_id"] and entry["phase"] not in TERMINAL_INTENT_PHASES and resources.intersection(entry["resources"])
      for key, entry in state["intents"].items()):
    raise ValueError()
  groups = {}
  for planned in plan["runs"]:
    run = planned["run_id"]
    ws, entry, lease = workspaces[run], state["reservations"][run], leases[run]
    if entry["phase"] != "released" or entry["resources"] != planned["resource_ids"]:
      raise ValueError()
    registry = resource_owners._registry(ws, entry)
    key = (str(registry.root), registry.binding_digest)
    if key not in groups:
      tree = stack.enter_context(registry._locked(nonblocking=True))
      if tree is None:
        raise ValueError()
      records, _ = registry._records(tree)
      scope = resource_scopes._verify(state, ws, instance_fd=lease["instance_fd"],
        native_home_fd=lease["native_home_fd"])
      related = {run_id: item for run_id, item in state["reservations"].items() if scope.intersection(item["resources"])}
      # EX 不能清掉旧的未关联/未知 owner，也不能忽略丢失的历史双向关联。
      for run_id, record in records.items():
        if run_id not in related or record.get("coordination_domain") is None:
          raise ValueError()
        omp_observation._record_link(state, related[run_id], ws, registry, tree, record, scope,
          lease["instance_fd"], lease["native_home_fd"])
      for run_id, item in related.items():
        if item["phase"] == "cancelled" and run_id not in records:
          continue
        if item["phase"] != "released" or run_id not in records or record_state(records[run_id]) != "idle_confirmed":
          raise ValueError()
      groups[key] = tree, records
    tree, records = groups[key]
    receipt = entry["release_receipt"]
    expected = resource_owners._completed_record(saved["acceptance"]["records"][run],
      observed_at_ns=receipt["observed_at_ns"])
    if records.get(run) != expected:
      raise ValueError()
    resource_owners._check_link(domain, state, entry, ws, registry, tree, records[run],
      instance_fd=lease["instance_fd"], native_home_fd=lease["native_home_fd"], runtime_fds=lease["runtime_fds"],
      expected_state="idle_confirmed", expected_digest=receipt["owner_record_digest"], unfenced=False)
    with Tree(ws.state_root) as state_tree:
      _same_file(state_tree, "instance.lock", lease["state_fd"])


def confirm_setup_release(domain, batch_id, *, expected_revision, workspaces):
  """非阻塞原 EX → 短协调锁 → owner NB；锁保持到进展持久提交完成。

  无维护副作用；失败不清保护、不改 owner、不重试。返回值只是历史观察，
  所有物理锁离开本调用即关闭，不能把此值当作后续 setup 的授权或锁句柄。
  """
  try:
    with domain._transaction() as initial:
      saved, batch = _load(domain, initial, batch_id, expected_revision)
    with ExitStack() as physical:
      leases = _leases(physical, initial, batch, workspaces)
      for run in batch["accepted_runs"]:
        check_stop_deployment(workspaces[run], saved["acceptance"]["records"][run],
          instance_fd=leases[run]["instance_fd"], state_fd=leases[run]["state_fd"])
      # owner 外层 stack 确保协调表 replace/fsync/读回结束后才释放 owner 锁。
      with ExitStack() as owners, domain._transaction(write=True) as state:
        saved, batch = _load(domain, state, batch_id, expected_revision)
        _hold_released(domain, state, saved, batch, workspaces, leases, owners)
        for item in batch["items"]:
          item["facts"]["resources_released"] = True
          item["stop_phase"] = "stopped_confirmed"
        batch["phase"] = "stopped_confirmed"
        batch["revision"] += 1
        normalized = maintenance.decode_batch(maintenance.encode_batch(batch))
        state["intents"][batch_id]["progress"] = normalized
      return deepcopy(normalized)
  except Exception:
    raise Conflict(_ERROR) from None
