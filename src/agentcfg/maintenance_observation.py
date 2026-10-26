"""维护 setup 的只读现场观察；不恢复 journal、不推进结果或解除保护。"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
import sys

from . import commands, deployment, maintenance, maintenance_progress, maintenance_release, runtime
from .omp_lifecycle import _same_file
from .setup_preview import setup_deployment_digest
from .storage import Conflict, Tree


_ERROR = "维护 setup 观察的批次或明确目标不能确认；未修改现场"


@dataclass(frozen=True)
class SetupObservation:
  """返回前锁已释放；匹配只指 manifest 与受保护投影，不证明历史执行成功。"""

  batch: dict
  target_state: str
  resources_checked: bool
  pending_journal: bool | None
  reason: str | None = None


def _load(domain, state, batch_id, expected_revision, canonical=None):
  saved, batch = maintenance_progress._load(domain, state, batch_id)
  if (type(expected_revision) is not int or batch["revision"] != expected_revision
      or batch["operation"] != "setup"
      or canonical is not None and maintenance.encode_batch(batch) != canonical):
    raise Conflict(_ERROR)
  return saved, batch


def _scope(args, workspace, batch):
  if (sys.platform != "linux" or workspace.agent != "omp" or not getattr(args, "local", None)
      or type(getattr(args, "profile", None)) is not str or not args.profile
      or args.profile != workspace.profile
      or any(item["scope"] != {"agent": workspace.agent, **workspace.binding} for item in batch["plan"]["runs"])):
    raise Conflict(_ERROR)


def _read_target(workspace, target_digest, state_fd):
  """借入原物理租约读取目标；调用方另在前后核验全部资源，不授予许可。"""
  with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
    _same_file(state, "instance.lock", state_fd)
    pending = state.read("pending.json") is not None
    if pending:
      target_state = "journal-pending"
    else:
      saved = deployment.read_state(state)
      current = saved["current"]
      matches = (current is not None and current["binding"] == workspace.binding
        and saved["owner"]["binding"] == workspace.binding
        and setup_deployment_digest(current) == target_digest)
      if matches:
        runtime.check_deployed_resources(current, target)
      target_state = "target-matches" if matches else "target-differs"
    _same_file(state, "instance.lock", state_fd)
  return target_state, pending


def observe_setup(domain, batch_id, *, expected_revision, args) -> SetupObservation:
  """仅按本次显式配置定位同 scope 完整批次；不沿历史路径查其它实例。

  缺目标摘要保留历史可读；物理锁、owner、共享引用或并发状态不能确认时只报告
  unconfirmed，不清 unknown、不重试或创建资源。结果不是执行/恢复/取消许可。
  """
  try:
    with domain._transaction() as initial:
      _, batch = _load(domain, initial, batch_id, expected_revision)
    canonical = maintenance.encode_batch(batch)
  except Exception:
    raise Conflict(_ERROR) from None
  # 保留普通只读配置解析的原错误契约；不渲染候选、读秘密或选择历史包路径。
  workspace = commands.workspace(args)
  _scope(args, workspace, batch)
  target_digest = batch["maintenance_dispatch"].get("target_deployment_digest")
  if target_digest is None:
    return SetupObservation(deepcopy(batch), "target-unavailable", False, None, "no-saved-target")
  selected = {run: workspace for run in batch["accepted_runs"]}
  try:
    with ExitStack() as physical:
      leases = maintenance_release._leases(physical, initial, batch, selected)

      def check():
        # 物理 EX → Domain → owner NB；不在元数据锁内读部署内容。
        with ExitStack() as owners, domain._transaction() as state:
          saved, current = _load(domain, state, batch_id, expected_revision, canonical)
          maintenance_release._hold_released(domain, state, saved, current, selected, leases, owners)

      check()
      state_fd = leases[batch["accepted_runs"][0]]["state_fd"]
      target_state, pending = _read_target(workspace, target_digest, state_fd)
      check()
    return SetupObservation(deepcopy(batch), target_state, True, pending)
  except Exception:
    return SetupObservation(deepcopy(batch), "unconfirmed", False, None, "live-state-unconfirmed")
