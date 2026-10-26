"""内部阶段共享绝对预算；不执行停止、观察、清理或任何宿主动作。"""
import math
import time

from .storage import Conflict


_ERROR = "阶段时钟或截止预算不能确认；保留现有保护"


class ControlDeadline:
  """每个 stop/ready 阶段由可信调用方分别构造；同阶段各项共享此对象。"""

  def __init__(self, wait_seconds=30, *, clock=None):
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 300:
      raise ValueError("invalid-control-wait")
    self._clock = time.monotonic if clock is None else clock
    if not callable(self._clock):
      raise Conflict(_ERROR)
    self._last = None
    start = self._read()
    self._deadline = start + wait_seconds
    try:
      if not math.isfinite(self._deadline) or self._deadline <= start:
        raise ValueError()
    except Exception:
      raise Conflict(_ERROR) from None
    self._remaining = wait_seconds

  def _read(self):
    try:
      now = self._clock()
      if (type(now) not in (int, float) or not math.isfinite(now)
          or self._last is not None and now < self._last):
        raise ValueError()
    except Exception:
      raise Conflict(_ERROR) from None
    self._last = now
    return now

  def remaining(self):
    now = self._read()
    # 仅收紧剩余预算；轮询及逐项处理都不能重设绝对截止时间。
    try:
      left = self._deadline - now
      if not math.isfinite(left):
        raise ValueError()
    except Exception:
      raise Conflict(_ERROR) from None
    self._remaining = min(self._remaining, max(0, left))
    return self._remaining

  def expired(self):
    return self.remaining() == 0

  @property
  def deadline_ns(self):
    """同阶段 IPC 使用同一绝对单调截止点，取整只收紧预算。"""
    return int(self._deadline * 1000000000)
