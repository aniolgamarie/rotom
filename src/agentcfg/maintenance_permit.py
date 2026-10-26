"""内部 setup 审阅和提交后单次内存许可；不证明现场或旁路原 guard。

停止批准不能充当 setup 批准。未来调用方必须在原首个副作用 guard 内完成物理、
部署及 intent 核验后消费许可；此模块不读现场、不持久化或执行 setup。
"""
from copy import deepcopy
import os
import re
import threading

from . import maintenance
from .storage import Conflict


_ERROR = "setup 的显式审阅、原批次绑定或单次许可不能确认"
_REVIEW_TOKEN = object()
_PERMIT_TOKEN = object()


def _normalized(batch, generation, digest, *, issued):
  if (type(generation) is not int or not 0 <= generation <= 2**64 - 1
      or type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
    raise ValueError()
  value = maintenance.decode_batch(maintenance.encode_batch(batch))
  dispatch = value["maintenance_dispatch"]
  if (value["operation"] != "setup" or value["review_required"] is not False
      or value["operation_result"] is not None
      or value["phase"] != ("maintenance_dispatch_intent" if issued else "stopped_confirmed")
      or dispatch["state"] != ("dispatch_intent" if issued else "not_dispatched")
      or any(run["restore"]["mode"] != "manual" for run in value["plan"]["runs"])
      or any(item["stop_phase"] != "stopped_confirmed"
        or item["facts"]["exit_confirmed"] is not True or item["facts"]["resources_released"] is not True
        or item["restore_phase"] not in ("not_requested", "manual")
        or item["launch_dispatch"]["state"] != "not_dispatched" for item in value["items"])):
    raise ValueError()
  if issued:
    if dispatch["dispatch_id"] is None or dispatch.get("setup_plan_digest") != digest:
      raise ValueError()
  elif dispatch["dispatch_id"] is not None or "setup_plan_digest" in dispatch:
    raise ValueError()
  return value, maintenance.encode_batch(value)


class SetupReview:
  """完整 setup 审阅请求绑定到本进程；不是停止批准或现场资源证明。"""

  __slots__ = ("_canonical", "_generation", "_digest", "_pid", "_used", "_lock")

  def __init__(self, token, canonical, generation, digest):
    if token is not _REVIEW_TOKEN:
      raise Conflict(_ERROR)
    object.__setattr__(self, "_canonical", canonical)
    object.__setattr__(self, "_generation", generation)
    object.__setattr__(self, "_digest", digest)
    object.__setattr__(self, "_pid", os.getpid())
    object.__setattr__(self, "_used", False)
    object.__setattr__(self, "_lock", threading.Lock())

  def __setattr__(self, name, value):
    raise Conflict(_ERROR)

  def __delattr__(self, name):
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


class BatchPermit:
  """仅由可信调用方确认原持久提交明确成功后发行；不代替任何副作用 guard。"""

  __slots__ = ("_canonical", "_generation", "_digest", "_pid", "_used", "_lock")

  def __init__(self, token, canonical, generation, digest):
    if token is not _PERMIT_TOKEN:
      raise Conflict(_ERROR)
    object.__setattr__(self, "_canonical", canonical)
    object.__setattr__(self, "_generation", generation)
    object.__setattr__(self, "_digest", digest)
    object.__setattr__(self, "_pid", os.getpid())
    object.__setattr__(self, "_used", False)
    object.__setattr__(self, "_lock", threading.Lock())

  def __setattr__(self, name, value):
    raise Conflict(_ERROR)

  def __delattr__(self, name):
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


def review_setup(batch, *, intent_generation, setup_plan_digest, approve) -> SetupReview:
  """可信调用方选择交互策略；回调在任何内存锁外，只接受精确 True。"""
  try:
    value, canonical = _normalized(batch, intent_generation, setup_plan_digest, issued=False)
    if not callable(approve):
      raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None
  if approve({"batch": deepcopy(value), "intent_generation": intent_generation,
      "setup_plan_digest": setup_plan_digest}) is not True:
    raise Conflict(_ERROR)
  try:
    return SetupReview(_REVIEW_TOKEN, canonical, intent_generation, setup_plan_digest)
  except Exception:
    raise Conflict(_ERROR) from None


def _issue_batch_permit(batch, *, intent_generation, setup_plan_digest) -> BatchPermit:
  """只绑定明确提交后的完整批次；调用方负责 durable commit，未知响应不得发行。"""
  try:
    _, canonical = _normalized(batch, intent_generation, setup_plan_digest, issued=True)
    return BatchPermit(_PERMIT_TOKEN, canonical, intent_generation, setup_plan_digest)
  except Exception:
    raise Conflict(_ERROR) from None


def _consume(value, expected_type, batch, generation, digest):
  locked = False
  try:
    if type(value) is not expected_type:
      raise ValueError()
    _, canonical = _normalized(batch, generation, digest, issued=expected_type is BatchPermit)
    locked = value._lock.acquire(blocking=False)
    if not locked:
      raise ValueError()
    if (value._used or value._pid != os.getpid() or value._canonical != canonical
        or value._generation != generation or value._digest != digest):
      raise ValueError()
    object.__setattr__(value, "_used", True)
  except Exception:
    raise Conflict(_ERROR) from None
  finally:
    if locked:
      value._lock.release()


def consume_setup_review(review, *, batch, intent_generation, setup_plan_digest) -> None:
  """精确绑定后立即单次消费；后续写入失败不恢复本次 setup 批准。"""
  _consume(review, SetupReview, batch, intent_generation, setup_plan_digest)


def consume_batch_permit(permit, *, batch, intent_generation, setup_plan_digest) -> None:
  """仅原副作用 guard 完成现场核验后调用；本函数自己不核验现场或持久状态。"""
  _consume(permit, BatchPermit, batch, intent_generation, setup_plan_digest)
