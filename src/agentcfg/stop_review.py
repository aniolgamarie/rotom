"""停止专属内存审阅；不是控制、资源证明、setup 批准或维护许可。"""
from copy import deepcopy
import os
import re
import threading

from . import maintenance
from .storage import Conflict


_ERROR = "停止计划的显式审阅或单次消费不能确认"
_TOKEN = object()


def _batch(value):
  if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
    raise ValueError()


def _normalized(plan):
  value = maintenance.decode_stop_plan(maintenance.encode_stop_plan(plan))
  if value["readiness"] != "ready":
    raise ValueError()
  return value, maintenance.encode_stop_plan(value)


class StopReview:
  """只绑定完整计划、批次及发行进程；不提供任何现场控制能力。"""

  __slots__ = ("_canonical", "_batch_id", "_pid", "_used", "_lock")

  def __init__(self, token, canonical, batch_id):
    if token is not _TOKEN:
      raise Conflict(_ERROR)
    object.__setattr__(self, "_canonical", canonical)
    object.__setattr__(self, "_batch_id", batch_id)
    object.__setattr__(self, "_pid", os.getpid())
    object.__setattr__(self, "_used", False)
    object.__setattr__(self, "_lock", threading.Lock())

  def __setattr__(self, name, value):
    raise Conflict(_ERROR)

  def __copy__(self):
    return self

  def __deepcopy__(self, memo):
    memo[id(self)] = self
    return self

  def __reduce__(self):
    raise Conflict(_ERROR)

  def __reduce_ex__(self, protocol):
    raise Conflict(_ERROR)


def review_stop_plan(plan, *, scope, operation, selected_runs, plan_id, batch_id, approve) -> StopReview:
  """可信调用方先决定交互策略；仅精确 True 表示本次显式审阅完成。"""
  try:
    normalized, canonical = _normalized(plan)
    _batch(batch_id)
    if (type(scope) is not dict or scope != normalized["scope"]
        or type(operation) is not str or operation != normalized["operation"]
        or type(selected_runs) is not list or not selected_runs
        or any(type(run) is not str or re.fullmatch(r"[0-9a-f]{32}", run) is None for run in selected_runs)
        or len(set(selected_runs)) != len(selected_runs)
        or set(selected_runs) != set(normalized["selected_runs"])
        or type(plan_id) is not str or re.fullmatch(r"[0-9a-f]{64}", plan_id) is None
        or plan_id != normalized["plan_id"] or not callable(approve)):
      raise ValueError()
    # schema 和路径规则均沿用 codec，不补配方默认值。
    maintenance._validate(scope, "scope")
    maintenance._scope(scope)
  except Exception:
    raise Conflict(_ERROR) from None
  # 回调异常（包括 InputGateway 取消）保持原样，不改写成校验错误。
  if approve(deepcopy(normalized)) is not True:
    raise Conflict(_ERROR)
  return StopReview(_TOKEN, canonical, batch_id)


def consume_stop_review(review, *, plan, batch_id) -> None:
  """短内存锁下单次消费；后续事务/响应失败不得恢复本对象。"""
  locked = False
  try:
    if type(review) is not StopReview:
      raise ValueError()
    _batch(batch_id)
    _, canonical = _normalized(plan)
    locked = review._lock.acquire(blocking=False)
    if not locked:
      raise ValueError()
    if (review._used or review._pid != os.getpid() or review._batch_id != batch_id
        or review._canonical != canonical):
      raise ValueError()
    object.__setattr__(review, "_used", True)
  except Exception:
    raise Conflict(_ERROR) from None
  finally:
    if locked:
      review._lock.release()
