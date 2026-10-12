"""仅假 syscall 和假线程；不触碰 pytest 的真实 fd3。"""

from copy import copy, deepcopy
import errno
import fcntl
import importlib
import inspect
import os
import pickle
import stat
import traceback
from types import SimpleNamespace

import pytest


SECRET = "SYNTHETIC_CONTROLLER_SLOT_PRIVATE"
CODE = "PI_CONTROLLER_SLOT_INVALID"


def rejected(action):
  # 自有错误也不得保留调用方当前异常链。
  try:
    raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Exception) as caught:
      action()
  error = caught.value
  assert error.args == (CODE,)
  assert error.exit_code == 4
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))


class FakeCalls:
  def __init__(self):
    self.events = []
    self.occupied = False
    self.pre_error = errno.EBADF
    self.open_fd = 3
    self.open_error = None
    self.close_error = None
    self.held_error = None
    self.flag_error = None
    self.on_close = None
    self.thread_error = False
    self.info = SimpleNamespace(st_dev=21, st_ino=34, st_mode=stat.S_IFCHR | 0o666,
      st_uid=1000, st_gid=1000, st_rdev=os.makedev(1, 3))
    self.status_flags = os.O_RDONLY | os.O_NONBLOCK
    self.fd_flags = fcntl.FD_CLOEXEC
    self.main = object()
    self.thread = self.main

  def fstat(self, fd):
    self.events.append(("fstat", fd))
    if not self.occupied:
      raise OSError(self.pre_error, SECRET)
    if self.held_error:
      raise RuntimeError(SECRET)
    return self.info

  def open(self, path, flags):
    self.events.append(("open", path, flags))
    if self.open_error:
      raise RuntimeError(SECRET)
    self.occupied = True
    return self.open_fd

  def close(self, fd):
    self.events.append(("close", fd))
    if self.on_close:
      self.on_close()
    if self.close_error:
      raise RuntimeError(SECRET)
    self.occupied = False

  def fcntl(self, fd, command):
    self.events.append(("fcntl", fd, command))
    if self.flag_error:
      raise RuntimeError(SECRET)
    assert command in (fcntl.F_GETFL, fcntl.F_GETFD)
    return self.status_flags if command == fcntl.F_GETFL else self.fd_flags

  def current_thread(self):
    if self.thread_error: raise RuntimeError(SECRET)
    return self.thread

  def main_thread(self): return self.main


@pytest.fixture
def fake(monkeypatch):
  module = importlib.import_module("agentcfg.pi_durable_controller_slot")
  calls = FakeCalls()
  os_fake = SimpleNamespace(fstat=calls.fstat, open=calls.open, close=calls.close,
    O_RDONLY=os.O_RDONLY, O_CLOEXEC=os.O_CLOEXEC, O_NONBLOCK=os.O_NONBLOCK,
    O_ACCMODE=os.O_ACCMODE, major=os.major, minor=os.minor)
  fcntl_fake = SimpleNamespace(fcntl=calls.fcntl, F_GETFL=fcntl.F_GETFL,
    F_GETFD=fcntl.F_GETFD, FD_CLOEXEC=fcntl.FD_CLOEXEC)
  thread_fake = SimpleNamespace(current_thread=calls.current_thread, main_thread=calls.main_thread)
  monkeypatch.setattr(module, "os", os_fake)
  monkeypatch.setattr(module, "fcntl", fcntl_fake)
  monkeypatch.setattr(module, "threading", thread_fake)
  return module, calls


def closes(calls): return [event for event in calls.events if event[0] == "close"]


def opens(calls): return [event for event in calls.events if event[0] == "open"]


def test_reserve_interface_and_success(fake):
  module, calls = fake
  assert not inspect.signature(module.reserve_controller_slot).parameters
  slot = module.reserve_controller_slot()
  assert type(slot) is module.ControllerSlot
  assert calls.events == [("fstat", 3), ("open", "/dev/null", os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK),
    ("fstat", 3), ("fcntl", 3, fcntl.F_GETFL), ("fcntl", 3, fcntl.F_GETFD)]
  assert slot.check() is None
  assert len(opens(calls)) == 1
  assert slot.close() is None
  assert closes(calls) == [("close", 3)]
  for name in ("fileno", "fd", "pid", "source", "role", "__dict__", "__enter__", "to_dict"):
    assert not hasattr(slot, name)


