"""Linux 单线程启动现场的直接子进程绑定；候选终止原语不授予停止批准。"""
import os
from pathlib import Path
import select
import signal
import sys
import threading
import uuid

from .run_owners import current_process_identity
from .storage import Conflict


_ERROR = "本次启动的直接子进程身份不能确认；不提供控制句柄"
_SIGNAL_ERROR = "本次宿主终止请求不能确认；保留事实且不重发"
_TOKEN = object()


def _conditions(child, manager, pid):
  if (sys.platform != "linux" or threading.active_count() != 1
      or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL
      or type(manager) is not dict or set(manager) != {"pid", "birth_id"}
      or type(manager["pid"]) is not int or manager["pid"] <= 0
      or type(manager["birth_id"]) is not str or not manager["birth_id"]
      or manager != current_process_identity()
      or type(pid) is not int or pid <= 0 or pid == manager["pid"]
      or type(child.pid) is not int or child.pid != pid or child.returncode is not None):
    raise ValueError()


def _sample(pid, manager):
  boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
  if str(uuid.UUID(boot)) != boot or not manager["birth_id"].startswith("linux:" + boot + ":"):
    raise ValueError()
  prefix, separator, tail = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rpartition(")")
  fields = tail.split()
  if (not separator or int(prefix.split("(", 1)[0].strip()) != pid
      or fields[0] in {"Z", "X", "x"} or len(fields[0]) != 1
      or int(fields[1]) != manager["pid"] or not fields[19].isdecimal()
      or int(fields[19]) <= 0):
    raise ValueError()
  return {"pid": pid, "birth_id": "linux:" + boot + ":" + fields[19]}


def _quiet(fd):
  observer = select.poll()
  observer.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
  if observer.poll(0):
    raise ValueError()


def _verify(child, manager, pid, fd):
  _conditions(child, manager, pid)
  if type(fd) is not int or fd < 0 or os.get_inheritable(fd) is not False:
    raise ValueError()
  _quiet(fd)
  first = _sample(pid, manager)
  _conditions(child, manager, pid)
  _quiet(fd)
  second = _sample(pid, manager)
  _quiet(fd)
  _conditions(child, manager, pid)
  if first != second:
    raise ValueError()
  return second


class SpawnedHost:
  """仅 capture 创建；自有 pidfd 不可复制，观察与显式单次终止分开调用。"""

  def __init__(self, token, child, manager, pid, fd, identity):
    if token is not _TOKEN:
      raise Conflict(_ERROR)
    self._child, self._manager, self._pid = child, dict(manager), pid
    self._fd, self._identity = fd, dict(identity)
    self._termination_attempted = False

  def __copy__(self):
    return self

  def __deepcopy__(self, memo):
    return self

  def __reduce_ex__(self, protocol):
    raise TypeError("宿主句柄不能序列化")

  def snapshot(self):
    try:
      if self._fd is None:
        raise ValueError()
      identity = _verify(self._child, self._manager, self._pid, self._fd)
      if identity != self._identity:
        raise ValueError()
      return {"identity": dict(identity), "manager_identity": dict(self._manager),
        "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
    except BaseException as error:
      # 不让关闭失败覆盖原控制中断；任何不确定均永久放弃本句柄。
      try:
        self.close()
      except BaseException:
        pass
      if not isinstance(error, Exception):
        raise
      raise Conflict(_ERROR) from None

  def close(self):
    fd, self._fd, self._child = self._fd, None, None
    if fd is not None:
      try:
        os.close(fd)
      except OSError:
        pass

  def send_sigterm_once(self):
    """候选内部通道：调用者须先核验批准并持久化意图；返回不证明宿主或后代退出。

    只向捕获时的 pidfd 发 SIGTERM。未经工具/版本原生验收不得接入日常路径；
    不按 PID 重开、不降级 kill、不等待、不升级强杀，也不提供一般信号参数。
    """
    try:
      if self._termination_attempted:
        raise ValueError()
      # 先消费再核验/调用；中断、API 缺失或响应丢失均不能恢复发送资格。
      self._termination_attempted = True
      self.snapshot()
      if signal.pidfd_send_signal(self._fd, signal.SIGTERM, None, 0) is not None:
        raise ValueError()
    except Exception:
      raise Conflict(_SIGNAL_ERROR) from None

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    try:
      self.close()
    except BaseException:
      # 前台已有异常时，附属关闭不能覆盖原结果；fd 已先从对象撤销。
      if exc[0] is None:
        raise


def capture_spawned_host(child, manager_identity):
  """仅本次未 wait 的 Popen 后立即调用；不支持并发 reaper 或自定义 SIGCHLD。"""
  fd = None
  try:
    pid = child.pid
    _conditions(child, manager_identity, pid)
    manager = dict(manager_identity)
    fd = os.pidfd_open(pid, 0)
    identity = _verify(child, manager, pid, fd)
    return SpawnedHost(_TOKEN, child, manager, pid, fd, identity)
  except BaseException as error:
    if type(fd) is int and fd >= 0:
      try:
        os.close(fd)
      except BaseException:
        pass
    if not isinstance(error, Exception):
      raise
    return None
