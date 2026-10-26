"""明确成功的 setup 收尾并交接人工恢复；不取消未知动作或执行恢复。"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import os
import threading
from types import SimpleNamespace

from . import commands, maintenance, maintenance_observation as observation, maintenance_release
from .storage import Conflict


_ERROR = "维护成功与人工恢复交接不能确认；保留已保存事实，请只读核验批次和部署"


def _load(domain, state, batch_id, revision, canonical=None, generation=None):
  saved, batch = observation._load(domain, state, batch_id, revision, canonical)
  intent, dispatch, result = saved["intent"], batch["maintenance_dispatch"], batch["operation_result"]
  if (intent["phase"] not in ("active", "dispatched")
      or generation is not None and intent["generation"] != generation
      or batch["phase"] != "maintenance_succeeded" or batch["review_required"] is not False
      or dispatch["state"] != "confirmed" or "setup_plan_digest" not in dispatch
      or "target_deployment_digest" not in dispatch or result is None
      or result["status"] != "succeeded" or result["exit_code"] != 0 or result["result_digest"] is None
      or any(run["restore"]["mode"] != "manual" for run in batch["plan"]["runs"])
      or any(item["stop_phase"] != "stopped_confirmed" or item["restore_phase"] not in ("not_requested", "manual")
        or not item["facts"]["exit_confirmed"] or not item["facts"]["resources_released"]
        or item["launch_dispatch"]["state"] != "not_dispatched" for item in batch["items"])):
    raise Conflict(_ERROR)
  return saved, batch


@contextmanager
def _checked_target(domain, batch_id, revision, args, canonical, generation):
  # 当前显式配置解析保持原错误，不按快照路径选择其它实例。
  workspace = commands.workspace(args)
  try:
    with domain._transaction() as initial:
      _, batch = _load(domain, initial, batch_id, revision, canonical, generation)
    observation._scope(args, workspace, batch)
    selected = {run: workspace for run in batch["accepted_runs"]}
    with ExitStack() as physical:
      leases = maintenance_release._leases(physical, initial, batch, selected)

      def check():
        with ExitStack() as owners, domain._transaction() as state:
          saved, current = _load(domain, state, batch_id, revision, canonical, generation)
          observation._scope(args, workspace, current)
          maintenance_release._hold_released(domain, state, saved, current, selected, leases, owners)

      check()
      target, pending = observation._read_target(workspace,
        batch["maintenance_dispatch"]["target_deployment_digest"], leases[batch["accepted_runs"][0]]["state_fd"])
      if target != "target-matches" or pending is not False:
        raise Conflict(_ERROR)
      check()
      yield workspace, selected, leases
  except Exception:
    raise Conflict(_ERROR) from None


def complete_setup_manual(domain, batch_id, *, expected_revision, args, approve):
  """锁外明确审阅；原 EX 内重核后只终结本批意图，保留人工待恢复清单。

  仅确证成功且目标当前匹配可收尾。此函数不调用 setup/recover/resume，不产生
  恢复许可或成功回执；提交响应未知不读回重签或自动重试，旧结果与所有原记录保留。
  """
  try:
    if not callable(approve):
      raise Conflict(_ERROR)
    current_args = SimpleNamespace(local=args.local, profile=args.profile, agent=getattr(args, "agent", None))
    with domain._transaction() as state:
      saved, batch = _load(domain, state, batch_id, expected_revision)
    canonical = maintenance.encode_batch(batch)
    generation = saved["intent"]["generation"]
    identity = (os.getpid(), threading.get_ident())
  except Exception:
    raise Conflict(_ERROR) from None
  with _checked_target(domain, batch_id, expected_revision, current_args, canonical, generation):
    pass
  # 明确交接与原维护批准分开；回调异常/中断原样传播，返回的副本不能修改冻结事实。
  if approve({"action": "complete-setup-manual", "batch": deepcopy(batch), "intent_generation": generation}) is not True:
    raise Conflict(_ERROR)
  if identity != (os.getpid(), threading.get_ident()):
    raise Conflict(_ERROR)
  with _checked_target(domain, batch_id, expected_revision, current_args, canonical, generation) as (workspace, selected, leases):
    # 实例/状态/包 EX → Domain → owner NB；owner 与物理租约持续覆盖原子提交和 fsync。
    with ExitStack() as owners, domain._transaction(write=True) as state:
      saved, current = _load(domain, state, batch_id, expected_revision, canonical, generation)
      observation._scope(current_args, workspace, current)
      maintenance_release._hold_released(domain, state, saved, current, selected, leases, owners)
      current["revision"] += 1
      for item in current["items"]:
        item["restore_phase"] = "manual"
      normalized = maintenance.decode_batch(maintenance.encode_batch(current))
      state["intents"][batch_id]["progress"] = normalized
      state["intents"][batch_id]["phase"] = "completed"
  return deepcopy(normalized)
