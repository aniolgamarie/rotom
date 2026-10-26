"""Linux 原 manager 的只读退出观察；不提供信号或重新绑定 PID 的能力。"""
from copy import deepcopy
import os
import select
import sys

from . import run_owners
from .storage import Conflict


_ERROR = "原 manager 的退出观察不能确认；保留停止保护"


class ManagerExit:
  """先核对出生身份再捕获 pidfd；后续只读此 fd，观察失败不等于退出。"""

  def __init__(self, identity):
    self._fd = None
    try:
      if sys.platform != "linux" or type(identity) is not dict or set(identity) != {"pid", "birth_id"}:
        raise ValueError()
      identity = deepcopy(run_owners._manager(identity))
      if run_owners.observed_process_identity(identity["pid"]) != identity:
        raise ValueError()
      self._fd = os.pidfd_open(identity["pid"], 0)
      if (type(self._fd) is not int or self._fd < 0 or os.get_inheritable(self._fd)
          or run_owners.observed_process_identity(identity["pid"]) != identity
          or self.exited()):
        raise ValueError()
    except BaseException as error:
      self.close()
      if not isinstance(error, Exception):
        raise
      raise Conflict(_ERROR) from None

  def exited(self):
    try:
      if self._fd is None:
        raise ValueError()
      poller = select.poll()
      poller.register(self._fd, select.POLLIN | select.POLLERR | select.POLLHUP)
      events = poller.poll(0)
      if not events:
        return False
      if (len(events) != 1 or events[0][0] != self._fd
          or not events[0][1] & select.POLLIN
          or events[0][1] & ~(select.POLLIN | select.POLLHUP)):
        raise ValueError()
      return True
    except Exception:
      raise Conflict(_ERROR) from None

  def close(self):
    fd, self._fd = self._fd, None
    if type(fd) is int and fd >= 0:
      try:
        os.close(fd)
      except OSError:
        pass

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    self.close()