@pytest.mark.parametrize("scenario", ["occupied", "not-main", "other-errno", "unknown"])
def test_preflight_never_opens_or_closes(fake, scenario):
  module, calls = fake
  if scenario == "occupied": calls.occupied = True
  if scenario == "not-main": calls.thread = object()
  if scenario == "other-errno": calls.pre_error = errno.EACCES
  if scenario == "unknown":
    module.os.fstat = lambda fd: (_ for _ in ()).throw(RuntimeError(SECRET))
  rejected(module.reserve_controller_slot)
  assert opens(calls) == closes(calls) == []
  if scenario == "not-main": assert calls.events == []


@pytest.mark.parametrize("close_error", [False, True])
def test_raced_high_fd_only_closes_owned_once(fake, close_error):
  module, calls = fake
  calls.open_fd = 19
  calls.close_error = close_error
  rejected(module.reserve_controller_slot)
  assert closes(calls) == [("close", 19)]
  assert len(opens(calls)) == 1
  assert calls.events[-1] == ("close", 19)


def test_open_failure_has_no_owned_fd(fake):
  module, calls = fake
  calls.open_error = True
  rejected(module.reserve_controller_slot)
  assert closes(calls) == []


@pytest.mark.parametrize("scenario", ["regular", "major", "minor", "writeonly", "readwrite", "no-cloexec", "fstat-error", "fcntl-error"])
@pytest.mark.parametrize("close_error", [False, True])
def test_bad_held_resource_cleans_owned_once(fake, scenario, close_error):
  module, calls = fake
  if scenario == "regular": calls.info.st_mode = stat.S_IFREG | 0o600
  if scenario == "major": calls.info.st_rdev = os.makedev(2, 3)
  if scenario == "minor": calls.info.st_rdev = os.makedev(1, 5)
  if scenario == "writeonly": calls.status_flags = os.O_WRONLY
  if scenario == "readwrite": calls.status_flags = os.O_RDWR
  if scenario == "no-cloexec": calls.fd_flags = 0
  if scenario == "fstat-error": calls.held_error = True
  if scenario == "fcntl-error": calls.flag_error = True
  calls.close_error = close_error
  rejected(module.reserve_controller_slot)
  assert closes(calls) == [("close", 3)]


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev", "status", "fd-flags", "closed", "thread"])
def test_check_rejects_metadata_flags_closed_and_thread_drift(fake, field):
  module, calls = fake
  slot = module.reserve_controller_slot()
  if field.startswith("st_"): setattr(calls.info, field, getattr(calls.info, field) + 1)
  if field == "status": calls.status_flags ^= os.O_NONBLOCK
  if field == "fd-flags": calls.fd_flags = 0
  if field == "closed": calls.occupied = False
  if field == "thread": calls.thread = object()
  rejected(slot.check)
  assert len(opens(calls)) == 1 and closes(calls) == []


def test_original_methods_and_receiver_are_captured(fake):
  module, calls = fake
  slot = module.reserve_controller_slot()
  def forbidden(*args, **kwargs): raise RuntimeError(SECRET)
  module.os.fstat = module.os.open = module.os.close = forbidden
  module.fcntl.fcntl = forbidden
  module.threading.current_thread = module.threading.main_thread = forbidden
  slot.check()
  slot.close()
  assert closes(calls) == [("close", 3)]


@pytest.mark.parametrize("kind", ["foreign", "raw", "proxy", "subclass", "constructor", "copy", "deepcopy", "pickle"])
def test_unregistered_and_reconstruction_are_rejected(fake, kind):
  module, calls = fake
  slot = module.reserve_controller_slot()
  if kind == "foreign": action = lambda: module.ControllerSlot.check(object())
  elif kind == "raw": action = lambda: module.ControllerSlot.check(object.__new__(module.ControllerSlot))
  elif kind == "proxy":
    class Proxy:
      def __getattr__(self, name): return getattr(slot, name)
    action = lambda: module.ControllerSlot.check(Proxy())
  elif kind == "subclass":
    class Subslot(module.ControllerSlot): pass
    action = lambda: module.ControllerSlot.check(object.__new__(Subslot))
  elif kind == "constructor": action = module.ControllerSlot
  elif kind == "copy": action = lambda: copy(slot)
  elif kind == "deepcopy": action = lambda: deepcopy(slot)
  else: action = lambda: pickle.dumps(slot)
  rejected(action)
  assert closes(calls) == []


