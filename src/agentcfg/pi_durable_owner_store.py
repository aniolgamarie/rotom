"""原独占锁范围内的 acquired 发布与既有元数据读取；不授予 owner 权限。"""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from . import storage
from .activity_linux import LinuxProcesses
from .paths import PathError, _absolute_directory, _check_private, _open_directory
from .pi_durable_owner_record import capture_owner_record, decode_owner_record, encode_owner_record


Tree = storage.Tree
instance_lock = storage.instance_lock
Conflict = storage.Conflict
StateError = storage.StateError
_MESSAGE = "Durable所有者记录范围无效或需要恢复"


def _fail(kind=Conflict):
  error = kind(_MESSAGE)
  try:
    raise error
  except StateError:
    error.__context__ = None
    error.__cause__ = None
    raise


def _operation(call):
  kind = None
  try:
    return call()
  except (Conflict, PathError, FileNotFoundError, FileExistsError):
    kind = Conflict
  except Exception:
    kind = StateError
  _fail(kind)


def _input(root, deployment):
  if type(root) is not str or type(deployment) is not str: _fail()
  if (not root.startswith("/") or "\\" in root
      or any(ord(c) < 32 or ord(c) == 127 for c in root)
      or any(p in ("", ".", "..") for p in root.split("/")[1:])
      or re.fullmatch(r"[0-9a-f]{64}", deployment, re.ASCII) is None): _fail()
  if sys.platform != "linux": _fail()
  return Path(root)


def _binding(fd, directory=False):
  info = os.fstat(fd)
  if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
      or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
      or (not directory and info.st_nlink != 1)): _fail()
  binding = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
  return binding if directory else binding + (info.st_nlink,)


def _physical(fd):
  if type(fd) is not int: _fail()
  info = os.fstat(fd)
  return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))


@dataclass(frozen=True, slots=True)
class OwnerRecordScope:
  _observe: object

  def observe(self): return self._observe()

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


