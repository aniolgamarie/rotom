"""当前显式 OMP scope 的 setup 批次状态；只读，不选择其它机器或授予控制。"""
from copy import deepcopy

from . import commands, maintenance_observation, maintenance_progress, omp_observation
from .resource_protocol import TERMINAL_INTENT_PHASES
from .storage import Conflict


_ERROR = "维护批次与当前明确范围不能确认；未修改现场"


def _exit_code(batch, intent, observed):
  result = batch["operation_result"]
  if result is not None and result["exit_code"] is not None and result["exit_code"] != 0:
    return result["exit_code"]
  # 初始计划取消只证明未推进本批；异常观察不能借终态返回成功。
  if (intent["phase"] == "cancelled" and result is None
      and batch["maintenance_dispatch"]["state"] == "not_dispatched"
      and observed.target_state == "target-unavailable" and observed.reason == "no-saved-target"
      and observed.resources_checked is False and observed.pending_journal is None):
    return 0
  if (intent["phase"] == "completed" and observed.target_state == "target-matches"
      and observed.resources_checked and observed.pending_journal is False):
    return 0
  # 明确成功但还未交接人工也保留待处理，原成功 code 在 operation_result 中独立呈现。
  return 4


def status_setup(args, batch_id):
  """只读原批次及当前目标观察；成功结果、人工交接和实际恢复状态保持分离。"""
  workspace = commands.workspace(args)
  try:
    domain = omp_observation._domain(workspace)
    with domain._transaction() as state:
      saved, batch = maintenance_progress._load(domain, state, batch_id)
    if batch["operation"] != "setup":
      raise Conflict(_ERROR)
    maintenance_observation._scope(args, workspace, batch)
  except Exception:
    raise Conflict(_ERROR) from None
  observed = maintenance_observation.observe_setup(domain, batch_id,
    expected_revision=batch["revision"], args=args)
  if observed.batch != batch:
    raise Conflict(_ERROR)
  intent = saved["intent"]
  return {"kind": "setup-maintenance-status", "readonly": True,
    "batch_id": batch_id, "revision": batch["revision"], "intent_generation": intent["generation"],
    "intent_phase": intent["phase"], "scope": {"agent": workspace.agent, **deepcopy(workspace.binding)},
    "phase": batch["phase"], "operation": "setup", "maintenance_dispatch": deepcopy(batch["maintenance_dispatch"]),
    "operation_result": deepcopy(batch["operation_result"]), "review_required": batch["review_required"],
    "items": deepcopy(batch["items"]), "observation": {"target_state": observed.target_state,
      "resources_checked": observed.resources_checked, "pending_journal": observed.pending_journal,
      "reason": observed.reason}, "protected": intent["phase"] not in TERMINAL_INTENT_PHASES,
    "continue_status": "not_sent", "exit_code": _exit_code(batch, intent, observed)}