@pytest.mark.parametrize("close_error", [False, True])
def test_close_retires_before_call_and_never_retries(fake, close_error):
  module, calls = fake
  slot = module.reserve_controller_slot()
  calls.on_close = lambda: (rejected(slot.close), rejected(slot.check))
  calls.close_error = close_error
  if close_error: rejected(slot.close)
  else: slot.close()
  rejected(slot.close)
  rejected(slot.check)
  assert closes(calls) == [("close", 3)]


def test_wrong_thread_close_has_no_syscall_and_original_owner_can_close(fake):
  module, calls = fake
  slot = module.reserve_controller_slot()
  calls.thread = object()
  rejected(slot.close)
  assert closes(calls) == []
  calls.thread = calls.main
  slot.close()
  assert closes(calls) == [("close", 3)]


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev", "status", "fd-flags", "closed", "unknown"])
def test_close_retires_drifted_or_unknown_resource_without_closing(fake, field):
  module, calls = fake
  slot = module.reserve_controller_slot()
  if field.startswith("st_"): setattr(calls.info, field, getattr(calls.info, field) + 1)
  if field == "status": calls.status_flags ^= os.O_NONBLOCK
  if field == "fd-flags": calls.fd_flags = 0
  if field == "closed": calls.occupied = False
  if field == "unknown": calls.held_error = True
  rejected(slot.close)
  calls.info = SimpleNamespace(st_dev=21, st_ino=34, st_mode=stat.S_IFCHR | 0o666,
    st_uid=1000, st_gid=1000, st_rdev=os.makedev(1, 3))
  calls.status_flags = os.O_RDONLY | os.O_NONBLOCK
  calls.fd_flags = fcntl.FD_CLOEXEC
  calls.occupied = True
  calls.held_error = None
  rejected(slot.check)
  rejected(slot.close)
  assert closes(calls) == []


def test_foreign_close_cannot_retire_owner(fake):
  module, calls = fake
  slot = module.reserve_controller_slot()
  rejected(lambda: module.ControllerSlot.close(object.__new__(module.ControllerSlot)))
  slot.check()
  slot.close()
  assert closes(calls) == [("close", 3)]


@pytest.mark.parametrize("operation", ["check", "close"])
@pytest.mark.parametrize("failure", ["fstat", "fcntl", "thread"])
def test_unknown_check_and_close_errors_are_fixed(fake, operation, failure):
  module, calls = fake
  slot = module.reserve_controller_slot()
  if failure == "fstat": calls.held_error = True
  if failure == "fcntl": calls.flag_error = True
  if failure == "thread": calls.thread_error = True
  rejected(getattr(slot, operation))
  assert len(opens(calls)) == 1 and closes(calls) == []


def test_close_checks_held_metadata_and_flags_before_owned_close(fake):
  module, calls = fake
  slot = module.reserve_controller_slot()
  calls.events.clear()
  slot.close()
  assert calls.events == [("fstat", 3), ("fcntl", 3, fcntl.F_GETFL),
    ("fcntl", 3, fcntl.F_GETFD), ("close", 3)]


def test_failed_registry_publication_retires_record_before_owned_close(fake, monkeypatch):
  module, calls = fake
  published = []

  class InterruptedRegistry(dict):
    def __setitem__(self, key, record):
      super().__setitem__(key, record)
      published.append(record)
      raise KeyboardInterrupt(SECRET)

  monkeypatch.setattr(module, "_records", InterruptedRegistry())
  calls.on_close = lambda: (
    rejected(published[0].receiver.check),
    rejected(published[0].receiver.close),
  )
  rejected(module.reserve_controller_slot)
  assert len(published) == 1
  assert published[0].retired is True
  assert closes(calls) == [("close", 3)]
  rejected(published[0].receiver.check)
  rejected(published[0].receiver.close)
  assert closes(calls) == [("close", 3)]
