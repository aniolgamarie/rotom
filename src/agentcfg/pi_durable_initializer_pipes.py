"""本进程初始化双 pipe 创建与关闭；不授予来源或 child 资格。"""

from dataclasses import dataclass, field
import fcntl
import os
import stat
import threading


class InitializerPipesError(Exception):
  code = "PI_INITIALIZER_PIPES_INVALID"
  exit_code = 4

  def __init__(self):
    super().__init__(self.code)


def _reject():
  error = InitializerPipesError()
  try:
    raise error
  except InitializerPipesError:
    error.__cause__ = None
    error.__context__ = None
    raise


@dataclass(slots=True)
class _Methods:
  pipe2: object
  fstat: object
  close: object
  fcntl: object
  current_thread: object
  main_thread: object
  thread: object


@dataclass(frozen=True, slots=True)
class _Endpoint:
  fd: int
  metadata: tuple
  status: int
  descriptor: int


@dataclass(slots=True)
class _Ownership:
  owned: dict = field(default_factory=dict)
  pending_pipe: object = None
  pending_dup: object = None


@dataclass(slots=True)
class _Record:
  receiver: object
  methods: _Methods
  endpoints: tuple
  retired: bool = False


# 只登记本工厂的原 receiver；强引用避免 id 重用。
_records = {}


def _remember(owned, fd):
  owned[fd] = None


def _register_record(record):
  _records[id(record.receiver)] = record


def _valid_fd(value):
  return type(value) is int and value >= 0


def _metadata(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_rdev)


def _capture(methods, fd, direction):
  info = methods.fstat(fd)
  metadata = _metadata(info)
  status = methods.fcntl(fd, fcntl.F_GETFL)
  descriptor = methods.fcntl(fd, fcntl.F_GETFD)
  if not stat.S_ISFIFO(info.st_mode) or status & os.O_ACCMODE != direction:
    raise ValueError()
  if not status & os.O_NONBLOCK or not descriptor & fcntl.FD_CLOEXEC:
    raise ValueError()
  return _Endpoint(fd, metadata, status, descriptor)


def _verify(methods, endpoint):
  if _metadata(methods.fstat(endpoint.fd)) != endpoint.metadata:
    raise ValueError()
  if methods.fcntl(endpoint.fd, fcntl.F_GETFL) != endpoint.status:
    raise ValueError()
  if methods.fcntl(endpoint.fd, fcntl.F_GETFD) != endpoint.descriptor:
    raise ValueError()


def _normalize(methods, ownership, endpoint, direction):
  if endpoint.fd >= 4:
    return endpoint
  # 原 dup 返回值先留在 pending，再登记；登记故障也不丢失已返回资源。
  ownership.pending_dup = methods.fcntl(endpoint.fd, fcntl.F_DUPFD_CLOEXEC, 4)
  fd = ownership.pending_dup
  conflict = _valid_fd(fd) and fd in ownership.owned
  if _valid_fd(fd):
    _remember(ownership.owned, fd)
  ownership.pending_dup = None
  if not _valid_fd(fd) or fd < 4 or conflict:
    raise ValueError()
  replacement = _capture(methods, fd, direction)
  if (replacement.metadata, replacement.status, replacement.descriptor) != (
      endpoint.metadata, endpoint.status, endpoint.descriptor):
    raise ValueError()
  # 旧端点先永久退役再 close，异常不会进入后续 cleanup 的重试集合。
  ownership.owned.pop(endpoint.fd)
  methods.close(endpoint.fd)
  return replacement


def _pair(methods, ownership, other_identity=None):
  previous = tuple(ownership.owned)
  ownership.pending_pipe = methods.pipe2(os.O_CLOEXEC | os.O_NONBLOCK)
  raw = ownership.pending_pipe
  if type(raw) is tuple:
    for fd in raw:
      if _valid_fd(fd):
        _remember(ownership.owned, fd)
  ownership.pending_pipe = None
  if type(raw) is not tuple or len(raw) != 2 or not all(_valid_fd(fd) for fd in raw):
    raise ValueError()
  if raw[0] == raw[1] or any(fd in previous for fd in raw):
    raise ValueError()
  read = _capture(methods, raw[0], os.O_RDONLY)
  write = _capture(methods, raw[1], os.O_WRONLY)
  identity = read.metadata[:2]
  if identity != write.metadata[:2] or identity == other_identity:
    raise ValueError()
  read = _normalize(methods, ownership, read, os.O_RDONLY)
  write = _normalize(methods, ownership, write, os.O_WRONLY)
  return read, write