class _Scope:
  def __init__(self, root, deployment, create):
    self.root, self.deployment, self.create = root, deployment, create
    self.tree = self.tree_fd = self.directory_fd = self.parent_fd = self.lock_fd = None
    self.tree_receipt = self.directory_receipt = None
    self.parent_cm = self.lock_cm = None
    self.closed = False
    self.record = self.data = self.owner_identity = None
    self.tree_class, self.lock_function = Tree, instance_lock
    self.tree_methods = {name: getattr(Tree, name) for name in ("parent", "read", "write_new", "close")}
    self.process_class = LinuxProcesses
    self.process_methods = {name: getattr(LinuxProcesses, name) for name in ("identity", "observe")}
    self.epoch_function = secrets.token_hex
    self.processes = None

  def sources(self):
    if self.closed or Tree is not self.tree_class or instance_lock is not self.lock_function: _fail()
    if any(getattr(self.tree_class, n) is not fn for n, fn in self.tree_methods.items()): _fail()
    if LinuxProcesses is not self.process_class or secrets.token_hex is not self.epoch_function: _fail()
    if any(getattr(self.process_class, n) is not fn for n, fn in self.process_methods.items()): _fail()
    if self.tree is not None:
      if (type(self.tree) is not self.tree_class or type(self.tree.root) is not type(self.root) or self.tree.root != self.root
          or self.tree.private is not True or type(self.tree.fd) is not int or self.tree.fd != self.tree_fd): _fail()
      if any(getattr(getattr(self.tree, n), "__func__", None) is not fn
          or getattr(getattr(self.tree, n), "__self__", None) is not self.tree for n, fn in self.tree_methods.items()): _fail()
    if self.processes is not None:
      if type(self.processes) is not self.process_class: _fail()
      if any(getattr(getattr(self.processes, n), "__func__", None) is not fn
          or getattr(getattr(self.processes, n), "__self__", None) is not self.processes for n, fn in self.process_methods.items()): _fail()

  def guard(self):
    self.sources()
    if _binding(self.directory_fd, True) != self.directory_binding: _fail()
    if self.parent_fd is not None and _binding(self.parent_fd, True) != self.parent_binding: _fail()
    if self.tree_fd is not None and _binding(self.tree_fd, True) != self.directory_binding: _fail()
    with _absolute_directory(self.root) as fd:
      if _binding(fd, True) != self.directory_binding: _fail()
    if self.lock_fd is not None:
      if _binding(self.lock_fd) != self.lock_binding: _fail()
      info = os.stat("instance.lock", dir_fd=self.directory_fd, follow_symlinks=False)
      if (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink) != self.lock_binding: _fail()
    self.sources()

  def invoke(self, name, *args, **kwargs):
    self.guard()
    result = self.tree_methods[name](self.tree, *args, **kwargs)
    self.guard()
    return result

  def alive(self):
    self.guard()
    expected = dict(self.controller)
    result = self.process_methods["observe"](self.processes, expected)
    self.guard()
    if type(result) is not str or result != "alive" or expected != self.controller: _fail()

  def read(self):
    result = self.invoke("read", "owner.json", max_bytes=16384)
    if result is None or type(result) is not tuple or len(result) != 3 or result[1] != 0o600: _fail()
    record = decode_owner_record(result[0])
    if record.deployment_identity != self.deployment: _fail()
    if (record.storage_identity.device, record.storage_identity.inode) != self.directory_binding[:2]: _fail()
    self.guard()
    return record, result[0], result[2]

  def initialize(self):
    self.sources()
    if self.create:
      self.parent_cm = _absolute_directory(self.root.parent)
      self.parent_fd = self.parent_cm.__enter__()
      _check_private(self.parent_fd)
      self.parent_binding = _binding(self.parent_fd, True)
      os.mkdir(self.root.name, 0o700, dir_fd=self.parent_fd)
      self.directory_fd = _open_directory(self.parent_fd, self.root.name)
      self.directory_receipt = _physical(self.directory_fd)
      self.directory_binding = _binding(self.directory_fd, True)
      os.fsync(self.directory_fd)
      os.fsync(self.parent_fd)
    else:
      with _absolute_directory(self.root) as fd:
        self.directory_fd = os.dup(fd)
        self.directory_receipt = _physical(self.directory_fd)
      self.directory_binding = _binding(self.directory_fd, True)
    self.sources()
    self.tree = self.tree_class(self.root, create=False)
    self.tree_fd = self.tree.fd
    self.tree_receipt = _physical(self.tree_fd)
    self.tree_binding = _binding(self.tree_fd, True)
    self.guard()
    try:
      lock_info = os.stat("instance.lock", dir_fd=self.directory_fd, follow_symlinks=False)
    except FileNotFoundError:
      if not self.create: _fail()
    else:
      if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1
          or lock_info.st_uid != os.geteuid() or stat.S_IMODE(lock_info.st_mode) != 0o600): _fail()
    self.guard()
    self.lock_cm = self.lock_function(self.tree, create=self.create)
    self.lock_fd = self.lock_cm.__enter__()
    self.lock_binding = _binding(self.lock_fd)
    self.guard()
    if self.create:
      if self.invoke("read", "owner.json", max_bytes=16384) is not None: _fail()
      self.processes = self.process_class(self.root)
      self.guard()
      self.controller = self.process_methods["identity"](self.processes, os.getpid())
      self.guard()
      raw = {"schema": 1, "deployment_identity": self.deployment,
        "storage_identity": {"device": self.directory_binding[0], "inode": self.directory_binding[1]},
        "epoch": "0" * 64, "controller": self.controller, "writer": None, "stage": "acquired"}
      record = capture_owner_record(raw)
      if record.controller.pid != os.getpid() or record.controller.uid != os.geteuid(): _fail()
      self.controller = {name: getattr(record.controller, name) for name in
        ("platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid")}
      raw["controller"] = self.controller
      self.alive()
      raw["epoch"] = self.epoch_function(32)
      self.guard()
      record = capture_owner_record(raw)
      data = encode_owner_record(record)
      self.invoke("write_new", "owner.json", data)
      self.alive()
      self.record, self.data, self.owner_identity = self.read()
      if self.record != record or self.data != data: _fail()
    else:
      self.record, self.data, self.owner_identity = self.read()
    self.guard()
    return OwnerRecordScope(self.observe)

  def observe(self):
    try:
      def read_current():
        self.guard()
        record, data, identity = self.read()
        if record != self.record or data != self.data or identity != self.owner_identity: _fail()
        self.guard()
        return self.record
      return _operation(read_current)
    except BaseException:
      self.closed = True
      raise

  def cleanup(self):
    self.closed = True
    failed = False
    # 清理只核原物理回执；权限漂移不取消已取得句柄的所有权。
    # 不让 Tree.close 读取漂移后的 foreign fd。
    if self.lock_cm is not None:
      try: self.lock_cm.__exit__(None, None, None)
      except Exception: failed = True
    if self.tree_fd is not None:
      try:
        if self.tree_receipt is None or _physical(self.tree_fd) != self.tree_receipt: failed = True
        elif type(self.tree.fd) is int and self.tree.fd == self.tree_fd:
          self.tree_methods["close"](self.tree)
        else: os.close(self.tree_fd)
      except Exception: failed = True
    if self.directory_fd is not None:
      try:
        if self.directory_receipt is None or _physical(self.directory_fd) != self.directory_receipt: failed = True
        else: os.close(self.directory_fd)
      except Exception: failed = True
    if self.parent_cm is not None:
      try: self.parent_cm.__exit__(None, None, None)
      except Exception: failed = True
    if failed: _fail(StateError)


@contextmanager
def _scope(root, deployment, create):
  path = _input(root, deployment)
  state = _operation(lambda: _Scope(path, deployment, create))
  primary = False
  try:
    scope = _operation(state.initialize)
    try:
      yield scope
    except BaseException:
      primary = True
      raise
  except BaseException:
    primary = True
    raise
  finally:
    try: state.cleanup()
    except BaseException:
      if not primary: raise


def create_owner_record_scope(root, deployment_identity):
  return _scope(root, deployment_identity, True)


def open_owner_record_scope(root, deployment_identity):
  return _scope(root, deployment_identity, False)
