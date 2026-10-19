"""当前管理器的Linux子收割者观察；不启动、调度、终止或恢复任务。"""

from copy import deepcopy
import ctypes
import errno
import os
import signal
import sys
import threading


WALL = 0x40000000
_SCOPE = threading.Lock()


def _prctl(option, value):
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.prctl(option, value, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), "无法核实当前管理器的内核后代观察")


def _get_subreaper():
  value = ctypes.c_int()
  _prctl(37, ctypes.byref(value))
  return value.value


def _set_subreaper(value):
  _prctl(36, ctypes.c_ulong(value))


def _initially_empty():
  # WNOWAIT不收割调用方既有子进程；仅无既有子进程时建立本次完整覆盖。
  try:
    os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT | WALL)
  except ChildProcessError as error:
    return error.errno == errno.ECHILD
  return False


class DescendantScope:
  """必须在spawn前进入；只有内核证明全部子进程消失才返回完整观察。

  子收割者使双fork、setsid等孤儿后代仍由当前管理器接收。没有cgroup、
  额外守护进程或任务协议；不声称约束外部服务或任意同用户进程。
  管理器异常退出或有活动后代时不生成释放证明，旧unknown也不据此清除。
  """

  def __init__(self, manager):
    self.manager = deepcopy(manager)
    self.armed = False
    self.locked = False
    self.previous = None
    self.complete = False

  def __enter__(self):
    if (sys.platform != "linux" or self.manager.get("pid") != os.getpid()
        or threading.active_count() != 1 or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL):
      return self
    self.locked = _SCOPE.acquire(blocking=False)
    if not self.locked:
      return self
    try:
      if not _initially_empty():
        return self
      self.previous = _get_subreaper()
      _set_subreaper(1)
      self.armed = _get_subreaper() == 1
    except (OSError, AttributeError, ValueError):
      self.armed = False
    return self

  def observe(self, run_id):
    from .run_owners import ReleaseObservation, current_process_identity
    if not self.armed:
      return None
    try:
      if (current_process_identity() != self.manager or _get_subreaper() != 1
          or threading.active_count() != 1 or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL):
        return None
      # 有界非阻塞收割；0表示仍有活动子进程，不能由已退出的父替它释放。
      for _ in range(4096):
        try:
          pid, status = os.waitpid(-1, os.WNOHANG | WALL)
        except ChildProcessError as error:
          if error.errno != errno.ECHILD:
            return None
          self.complete = True
          return ReleaseObservation(run_id, deepcopy(self.manager), True, True)
        if pid == 0 or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
          return None
    except (OSError, AttributeError, ValueError):
      return None
    return None

  def __exit__(self, *args):
    try:
      # 只有已经证明无后代时恢复本进程属性；活动/未知时保留观察直至管理器结束。
      if self.complete and self.previous == 0:
        try:
          _set_subreaper(0)
        except OSError:
          pass
    finally:
      if self.locked:
        _SCOPE.release()