def _cleanup(methods, ownership):
  # 先退休 pending；逐个处理，不先分配新的资源批次。
  pending_pipe = ownership.pending_pipe
  pending_dup = ownership.pending_dup
  ownership.pending_pipe = None
  ownership.pending_dup = None
  if type(pending_pipe) is tuple:
    index = 0
    while index < len(pending_pipe):
      fd = pending_pipe[index]
      if _valid_fd(fd) and fd not in ownership.owned:
        previous = 0
        duplicate = False
        while previous < index:
          earlier = pending_pipe[previous]
          if _valid_fd(earlier) and earlier == fd:
            duplicate = True
            break
          previous += 1
        if not duplicate:
          try:
            methods.close(fd)
          except BaseException:
            pass
      index += 1
  if _valid_fd(pending_dup) and pending_dup not in ownership.owned:
    covered = False
    if type(pending_pipe) is tuple:
      for fd in pending_pipe:
        if _valid_fd(fd) and fd == pending_dup:
          covered = True
          break
    if not covered:
      try:
        methods.close(pending_dup)
      except BaseException:
        pass
  while ownership.owned:
    # popitem 先退休此端点；close 失败继续其他端，不回填或重试。
    fd, unused = ownership.owned.popitem()
    try:
      methods.close(fd)
    except BaseException:
      pass


def _registered(receiver):
  record = _records.get(id(receiver))
  if type(receiver) is not InitializerPipes or record is None or record.receiver is not receiver:
    raise ValueError()
  if record.retired:
    raise ValueError()
  methods = record.methods
  if methods.current_thread() is not methods.thread or methods.main_thread() is not methods.thread:
    raise ValueError()
  return record


class InitializerPipes:
  """无公开端点或角色；只有工厂登记的原对象可以 check/close。"""

  __slots__ = ()

  def __new__(cls, *args, **kwargs):
    _reject()

  def __reduce_ex__(self, protocol):
    _reject()

  def check(self):
    failed = False
    try:
      record = _registered(self)
      for endpoint in record.endpoints:
        _verify(record.methods, endpoint)
      if record.retired:
        raise ValueError()
    except BaseException:
      failed = True
    if failed:
      _reject()

  def close(self):
    record = None
    try:
      record = _registered(self)
    except BaseException:
      pass
    if record is None:
      _reject()
    record.retired = True
    failed = False
    for endpoint in record.endpoints:
      try:
        _verify(record.methods, endpoint)
        record.methods.close(endpoint.fd)
      except BaseException:
        # 失败端点不重试；继续核验并清理其他仍自有端点。
        failed = True
    if failed:
      _reject()


def create_initializer_pipes():
  """主线程创建两条单向 pipe；无业务路径、读写、移交或 launch。"""
  ownership = None
  methods = None
  record = None
  failed = False
  try:
    ownership = _Ownership()
    methods = _Methods(os.pipe2, os.fstat, os.close, fcntl.fcntl,
      threading.current_thread, threading.main_thread, None)
    methods.thread = methods.current_thread()
    if methods.thread is not methods.main_thread():
      raise ValueError()
    controller_read, parent_write = _pair(methods, ownership)
    parent_read, controller_write = _pair(methods, ownership, controller_read.metadata[:2])
    endpoints = (controller_read, parent_write, parent_read, controller_write)
    if len({endpoint.fd for endpoint in endpoints}) != 4:
      raise ValueError()
    pipes = object.__new__(InitializerPipes)
    record = _Record(pipes, methods, endpoints)
    _register_record(record)
  except BaseException:
    failed = True
  if failed:
    if record is not None:
      record.retired = True
    if methods is not None and ownership is not None:
      try:
        _cleanup(methods, ownership)
      except BaseException:
        pass
    _reject()
  return pipes
