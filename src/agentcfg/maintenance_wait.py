"""内部共享释放等待；不操作宿主、不创建预算或授予维护许可。"""
from copy import deepcopy
from dataclasses import dataclass
import math
import re
import time

from .control_deadline import ControlDeadline
from .run_owners import ReleaseObservation, _encode, _manager
from .storage import Conflict


_ERROR = "释放等待参数或目标身份不能确认；保留现有保护"


@dataclass(frozen=True)
class ReleaseWaitResult:
  """confirmed 仅表示本轮同身份完整观察已由 record 保存，不证明 SH 已释放。

  不等于 stopped_confirmed/resources_released 或维护许可。
  """

  confirmed_runs: tuple[str, ...]
  pending_runs: tuple[str, ...]
  exit_code: int
  reason: str | None


def _proof_matches(proof, run, manager):
  try:
    return (type(proof) is ReleaseObservation and type(proof.run_id) is str
      and proof.run_id == run and proof.complete is True and proof.all_related_exited is True
      and _encode(_manager(proof.manager_identity)) == _encode(manager))
  except Exception:
    return False


def wait_for_release(targets, *, deadline, observe, record, sleep=time.sleep, interval=0.05):
  """调用方另核实意图、观察来源/时效及物理 EX 门禁，不据此推导锁释放。

  observe 必须可信且非阻塞；record 可能 fsync 超期，本循环不提供硬实时中断。
  """
  try:
    if (type(targets) is not dict or not 1 <= len(targets) <= 1024
        or type(deadline) is not ControlDeadline or not all(callable(fn) for fn in (observe, record, sleep))
        or type(interval) not in (int, float) or not math.isfinite(interval) or not 0 < interval <= 1
        or any(type(run) is not str or re.fullmatch(r"[0-9a-f]{32}", run) is None for run in targets)):
      raise ValueError()
    managers = {run: _manager(targets[run]) for run in sorted(targets)}
  except Exception:
    raise Conflict(_ERROR) from None
  pending, confirmed = set(managers), set()

  def result(reason=None):
    return ReleaseWaitResult(tuple(sorted(confirmed)), tuple(sorted(pending)), 4 if reason else 0, reason)

  def remaining():
    try:
      return deadline.remaining()
    except Exception:
      return None

  while pending:
    for run in sorted(pending):
      left = remaining()
      if left is None:
        return result("clock-unconfirmed")
      if left == 0:
        return result("deadline-expired")
      try:
        proof = observe(run, deepcopy(managers[run]))
      except Exception:
        return result("observation-unconfirmed")
      if _proof_matches(proof, run, managers[run]):
        try:
          record(deepcopy(proof))
        except Exception:
          # 回包丢失也不重试；只有明确返回成功的事实加入 confirmed。
          return result("record-unconfirmed")
        pending.remove(run)
        confirmed.add(run)
      # 即使观察期间到期，仍先保存可信事实；到期绝不允许继续维护。
      left = remaining()
      if left is None:
        return result("clock-unconfirmed")
      if left == 0:
        return result("deadline-expired")
    if pending:
      left = remaining()
      if left is None:
        return result("clock-unconfirmed")
      if left == 0:
        return result("deadline-expired")
      try:
        sleep(min(interval, left))
      except Exception:
        return result("wait-unconfirmed")
  return result()
