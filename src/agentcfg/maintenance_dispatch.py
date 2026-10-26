"""setup 派发意图的内部事务；只记账和发行内存凭证，不执行 setup。

批准来自无锁处的独立 setup 审阅；派发前重新取得原物理 EX，核验完整释放事实。
返回后锁已关闭，未来业务核心仍须在原首个副作用门禁核验并消费凭证。
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
import uuid

from . import maintenance, maintenance_permit, maintenance_progress, maintenance_release
from .maintenance_deployment import check_stop_deployment
from .run_owners import _run_id
from .storage import Conflict


_ERROR = "维护 setup 派发意图或批准不能确认；保留保护，不自动重试"


@dataclass(frozen=True)
class SetupDispatchResult:
  batch: dict
  permit: maintenance_permit.BatchPermit


def _load(domain, state, batch_id, expected_revision):
  saved, batch = maintenance_progress._load(domain, state, batch_id)
  if (type(expected_revision) is not int or batch["revision"] != expected_revision
      or saved["intent"]["phase"] not in ("active", "dispatched")
      or batch["operation"] != "setup" or batch["phase"] != "stopped_confirmed"
      or batch["review_required"] or batch["operation_result"] is not None
      or batch["maintenance_dispatch"]["state"] != "not_dispatched"
      or any(run["restore"]["mode"] != "manual" for run in batch["plan"]["runs"])
      or any(item["stop_phase"] != "stopped_confirmed"
        or not item["facts"]["exit_confirmed"] or not item["facts"]["resources_released"]
        or item["launch_dispatch"]["state"] != "not_dispatched"
        or item["restore_phase"] not in ("not_requested", "manual") for item in batch["items"])):
    raise ValueError()
  return saved, batch


def _unused_dispatch_id(state, dispatch_id):
  _run_id(dispatch_id)
  for intent in state["intents"].values():
    progress = intent.get("progress")
    if progress is not None and (progress["maintenance_dispatch"]["dispatch_id"] == dispatch_id
        or any(item["launch_dispatch"]["dispatch_id"] == dispatch_id for item in progress["items"])):
      raise ValueError()


def record_setup_dispatch(domain, batch_id, *, expected_revision, workspaces, review, setup_plan_digest):
  """单次持久提交后才发行许可；失败不读回重签、不清保护或重放。

  setup_plan_digest 必须由可信调用方从实际 setup 预览计算。当前为内部接缝，
  maintenance_setup 已连接实际预览；业务 guard 尚未准入，JSON/历史批次不能重建批准和许可。
  """
  try:
    if type(workspaces) is not dict or type(review) is not maintenance_permit.SetupReview:
      raise ValueError()
    selected = dict(workspaces)
    with domain._transaction() as initial:
      saved, batch = _load(domain, initial, batch_id, expected_revision)
    dispatch_id = uuid.uuid4().hex
    with ExitStack() as physical:
      leases = maintenance_release._leases(physical, initial, batch, selected)
      for run in batch["accepted_runs"]:
        check_stop_deployment(selected[run], saved["acceptance"]["records"][run],
          instance_fd=leases[run]["instance_fd"], state_fd=leases[run]["state_fd"])
      # owner 锁持续覆盖协调表 replace/fsync/读回；不持协调锁等待物理锁或用户。
      with ExitStack() as owners, domain._transaction(write=True) as state:
        saved, batch = _load(domain, state, batch_id, expected_revision)
        maintenance_release._hold_released(domain, state, saved, batch, selected, leases, owners)
        _unused_dispatch_id(state, dispatch_id)
        generation = saved["intent"]["generation"]
        maintenance_permit.consume_setup_review(review, batch=batch,
          intent_generation=generation, setup_plan_digest=setup_plan_digest)
        batch["revision"] += 1
        batch["phase"] = "maintenance_dispatch_intent"
        batch["maintenance_dispatch"] = {"state": "dispatch_intent", "dispatch_id": dispatch_id,
          "setup_plan_digest": setup_plan_digest}
        normalized = maintenance.decode_batch(maintenance.encode_batch(batch))
        state["intents"][batch_id]["progress"] = normalized
    # 必须在协调事务完整成功返回后发行；发行失败也不重新接受已保存的派发意图。
    permit = maintenance_permit._issue_batch_permit(normalized,
      intent_generation=generation, setup_plan_digest=setup_plan_digest)
    return SetupDispatchResult(deepcopy(normalized), permit)
  except Exception:
    raise Conflict(_ERROR) from None
