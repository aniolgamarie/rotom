"""同一次已批准 setup 的内部执行；不开放 CLI、恢复或历史凭证重建。"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
import sys
import threading
from types import SimpleNamespace

from . import commands, maintenance, maintenance_dispatch, maintenance_permit, maintenance_progress
from . import deployment, maintenance_release, maintenance_setup, runtime
from .maintenance_deployment import check_stop_deployment
from .omp_lifecycle import _same_file, _shared_file
from .resource_protocol import TERMINAL_INTENT_PHASES
from .setup_preview import setup_deployment_digest, setup_plan_digest, _strict_json
from .storage import Conflict, Tree
from .deployment import json_bytes


_ERROR = "维护 setup 的当前批准、计划或资源不能确认；保留保护，不自动重试"
_TOKEN = object()


def _warn(message):
  try:
    print(message, file=sys.stderr)
  except BaseException:
    pass


@dataclass(frozen=True)
class SetupExecutionResult:
  batch: dict
  operation: commands.SetupResult


def require_execution(value):
  if (type(value) is not _Execution or not value._active
      or value._pid != os.getpid() or value._thread != threading.get_ident()):
    raise Conflict(_ERROR)
  return value


class _Execution:
  def __init__(self, token, domain, dispatch, args):
    if token is not _TOKEN or type(dispatch) is not maintenance_dispatch.SetupDispatchResult:
      raise Conflict(_ERROR)
    if type(dispatch.permit) is not maintenance_permit.BatchPermit:
      raise Conflict(_ERROR)
    self._domain, self._permit = domain, dispatch.permit
    self._generation = dispatch.permit._generation
    self._digest = dispatch.batch["maintenance_dispatch"]["setup_plan_digest"]
    self._batch, self._canonical = maintenance_permit._normalized(dispatch.batch,
      self._generation, self._digest, issued=True)
    self._args = SimpleNamespace(local=args.local, profile=args.profile, agent=getattr(args, "agent", None))
    self._pid, self._thread = os.getpid(), threading.get_ident()
    self._active, self._started, self._stage = True, False, "new"
    self._workspace = None

  def _load(self, domain, state):
    require_execution(self)
    if domain.root != self._domain.root:
      raise Conflict(_ERROR)
    saved, batch = maintenance_progress._load(domain, state, self._batch["batch_id"])
    if (saved["intent"]["phase"] not in ("active", "dispatched")
        or saved["intent"]["generation"] != self._generation
        or maintenance.encode_batch(batch) != self._canonical):
      raise Conflict(_ERROR)
    return saved, batch

  def _workspace_matches(self, workspace):
    if self._workspace is None:
      raise Conflict(_ERROR)
    for name in ("agent", "profile", "binding", "instance", "state_root", "cache"):
      if getattr(workspace, name) != self._workspace[name]:
        raise Conflict(_ERROR)

  def _plan(self, workspace, lock, candidate, plan):
    if setup_plan_digest(workspace, lock, candidate, plan) != self._digest:
      raise Conflict(_ERROR)
    try:
      with self._domain._transaction() as state:
        _, batch = self._load(self._domain, state)
        maintenance_setup._check_target(state, batch, workspace, plan)
    except Exception:
      raise Conflict(_ERROR) from None
    return workspace, lock, candidate, plan

  def approve(self, workspace, lock, candidate, plan):
    require_execution(self)
    if (self._stage != "new" or sys.platform != "linux" or workspace.agent != "omp"
        or not self._args.local or type(self._args.profile) is not str
        or not self._args.profile or workspace.profile != self._args.profile):
      raise Conflict(_ERROR)
    self._plan(workspace, lock, candidate, plan)
    self._workspace = {name: deepcopy(getattr(workspace, name))
      for name in ("agent", "profile", "binding", "instance", "state_root", "cache")}
    self._runtime = plan.current["launch"].get("runtime_identity", plan.current["launch"].get("lock_identity"))
    self._stage = "approved"

  def check_runtime(self, workspace, identity, *, stage):
    require_execution(self)
    self._workspace_matches(workspace)
    if identity != self._runtime or self._stage != {"prepare": "preflight", "sync": "prepared", "apply": "sync_done"}.get(stage):
      raise Conflict(_ERROR)

  def check_scope(self, domain, state, workspace, resources, *, stage):
    require_execution(self)
    self._workspace_matches(workspace)
    expected = {"preflight": "approved", "prepare": "preflight", "apply": "sync_done"}
    if stage not in expected or self._stage != expected[stage]:
      raise Conflict(_ERROR)
    _, batch = self._load(domain, state)
    accepted = {item["resource_id"] for item in batch["plan"]["resources"]
      if item["key"]["kind"] in ("instance", "native-home")}
    if resources != accepted or any(key != batch["batch_id"] and entry["phase"] not in TERMINAL_INTENT_PHASES
        and resources.intersection(entry["resources"]) for key, entry in state["intents"].items()):
      raise Conflict(_ERROR)
    self._stage = {"preflight": "preflight", "prepare": "prepared", "apply": "apply_ready"}[stage]

  def _current_plan(self, workspace):
    # 不在 Domain/owner 锁内读取配置；调用方已持本次物理/状态/包租约。
    current, lock, candidate = commands.prepared(self._args)
    self._workspace_matches(current)
    self._workspace_matches(workspace)
    return self._plan(current, lock, candidate, commands.current_plan(current, lock, candidate))

  def _physical(self, domain, workspace, leases):
    _, _, _, plan = self._current_plan(workspace)
    with domain._transaction() as state:
      saved, batch = self._load(domain, state)
    for run in batch["accepted_runs"]:
      check_stop_deployment(workspace, saved["acceptance"]["records"][run],
        instance_fd=leases[run]["instance_fd"], state_fd=leases[run]["state_fd"])
    return setup_deployment_digest(plan.current)

  def begin_sync(self, domain, workspace, identity, *, instance_fd, state_fd, native_home_fd, package_fd):
    self.check_runtime(workspace, identity, stage="sync")
    self._stage = "sync_entering"
    with domain._transaction() as state:
      _, batch = self._load(domain, state)
      runtime_ids = [item["resource_id"] for item in batch["plan"]["resources"] if item["key"]["kind"] == "runtime"]
    if len(runtime_ids) != 1:
      raise Conflict(_ERROR)
    lease = {"instance_fd": instance_fd, "state_fd": state_fd, "native_home_fd": native_home_fd,
      "runtime_fds": {runtime_ids[0]: package_fd}}
    leases = {run: lease for run in batch["accepted_runs"]}
    workspaces = {run: workspace for run in batch["accepted_runs"]}
    target_digest = self._physical(domain, workspace, leases)
    # 原物理门禁内单次消费；owner NB 持续覆盖协调提交，不持协调锁执行同步。
    with ExitStack() as owners, domain._transaction(write=True) as state:
      saved, batch = self._load(domain, state)
      maintenance_release._hold_released(domain, state, saved, batch, workspaces, leases, owners)
      maintenance_permit.consume_batch_permit(self._permit, batch=batch,
        intent_generation=self._generation, setup_plan_digest=self._digest)
      batch["revision"] += 1
      batch["phase"] = "maintenance_running"
      batch["maintenance_dispatch"]["state"] = "dispatched"
      batch["maintenance_dispatch"]["target_deployment_digest"] = target_digest
      normalized = maintenance.decode_batch(maintenance.encode_batch(batch))
      state["intents"][batch["batch_id"]]["progress"] = normalized
    self._batch, self._canonical = normalized, maintenance.encode_batch(normalized)
    self._started, self._stage = True, "sync_running"

  def finish_sync(self):
    require_execution(self)
    if self._stage != "sync_running":
      raise Conflict(_ERROR)
    self._stage = "sync_done"

  @contextmanager
  def apply_guard(self, workspace, lock, candidate, plan, *, instance_fd, state_fd):
    with ExitStack() as physical:
      try:
        require_execution(self)
        self._workspace_matches(workspace)
        if self._stage != "apply_ready" or setup_plan_digest(workspace, lock, candidate, plan) != self._digest:
          raise Conflict(_ERROR)
        self._stage = "apply_entering"
        package = physical.enter_context(_shared_file(workspace.cache, "leases/" + self._runtime + ".lock"))
        home = physical.enter_context(Tree(workspace.instance / "user-home"))
        if home.fd is None:
          raise Conflict(_ERROR)
        with self._domain._transaction() as state:
          _, batch = self._load(self._domain, state)
          runtime_ids = [item["resource_id"] for item in batch["plan"]["resources"] if item["key"]["kind"] == "runtime"]
        if len(runtime_ids) != 1:
          raise Conflict(_ERROR)
        lease = {"instance_fd": instance_fd, "state_fd": state_fd, "native_home_fd": home.fd,
          "runtime_fds": {runtime_ids[0]: package}}
        leases = {run: lease for run in batch["accepted_runs"]}
        workspaces = {run: workspace for run in batch["accepted_runs"]}
        self._physical(self._domain, workspace, leases)
        with ExitStack() as owners, self._domain._transaction() as state:
          saved, batch = self._load(self._domain, state)
          maintenance_release._hold_released(self._domain, state, saved, batch, workspaces, leases, owners)
      except Exception:
        raise Conflict(_ERROR) from None
      # 包 SH 与原实例/状态 EX 覆盖原 recover/prepare/transact；不重新获取已持 EX。
      self._stage = "apply_running"
      yield
      try:
        with ExitStack() as owners, self._domain._transaction() as state:
          saved, batch = self._load(self._domain, state)
          maintenance_release._hold_released(self._domain, state, saved, batch, workspaces, leases, owners)
        with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
          _same_file(state, "instance.lock", state_fd)
          if state.read("pending.json") is not None:
            raise Conflict(_ERROR)
          current = deployment.read_state(state)["current"]
          if setup_deployment_digest(current) != batch["maintenance_dispatch"]["target_deployment_digest"]:
            raise Conflict(_ERROR)
          runtime.check_deployed_resources(current, target)
          _same_file(state, "instance.lock", state_fd)
        with ExitStack() as owners, self._domain._transaction() as state:
          saved, batch = self._load(self._domain, state)
          maintenance_release._hold_released(self._domain, state, saved, batch, workspaces, leases, owners)
      except Exception:
        raise Conflict(_ERROR) from None
      self._stage = "apply_done"

  def finish(self, outcome):
    require_execution(self)
    if not self._started:
      raise Conflict(_ERROR)
    if outcome is None:
      result = {"operation": "setup", "status": "unknown", "exit_code": None, "result_digest": None}
      phase = "unknown"
    else:
      if type(outcome) is not commands.SetupResult or type(outcome.code) is not int:
        raise Conflict(_ERROR)
      if outcome.code == 0 and self._stage != "apply_done":
        raise Conflict(_ERROR)
      value = {"code": outcome.code, "result": outcome.result, "reason": outcome.reason, "hint": outcome.hint}
      _strict_json(value)
      result = {"operation": "setup", "status": "succeeded" if outcome.code == 0 else "partial",
        "exit_code": outcome.code, "result_digest": hashlib.sha256(json_bytes(value)).hexdigest()}
      phase = "maintenance_succeeded" if outcome.code == 0 else "partial"
    with self._domain._transaction(write=True) as state:
      _, batch = self._load(self._domain, state)
      batch["revision"] += 1
      batch["phase"] = phase
      batch["maintenance_dispatch"]["state"] = "confirmed" if outcome is not None else "unknown"
      batch["operation_result"] = result
      batch["review_required"] = phase != "maintenance_succeeded"
      normalized = maintenance.decode_batch(maintenance.encode_batch(batch))
      state["intents"][batch["batch_id"]]["progress"] = normalized
      if phase in ("unknown", "partial"):
        # 协调协议要求未知进展与同一原 intent 的未知阶段在一笔事务中一致。
        state["intents"][batch["batch_id"]]["phase"] = "unknown"
    self._batch, self._canonical = normalized, maintenance.encode_batch(normalized)
    self._stage = "finished"
    return deepcopy(normalized)


def execute_setup(domain, dispatch, *, args, progress, preview):
  """只接受本进程已发行许可；原 setup 结果/异常不改写，落盘不保存正文。"""
  try:
    execution = _Execution(_TOKEN, domain, dispatch, args)
  except Exception:
    raise Conflict(_ERROR) from None
  try:
    try:
      outcome = commands._setup_operation(execution._args, progress=progress, preview=preview,
        approve=execution.approve, maintenance=execution)
    except BaseException:
      if execution._started:
        try:
          execution.finish(None)
        except BaseException:
          # 对账失败不掩盖原业务异常，也不读回重签；原 running/intent 继续阻断。
          _warn("维护结果记账未确认；保留保护，请先核验批次与部署日志。")
      elif execution._permit._used:
        # 消费后提交响应未知时没有可信新 CAS；不读回升级或再次写入 unknown。
        _warn("维护执行准入记账未确认；未继续同步，请先核验批次与部署日志。")
      raise
    if not execution._started:
      # 原核心在实际同步前明确拒绝；不伪造已执行结果或重用已有派发许可。
      return SetupExecutionResult(deepcopy(execution._batch), outcome)
    return SetupExecutionResult(execution.finish(outcome), outcome)
  finally:
    execution._active = False
