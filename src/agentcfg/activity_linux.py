"""Linux 进程身份与显式停止；系统调用均可注入，默认测试不发真实信号。"""

import os
from pathlib import Path
import signal
import time

from .pi_catalog import validate
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict
from .process_tracking import TrackedProcesses


class LinuxProcesses(TrackedProcesses):
  def __init__(self, record_root, *, proc_root=Path("/proc"), send_signal=None, clock=None, pause=None):
    super().__init__(record_root)
    self.proc_root = Path(proc_root)
    self.send_signal = send_signal or self._pidfd_signal
    self.clock, self.pause = clock or time.monotonic, pause or time.sleep

  def identity(self, pid):
    directory = self.proc_root / str(pid)
    raw = (directory / "stat").read_text()
    tail = raw[raw.rfind(")") + 2:].split()
    if len(tail) < 20 or not raw.startswith(str(pid) + " ("):
      raise Conflict("Linux进程身份不可解析")
    value = {"platform": "linux", "boot_id": (self.proc_root / "sys/kernel/random/boot_id").read_text().strip(),
      "pid": pid, "ppid": int(tail[1]), "pgid": int(tail[2]), "start_time": str(int(tail[19])),
      "namespace": os.readlink(directory / "ns/pid"), "uid": directory.stat().st_uid}
    if (directory / "stat").read_text().split(")")[-1].split()[19] != value["start_time"]:
      raise Conflict("读取期间Linux进程身份已改变")
    validate("process-identity", value)
    return value

  def observe(self, expected):
    try:
      actual = self.identity(expected["pid"])
    except FileNotFoundError:
      return "dead" if not (self.proc_root / str(expected["pid"])).exists() else "unknown"
    except (OSError, ValueError, Conflict, ConfigError):
      return "unknown"
    # PPID 会在父进程退出后改变，不属于开始身份；其他边界必须保持。
    return "alive" if all(actual[key] == expected[key] for key in expected if key != "ppid") else "unknown"


  def _scan(self):
    result = {}
    for path in self.proc_root.iterdir():
      if not path.name.isdecimal():
        continue
      try:
        uid = path.stat().st_uid
        # 其他用户只读取父进程/进程组编号，防止把混入组的未知成员漏记成已清零。
        if uid != os.geteuid():
          raw = (path / "stat").read_text()
          tail = raw[raw.rfind(")") + 2:].split()
          result[path.name] = {"pid": int(path.name), "ppid": int(tail[1]), "pgid": int(tail[2]), "uid": uid}
          continue
        try:
          result[path.name] = self.identity(int(path.name))
        except PermissionError:
          # 同用户的无关 nondumpable 进程不能阻断整个扫描；包含关系仍可从 stat 判断。
          raw = (path / "stat").read_text()
          tail = raw[raw.rfind(")") + 2:].split()
          result[path.name] = {"pid": int(path.name), "ppid": int(tail[1]), "pgid": int(tail[2]), "uid": uid}
      except FileNotFoundError:
        continue
    return result


  def _pidfd_signal(self, expected, number):
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
      raise DependencyError("Linux监督需要pidfd身份信号支持")
    try:
      fd = os.pidfd_open(expected["pid"], 0)
    except ProcessLookupError:
      return
    try:
      if self.observe(expected) != "alive":
        raise Conflict("信号发送前进程身份已变化")
      signal.pidfd_send_signal(fd, number)
    finally:
      os.close(fd)

  def register_namespace(self, expected, wrapper):
    from .pi_pid_namespace import register_namespace
    register_namespace(self, expected, wrapper)

  def termination_status(self, expected):
    from .pi_pid_namespace import namespace_record, namespace_status
    try:
      record = namespace_record(self, expected)
      if record is not None: return namespace_status(self, expected, record)
    except (OSError, ValueError, Conflict, ConfigError): return "unknown"
    return super().termination_status(expected)

  def stop(self, expected, *, grace_seconds=2, grant_generation=None, force=False):
    if type(force) is not bool: raise Conflict("停止模式无效")
    from .pi_pid_namespace import namespace_record, stop_namespace
    scope = namespace_record(self, expected)
    if scope is not None:
      return stop_namespace(self, expected, scope, grace_seconds=grace_seconds)
    for number in ((signal.SIGKILL,) if force else (signal.SIGTERM, signal.SIGKILL)):
      record = self._refresh(expected)
      if record["escaped"]:
        raise Conflict("执行包含未知或脱离进程组的工作；停止保护保持生效")
      # pidfd 逐个指向核实的内核进程对象，不对可能复用的裸PGID盲发信号。
      for member in reversed(list(record["members"].values())):
        status = self.observe(member)
        if status == "unknown":
          raise Conflict("停止目标身份未知")
        if status == "alive":
          self.send_signal(member, number)
      deadline = self.clock() + grace_seconds
      while self.clock() < deadline:
        status = self.termination_status(expected)
        if status == "terminated":
          return
        # 退出期间/proc的namespace链接可能先消失；仅继续观察，不向未知身份追加信号。
        self.pause(min(0.05, max(0, deadline - self.clock())))
    if self.termination_status(expected) != "terminated":
      raise Conflict("TERM/KILL后仍有活动；不得回收执行租约")

  def external_status(self, identifier):
    # 外部CLI/工具必须另行登记可验证身份；名字本身不能成为终止证据。
    return "unknown"
