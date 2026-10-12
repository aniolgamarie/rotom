"""专用 controller 的 fd3 预留；不授予来源、初始化或 storage 资格。"""

from dataclasses import dataclass
import errno
import fcntl
import os
import stat
import threading


class ControllerSlotError(Exception):
  code = "PI_CONTROLLER_SLOT_INVALID"
  exit_code = 4

  def __init__(self):
    super().__init__(self.code)


def _reject():
  # 清除调用方的当前异常，不保留 syscall 的正文或 foreign 链。
  error = ControllerSlotError()
  try:
    raise error
  except ControllerSlotError:
    error.__cause__ = None
    error.__context__ = None
    raise


@dataclass(slots=True)
class _Record:
  receiver: object
  fd: int
  fstat: object
  open: object
  close: object
  fcntl: object
  current_thread: object
  main_thread: object
  thread: object
  metadata: tuple
  status_flags: int
  fd_flags: int
  retired: bool = False


# 强引用原 receiver，避免 id 重用使手工对象获得登记资格。
_records = {}


def _metadata(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_rdev)


def _registered(receiver):
  record = _records.get(id(receiver))
  if type(receiver) is not ControllerSlot or record is None or record.receiver is not receiver:
    raise ValueError()
  if record.retired:
    raise ValueError()
  if record.current_thread() is not record.thread or record.main_thread() is not record.thread:
    raise ValueError()
  return record


def _held(record):
  if _metadata(record.fstat(record.fd)) != record.metadata:
    raise ValueError()
  if record.fcntl(record.fd, fcntl.F_GETFL) != record.status_flags:
    raise ValueError()
  if record.fcntl(record.fd, fcntl.F_GETFD) != record.fd_flags:
    raise ValueError()


class ControllerSlot:
  """仅 reserve 登记的原对象有效；没有 DTO、fd 或公开构造入口。"""

  __slots__ = ()

  def __new__(cls, *args, **kwargs):
    _reject()

  def __reduce_ex__(self, protocol):
    _reject()

  def check(self):
    failed = False
    try:
      record = _registered(self)
      _held(record)
      if record.retired:
        raise ValueError()
    except BaseException:
      failed = True
    if failed:
      _reject()

  def close(self):
    failed = False
    try:
      record = _registered(self)
      # 先退休；核失败或 close 失败都不得再次使用或重试。
      record.retired = True
      _held(record)
      record.close(record.fd)
    except BaseException:
      failed = True
    if failed:
      _reject()


def reserve_controller_slot():
  """主线程以原方法预留自身 fd3；唯一业务 open 是固定 /dev/null。"""
  owned = None
  record = None
  original_close = None
  failed = False
  try:
    original_fstat = os.fstat
    original_open = os.open
    original_close = os.close
    original_fcntl = fcntl.fcntl
    original_current = threading.current_thread
    original_main = threading.main_thread
    thread = original_current()
    if thread is not original_main():
      raise ValueError()
    vacant = False
    try:
      original_fstat(3)
    except OSError as error:
      vacant = error.errno == errno.EBADF
    if not vacant:
      raise ValueError()
    owned = original_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    if type(owned) is not int or owned != 3:
      raise ValueError()
    info = original_fstat(owned)
    if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 1 or os.minor(info.st_rdev) != 3:
      raise ValueError()
    status_flags = original_fcntl(owned, fcntl.F_GETFL)
    fd_flags = original_fcntl(owned, fcntl.F_GETFD)
    if status_flags & os.O_ACCMODE != os.O_RDONLY or not fd_flags & fcntl.FD_CLOEXEC:
      raise ValueError()
    slot = object.__new__(ControllerSlot)
    record = _Record(slot, owned, original_fstat, original_open, original_close,
      original_fcntl, original_current, original_main, thread, _metadata(info), status_flags, fd_flags)
    _records[id(slot)] = record
  except BaseException:
    failed = True
  if failed:
    # 登记后捕获到中断时，原对象也须先失效，不能在 cleanup 中再使用。
    if record is not None:
      record.retired = True
    # 只清理本次原 open 返回值；close 异常也绝不重试。
    if owned is not None:
      try:
        original_close(owned)
      except BaseException:
        pass
    _reject()
  return slot
