"""DSH 实例停止计划：只读现场采集与精确新启动通道观察。"""
from copy import deepcopy
import hashlib
import os
import re
import time

from . import dsh_stop_control, dsh_stop_scope, lifecycle, maintenance, run_owners, run_stop_fence, stop_locks
from .storage import Conflict, Tree, instance_lock


def _selection(selected_runs):
  if (type(selected_runs) is not list or not 1 <= len(selected_runs) <= 1024
      or any(type(run) is not str or re.fullmatch(r"[0-9a-f]{32}", run) is None for run in selected_runs)
      or len(set(selected_runs)) != len(selected_runs)):
    raise ValueError("停止目标必须是互不重复的完整 run ID")
  return sorted(selected_runs)


def _digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


def _target(record):
  observation = record["session_observation"]
  return {"run_id": record["run_id"], "manager_identity": deepcopy(record["manager_identity"]),
    "deployed_identity": deepcopy(record["deployed_identity"]),
    "host_identity": deepcopy(record["host_identity"]), "start_cwd": deepcopy(record["start_cwd"]),
    "session_cwd": deepcopy(record["session_cwd"]),
    "session_ref": deepcopy(observation["session"]) if observation else None,
    "session_status": observation["confirmation"] if observation else "unknown"}


def workspace_for_scope(local, *, selected_runs, profile=None):
  """从明确机器归属查找所选运行；不使用启动默认配方猜测停止范围。"""
  from .local import available_profiles
  from .process import DependencyError
  from .workspace import load_instance_workspaces
  selected = _selection(selected_runs)
  available = dict(available_profiles())
  if profile is not None:
    if profile not in available:
      raise ValueError("未知 profile")
    if available[profile] not in ("dsh", "pi", "omp"):
      raise DependencyError("当前只读停止计划仅支持 DSH")
  profiles = [profile] if profile is not None else sorted(name for name, agent in available.items() if agent in ("dsh", "pi", "omp"))
  workspaces = load_instance_workspaces(local, profiles)
  try:
    if (len(workspaces) != len(profiles)
        or [ws.profile for ws in workspaces] != profiles
        or any(ws.agent not in ("dsh", "pi", "omp") for ws in workspaces)):
      raise ValueError()
    matches = []
    for ws in workspaces:
      with Tree(ws.instance) as instance:
        if instance.fd is None:
          # 有历史状态却缺物理实例时不能将它当作不存在的候选。
          with Tree(ws.state_root) as state:
            if state.fd is not None:
              raise ValueError()
          continue
      with lifecycle.observation_guard(ws):
        registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
        with stop_locks.locked(registry, time.monotonic_ns() + 2_000_000_000) as owner:
          records, _ = registry._records(owner)
          if set(selected) & set(records):
            if not set(selected) <= set(records):
              raise ValueError()
            matches.append(ws)
    if len(matches) != 1:
      raise ValueError()
  except Exception:
    raise Conflict("无法唯一确认同一 DSH 实例内的停止目标；请检查所选 run 与显式 profile") from None
  # 发现结果不授予控制；再次持双 SH 和 owner 锁核实完整部署与运行集合。
  return matches[0]


def preview_for_scope(local, *, selected_runs, profile=None, operation="stop_only"):
  if operation not in ("stop_only", "setup"):
    raise ValueError("仅支持 stop_only/setup 计划")
  workspace = workspace_for_scope(local, selected_runs=selected_runs, profile=profile)
  return preview_stop(workspace, selected_runs=selected_runs, operation=operation)


def preview_stop(workspace, *, selected_runs, operation="stop_only"):
  return capture_stop(workspace, selected_runs=selected_runs, operation=operation)[0]


def capture_stop(workspace, *, selected_runs, operation="stop_only"):
  """读取完整 owner 后重新核实部署；不把已登记集合视为完整外部 writer 覆盖。"""
  selected = _selection(selected_runs)
  if operation not in ("stop_only", "setup"):
    raise ValueError("仅支持 stop_only/setup 计划")
  try:
    if workspace.agent not in ("dsh", "pi", "omp"):
      raise ValueError()
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    with lifecycle.observation_guard(workspace) as instance_fd, Tree(workspace.state_root) as state:
      with instance_lock(state, shared=True, create=False) as state_fd, \
          stop_locks.locked(registry, time.monotonic_ns() + 2_000_000_000) as owner:
        if owner is None:
          raise ValueError()
        run_stop_fence.assert_unfenced(registry)
        records, _ = registry._records(owner)
        original = run_owners._encode(records)
        if not set(selected) <= set(records):
          raise ValueError()
        layout = None
        for run in selected:
          observed = dsh_stop_scope.inspect_deployment(workspace, records[run],
            instance_fd=instance_fd, state_fd=state_fd)
          if layout is not None and run_owners._encode(observed) != run_owners._encode(layout):
            raise ValueError()
          layout = observed
        references = sorted(run for run, record in records.items() if run_owners.record_state(record) != "idle_confirmed")
        resources = [{"resource_id": layout[name]["key_id"][:32], "key": layout[name],
          "reference_runs": references, "coverage": "unknown"} for name in ("instance", "native_home", "runtime")]
        scope = {**workspace.binding, "agent": workspace.agent}
        targets, runs = [], []
        for run in selected:
          record = records[run]; target = _target(record); targets.append(target)
          host = record["host_identity"]
          runs.append({"run_id": run, "scope": scope,
            "observation": {"state": "active", "manager_identity": record["manager_identity"],
              "host_identity": host["identity"] if host else None, "record_digest": _digest(record)},
            "deployment_digest": _digest(record["deployed_identity"]),
            "resource_ids": [resource["resource_id"] for resource in resources],
            "restore": {"mode": "manual", "capability": "unavailable", "target_digest": None,
              "session_status": "historical" if target["session_status"] in ("historical", "confirmed", "final") else "unknown"}})
        info = os.fstat(owner.fd)
        coordinator = {"kind": workspace.agent + "-instance-registry", "binding_digest": registry.binding_digest,
          "registry_physical": {"device": info.st_dev, "inode": info.st_ino}, "records_digest": _digest(records)}
        # 当前活通道只授予精确停止候选；未知外部资源覆盖仍阻断 setup。
        control = "supported" if all(dsh_stop_control.available_locked(workspace, records[run],
          deadline_ns=time.monotonic_ns() + 2_000_000_000)
          for run in selected) else "unavailable"
        plan = maintenance.build_dsh_stop_plan(scope=scope, operation=operation, selected_runs=selected,
          runs=runs, resources=resources, coordinator=coordinator, control_capability=control)
        current, _ = registry._records(owner)
        if run_owners._encode(current) != original:
          raise ValueError()
        run_stop_fence.assert_unfenced(registry)
        registry._verify_root(owner)
        return {"plan": plan, "targets": targets}, deepcopy(records), deepcopy(layout)
  except Exception:
    raise Conflict("DSH 停止目标、部署或运行集合不能确认；未写入停止意图") from None
