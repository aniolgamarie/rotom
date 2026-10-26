"""实际 setup 只读预览的独立审阅与派发记账；不执行 setup 或消费许可。"""
from copy import deepcopy
import sys

from . import commands, maintenance_dispatch, maintenance_permit
from .setup_preview import setup_plan_digest
from .storage import Conflict


_ERROR = "维护 setup 预览与原批次目标不能确认；保留保护，不执行 setup"


def _check_target(state, batch, workspace, plan):
  scope = {"agent": workspace.agent, **workspace.binding}
  if any(run["scope"] != scope for run in batch["plan"]["runs"]):
    raise ValueError()
  resources = {item["resource_id"]: item for item in batch["plan"]["resources"]}
  for rid, planned in resources.items():
    actual = state["resources"][rid]
    if actual["resource_id"] != rid or actual["key"] != planned["key"]:
      raise ValueError()
  launch = plan.current["launch"]
  runtime = launch.get("runtime_identity", launch.get("lock_identity"))
  for run in batch["plan"]["runs"]:
    entry = state["reservations"][run["run_id"]]
    if (entry["resources"] != run["resource_ids"]
        or entry["owner_ref"] != {"state_root": str(workspace.state_root), "binding": workspace.binding}):
      raise ValueError()
    selected = [state["resources"][rid] for rid in entry["resources"]]
    if any(item["resource_id"] not in resources for item in selected):
      raise ValueError()
    kinds = {kind: [item for item in selected if item["key"]["kind"] == kind]
      for kind in ("runtime", "instance", "native-home")}
    if any(len(items) != 1 for items in kinds.values()) or len(selected) != 3:
      raise ValueError()
    package = kinds["runtime"][0]
    if package["runtime_identity"] != runtime or package["cache"] != str(workspace.cache):
      raise ValueError()
    if (kinds["instance"][0]["path"] != str(workspace.instance / ".agentcfg-omp.lock")
        or kinds["native-home"][0]["path"] != str(workspace.instance / "user-home")):
      raise ValueError()


def review_and_dispatch_setup(domain, batch_id, *, expected_revision, args, approve) -> maintenance_dispatch.SetupDispatchResult:
  """无锁处独立批准实际预览；原 dispatch 事务负责现场复核和单次提交。

  仅支持 Linux OMP 同一显式 local/profile 的原包和缓存。当前接缝不会调用
  setup、sync、apply 或任何许可消费门禁，也不会依据历史路径打开工作区。
  """
  # 沿用普通只读准备路径及其原有错误契约，不将配置或依赖错误改成维护冲突。
  workspace, lock, candidate = commands.prepared(args)
  plan = commands.current_plan(workspace, lock, candidate)
  try:
    if (sys.platform != "linux" or workspace.agent != "omp"
        or not getattr(args, "local", None) or type(getattr(args, "profile", None)) is not str
        or not args.profile or args.profile != workspace.profile or plan.conflicts or plan.drift
        or not callable(approve)):
      raise ValueError()
    digest = setup_plan_digest(workspace, lock, candidate, plan)
    summary = deepcopy(plan.public())
    with domain._transaction() as state:
      saved, batch = maintenance_dispatch._load(domain, state, batch_id, expected_revision)
      _check_target(state, batch, workspace, plan)
      generation = saved["intent"]["generation"]
      selected = {run: workspace for run in batch["accepted_runs"]}
  except Exception:
    raise Conflict(_ERROR) from None

  def show(view):
    view["setup_preview"] = deepcopy(summary)
    return approve(view)

  # 不在验证包装或任何物理、协调、owner 锁内调用用户代码；取消和异常原样传播。
  review = maintenance_permit.review_setup(batch, intent_generation=generation,
    setup_plan_digest=digest, approve=show)
  return maintenance_dispatch.record_setup_dispatch(domain, batch_id, expected_revision=expected_revision,
    workspaces=selected, review=review, setup_plan_digest=digest)
