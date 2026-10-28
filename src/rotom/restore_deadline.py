"""恢复 ready/handoff 的共享绝对预算；不约束已交接宿主。"""
import time

from agentcfg.control_deadline import ControlDeadline
from agentcfg.storage import Conflict
from termcfg.errors import TermcfgError


def _timeout():
  return TermcfgError(4, "restore_ready_timeout", "rotom resume --stopped --list")


class ReadyDeadline:
  def __init__(self, wait_seconds=30, *, clock=None):
    source = time.monotonic if clock is None else clock
    def read():
      self._now = source()
      return self._now
    try:
      self._control = ControlDeadline(wait_seconds, clock=read)
    except Conflict:
      raise _timeout() from None
    self._deadline_ns = self._control.deadline_ns

  @classmethod
  def from_expires_at_ns(cls, expires_at_ns, *, clock=None):
    deadline = cls(300, clock=clock)
    deadline._deadline_ns = min(deadline.deadline_ns, expires_at_ns)
    deadline.remaining()
    return deadline

  @property
  def expires_at(self):
    return self.deadline_ns / 1_000_000_000

  @property
  def deadline_ns(self):
    return self._deadline_ns

  def _remaining(self):
    try:
      left = self._control.remaining()
    except Conflict:
      raise _timeout() from None
    return min(left, max(0, self.expires_at - self._now))

  @property
  def expired(self):
    return self._remaining() == 0

  def remaining(self, limit=None):
    left = self._remaining()
    if left <= 0:
      raise _timeout()
    return min(left, limit) if limit is not None else left
