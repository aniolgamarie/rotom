"""独立持续 SourceSH 资源；不提供来源、actor、SourceHold 或交接资格。"""

from dataclasses import dataclass
from functools import wraps
import fcntl
import os
import stat
import threading

from .deployment import json_bytes
from .pi import PiAdapter
from .storage import Tree
from .workspace import Workspace
from .pi_source_latch import _acquire, _cleanup, _identity, _directory_identity


_GET_PROFILE = Workspace.profile.fget
_GET_AGENT = Workspace.agent.fget
_GET_INSTANCE = Workspace.instance.fget
_GET_STATE = Workspace.state_root.fget
_GET_BINDING = Workspace.binding.fget
_GETFL, _GETFD, _CLOEXEC = fcntl.F_GETFL, fcntl.F_GETFD, fcntl.FD_CLOEXEC
_ACCESS, _RW, _NONBLOCK = os.O_ACCMODE, os.O_RDWR, os.O_NONBLOCK
_records = {}
_MAX_READERS = 64
_starting = 0


class SourceReaderError(Exception):
  code = "PI_SOURCE_READER_INVALID"
  exit_code = 4

  def __init__(self): super().__init__(self.code)


def _reject():
  error = SourceReaderError()
  try:
    raise error
  except SourceReaderError:
    error.__cause__ = None
    error.__context__ = None
    raise


def _boundary(action):
  @wraps(action)
  def checked(*args, **kwargs):
    failed = False
    try: result = action(*args, **kwargs)
    except BaseException: failed = True
    if failed: _reject()
    return result
  return checked


@dataclass(slots=True)
class _Methods:
  fstat: object
  stat: object
  close: object
  geteuid: object
  fcntl: object
  current_thread: object
  main_thread: object
  tree_factory: object
  parent: object
  tree_close: object
  tree_read: object


@dataclass(slots=True)
class _Record:
  receiver: object
  workspace: Workspace
  context: tuple
  instance: object
  marker: bytes
  methods: _Methods
  thread: object
  resources: object
  source: int
  tree: object
  tree_fd: int
  source_identity: tuple
  root_identity: tuple
  status: int
  descriptor: int
  parent: object
  tree_close: object
  tree_read: object
  retired: bool = False


def _register_record(record):
  _records[id(record.receiver)] = record


def _invalid(): raise ValueError()


def _forget(record):
  key = id(record.receiver)
  if _records.get(key) is record:
    del _records[key]


def _reserve():
  global _starting
  if _starting + len(_records) >= _MAX_READERS: _invalid()
  _starting += 1


def _release():
  global _starting
  _starting -= 1


def _context(workspace):
  if type(workspace) is not Workspace or type(workspace.adapter) is not PiAdapter:
    _invalid()
  profile, agent = _GET_PROFILE(workspace), _GET_AGENT(workspace)
  if profile not in ("pi-base", "pi-full") or agent != "pi": _invalid()
  return (profile, agent, _GET_INSTANCE(workspace), _GET_STATE(workspace), _GET_BINDING(workspace), workspace.adapter)


def _marker(read, expected):
  raw = read(".agentcfg-instance.json", max_bytes=len(expected))
  if raw is None or raw[1] != 0o600 or raw[0] != expected: _invalid()


def _source(record):
  info = record.methods.fstat(record.source)
  if (not stat.S_ISREG(info.st_mode) or info.st_uid != record.methods.geteuid()
      or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 0
      or _identity(info) != record.source_identity): _invalid()
  if record.methods.fcntl(record.source, _GETFL) != record.status: _invalid()
  if record.methods.fcntl(record.source, _GETFD) != record.descriptor: _invalid()


def _tree(record):
  if type(record.tree.fd) is not int or record.tree.fd != record.tree_fd: _invalid()
  if _directory_identity(record.methods.fstat(record.tree_fd)) != record.root_identity: _invalid()


def _check(record):
  if _context(record.workspace) != record.context: _invalid()
  _tree(record); _source(record)
  with record.parent("source.lock") as (parent, name):
    if _directory_identity(record.methods.fstat(parent)) != record.root_identity: _invalid()
    named = record.methods.stat(name, dir_fd=parent, follow_symlinks=False)
    if _identity(named) != record.source_identity: _invalid()
  _marker(record.tree_read, record.marker)
  with record.methods.tree_factory(record.instance) as named:
    if named.fd is None or _directory_identity(record.methods.fstat(named.fd)) != record.root_identity: _invalid()


def _registered(receiver):
  record = _records.get(id(receiver))
  if type(receiver) is not SourceReader or record is None or record.receiver is not receiver or record.retired: _invalid()
  if record.methods.current_thread() is not record.thread or record.methods.main_thread() is not record.thread: _invalid()
  return record


class SourceReader:
  __slots__ = ()

  def __new__(cls, *args, **kwargs): _reject()

  def __reduce_ex__(self, protocol): _reject()

  @_boundary
  def check(self):
    record = _registered(self)
    _check(record)
    if record.retired: _invalid()

  @_boundary
  def close(self):
    record = _registered(self)
    record.retired = True
    failed = False
    try: _check(record)
    except BaseException: failed = True
    # named/context坏不自动认定held foreign；逐项独立核自有资源。
    try: _source(record)
    except BaseException:
      record.resources.source = None
      failed = True
    try: _tree(record)
    except BaseException:
      record.resources.tree = None
      failed = True
    both_owned = record.resources.source is not None and record.resources.tree is not None
    try: _cleanup(record.resources)
    except BaseException: failed = True
    else:
      # 共用cleanup正常完成且两项都已核自有，两个原close均成功。
      if both_owned: _forget(record)
    if failed: _invalid()


@_boundary
def hold_source_reader(workspace):
  resources, record = None, None
  methods = _Methods(os.fstat, os.stat, os.close, os.geteuid, fcntl.fcntl,
    threading.current_thread, threading.main_thread, Tree, Tree.parent, Tree.close, Tree.read)
  thread = methods.current_thread()
  if thread is not methods.main_thread(): _invalid()
  _reserve()
  try:
    context = _context(workspace)
    instance, state, binding = context[2:5]
    expected = json_bytes({"schema_version": 1, "state_root": str(state), "binding": binding})
    with methods.tree_factory(instance) as marker_tree:
      _marker(methods.tree_read.__get__(marker_tree, type(marker_tree)), expected)
    failed = False
    try:
      # 共用唯一acquisition实现；这里固定SH/已有anchor。
      resources = _acquire(workspace, shared=True, create=False)
      resources.source_close = methods.close
      resources.tree_close = methods.tree_close.__get__(resources.tree, type(resources.tree))
      status = methods.fcntl(resources.source, _GETFL)
      descriptor = methods.fcntl(resources.source, _GETFD)
      if status & _ACCESS != _RW or not status & _NONBLOCK or not descriptor & _CLOEXEC: _invalid()
      reader = object.__new__(SourceReader)
      tree = resources.tree
      record = _Record(reader, workspace, context, instance, expected, methods, thread, resources,
        resources.source, tree, tree.fd, resources.original, resources.root, status, descriptor,
        methods.parent.__get__(tree, type(tree)), resources.tree_close, methods.tree_read.__get__(tree, type(tree)))
      _check(record)
      _register_record(record)
    except BaseException:
      failed = True
    if failed:
      if record is not None: record.retired = True
      if resources is not None:
        both_owned = resources.source is not None and resources.tree is not None
        try: _cleanup(resources)
        except BaseException: pass
        else:
          if record is not None and both_owned: _forget(record)
      _invalid()
    return reader
  finally:
    _release()
