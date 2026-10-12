"""合成双 pipe 所有权；全部 syscall/thread 为假，不创建实际端点。"""

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


SECRET = "SYNTHETIC_INITIALIZER_PIPES_PRIVATE"
CODE = "PI_INITIALIZER_PIPES_INVALID"


def rejected(action):
  try:
    raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Exception) as caught:
      action()
  error = caught.value
  assert error.args == (CODE,) and error.exit_code == 4
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))


class FakeCalls:
  def __init__(self):
    self.events = []
    self.returns = [(11, 12), (13, 14)]
    self.nodes = {}
    self.pipe_calls = 0
    self.fail_pipe = None
    self.fail_fstat = set()
    self.fail_fcntl = set()
    self.fail_close = set()
    self.dup_returns = [21, 22, 23, 24]
    self.dup_mutate = None
    self.on_close = None
    self.on_pipe = None
    self.main = object()
    self.thread = self.main
    self.thread_error = False

  def node(self, pipe, direction):
    return SimpleNamespace(st_dev=8, st_ino=100 + pipe, st_mode=stat.S_IFIFO | 0o600,
      st_uid=1000, st_gid=1000, st_rdev=0,
      status=(os.O_RDONLY if direction == 0 else os.O_WRONLY) | os.O_NONBLOCK,
      descriptor=fcntl.FD_CLOEXEC, st_size=0, st_mtime_ns=0, st_nlink=1)

  def pipe2(self, flags):
    self.pipe_calls += 1
    self.events.append(("pipe2", flags))
    if self.on_pipe: self.on_pipe(self.pipe_calls)
    if self.fail_pipe == self.pipe_calls: raise RuntimeError(SECRET)
    result = self.returns[self.pipe_calls - 1]
    if type(result) is tuple:
      for direction, fd in enumerate(result):
        if type(fd) is int and fd >= 0 and fd not in self.nodes:
          self.nodes[fd] = self.node(self.pipe_calls, direction)
    return result

  def fstat(self, fd):
    self.events.append(("fstat", fd))
    if fd in self.fail_fstat: raise RuntimeError(SECRET)
    if fd not in self.nodes: raise OSError(errno.EBADF, SECRET)
    return self.nodes[fd]

  def fcntl(self, fd, command, *args):
    self.events.append(("fcntl", fd, command, *args))
    if (fd, command) in self.fail_fcntl: raise RuntimeError(SECRET)
    if command == fcntl.F_DUPFD_CLOEXEC:
      assert args == (4,)
      result = self.dup_returns.pop(0)
      if type(result) is int and result >= 0 and result not in self.nodes:
        self.nodes[result] = SimpleNamespace(**vars(self.nodes[fd]))
        if self.dup_mutate: self.dup_mutate(self.nodes[result])
      return result
    assert args == () and command in (fcntl.F_GETFL, fcntl.F_GETFD)
    return self.nodes[fd].status if command == fcntl.F_GETFL else self.nodes[fd].descriptor

  def close(self, fd):
    self.events.append(("close", fd))
    if self.on_close: self.on_close(fd)
    if fd in self.fail_close: raise RuntimeError(SECRET)
    self.nodes.pop(fd, None)

  def current_thread(self):
    if self.thread_error: raise RuntimeError(SECRET)
    return self.thread

  def main_thread(self): return self.main


@pytest.fixture
def fake(monkeypatch):
  module = importlib.import_module("agentcfg.pi_durable_initializer_pipes")
  calls = FakeCalls()
  monkeypatch.setattr(module, "os", SimpleNamespace(pipe2=calls.pipe2, fstat=calls.fstat,
    close=calls.close, O_RDONLY=os.O_RDONLY, O_WRONLY=os.O_WRONLY, O_ACCMODE=os.O_ACCMODE,
    O_CLOEXEC=os.O_CLOEXEC, O_NONBLOCK=os.O_NONBLOCK))
  monkeypatch.setattr(module, "fcntl", SimpleNamespace(fcntl=calls.fcntl,
    F_GETFL=fcntl.F_GETFL, F_GETFD=fcntl.F_GETFD, F_DUPFD_CLOEXEC=fcntl.F_DUPFD_CLOEXEC,
    FD_CLOEXEC=fcntl.FD_CLOEXEC))
  monkeypatch.setattr(module, "threading", SimpleNamespace(current_thread=calls.current_thread,
    main_thread=calls.main_thread))
  return module, calls


def close_fds(calls): return [event[1] for event in calls.events if event[0] == "close"]


def assert_closed_once(calls, expected):
  closed = close_fds(calls)
  assert len(closed) == len(set(closed)) and set(closed) == set(expected)


def test_success_exact_order_flags_interface_and_no_public_endpoints(fake):
  module, calls = fake
  assert not inspect.signature(module.create_initializer_pipes).parameters
  pipes = module.create_initializer_pipes()
  expected = []
  for endpoints in ((11, 12), (13, 14)):
    expected.append(("pipe2", os.O_CLOEXEC | os.O_NONBLOCK))
    for fd in endpoints:
      expected.extend((("fstat", fd), ("fcntl", fd, fcntl.F_GETFL), ("fcntl", fd, fcntl.F_GETFD)))
  assert calls.events == expected
  assert type(pipes) is module.InitializerPipes
  for name in ("fileno", "fds", "fd", "roles", "controller_read", "parent_write", "launch", "to_dict", "__dict__", "__enter__"):
    assert not hasattr(pipes, name)
  assert pipes.check() is None
  assert calls.pipe_calls == 2 and close_fds(calls) == []
  assert pipes.close() is None
  assert_closed_once(calls, (11, 12, 13, 14))


def test_nonmain_or_unknown_thread_has_zero_io(fake):
  module, calls = fake
  calls.thread = object()
  rejected(module.create_initializer_pipes)
  assert calls.events == []
  calls.thread_error = True
  rejected(module.create_initializer_pipes)
  assert calls.events == []


@pytest.mark.parametrize("at", [1, 2])
def test_pipe_failure_only_cleans_previous_returned_endpoints(fake, at):
  module, calls = fake
  calls.fail_pipe = at
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == at
  assert_closed_once(calls, () if at == 1 else (11, 12))


@pytest.mark.parametrize("returns,expected", [((11, 11), (11,)), ((11, True), (11,)),
  ((11, -1), (11,)), ((11,), (11,)), ((11, 12, 15), (11, 12, 15)),
  ([11, 12], ()), (None, ())])
def test_malformed_pipe_result_closes_only_valid_returned_exact_tuple_integers(fake, returns, expected):
  module, calls = fake
  calls.returns[0] = returns
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == 1
  assert_closed_once(calls, expected)


@pytest.mark.parametrize("at", [1, 2, 3, 4])
def test_immediate_endpoint_registration_failure_keeps_returned_cleanup(fake, monkeypatch, at):
  module, calls = fake
  original = module._remember
  count = 0
  def failing(owned, fd):
    nonlocal count
    count += 1
    if count == at: raise RuntimeError(SECRET)
    original(owned, fd)
  monkeypatch.setattr(module, "_remember", failing)
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == (1 if at <= 2 else 2)
  assert_closed_once(calls, (11, 12) if at <= 2 else (11, 12, 13, 14))


def test_first_endpoints_registered_before_inspection_and_second_creation(fake, monkeypatch):
  module, calls = fake
  remembered = set()
  original = module._remember
  def remember(owned, fd):
    original(owned, fd)
    remembered.add(fd)
  monkeypatch.setattr(module, "_remember", remember)
  original_stat = module.os.fstat
  def inspecting(fd):
    assert fd in remembered
    return original_stat(fd)
  module.os.fstat = inspecting
  calls.on_pipe = lambda count: None if count == 1 else remembered.issuperset((11, 12)) or pytest.fail("not registered")
  pipes = module.create_initializer_pipes()
  pipes.close()


@pytest.mark.parametrize("fd", [11, 12, 13, 14])
@pytest.mark.parametrize("operation", ["fstat", "getfl", "getfd"])
def test_each_inspection_failure_cleans_known_once_and_stops_creation(fake, fd, operation):
  module, calls = fake
  if operation == "fstat": calls.fail_fstat.add(fd)
  else: calls.fail_fcntl.add((fd, fcntl.F_GETFL if operation == "getfl" else fcntl.F_GETFD))
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == (1 if fd <= 12 else 2)
  assert_closed_once(calls, (11, 12) if fd <= 12 else (11, 12, 13, 14))


@pytest.mark.parametrize("field,value", [("st_mode", stat.S_IFCHR | 0o600), ("status", os.O_RDWR | os.O_NONBLOCK),
  ("status", os.O_RDONLY), ("descriptor", 0)])
def test_invalid_fifo_or_direction_or_required_flags(fake, field, value):
  module, calls = fake
  calls.on_pipe = lambda count: None
  original_stat = module.os.fstat
  def mutate(fd):
    info = original_stat(fd)
    if fd == 11: setattr(info, field, value)
    return info
  module.os.fstat = mutate
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == 1
  assert_closed_once(calls, (11, 12))


@pytest.mark.parametrize("scenario", ["same-end", "cross-fd", "pair-identity", "same-pipe"])
def test_duplicate_endpoints_and_pipe_identities_rejected(fake, scenario):
  module, calls = fake
  if scenario == "same-end": calls.returns[1] = (13, 13)
  if scenario == "cross-fd": calls.returns[1] = (11, 14)
  original_stat = module.os.fstat
  def mutate(fd):
    info = original_stat(fd)
    if scenario == "pair-identity" and fd == 12: info.st_ino += 1
    if scenario == "same-pipe" and fd in (13, 14): info.st_ino = 101
    return info
  module.os.fstat = mutate
  rejected(module.create_initializer_pipes)
  expected = (11, 12) if scenario == "pair-identity" else (11, 12, 13) if scenario == "same-end" else (11, 12, 14) if scenario == "cross-fd" else (11, 12, 13, 14)
  assert_closed_once(calls, expected)


def test_all_low_endpoints_normalized_with_original_identity_and_flags(fake):
  module, calls = fake
  calls.returns = [(0, 1), (2, 3)]
  pipes = module.create_initializer_pipes()
  assert close_fds(calls) == [0, 1, 2, 3]
  assert [event for event in calls.events if event[0] == "fcntl" and event[2] == fcntl.F_DUPFD_CLOEXEC] == [
    ("fcntl", fd, fcntl.F_DUPFD_CLOEXEC, 4) for fd in (0, 1, 2, 3)]
  assert set(calls.nodes) == {21, 22, 23, 24}
  pipes.check()
  pipes.close()
  assert_closed_once(calls, (0, 1, 2, 3, 21, 22, 23, 24))


@pytest.mark.parametrize("scenario", ["dup-error", "low-result", "conflict", "register", "identity", "direction", "nonblock", "cloexec", "inspect", "old-close"])
def test_low_dup_failure_tracks_every_return_and_never_retries_old_close(fake, monkeypatch, scenario):
  module, calls = fake
  calls.returns[0] = (0, 12)
  if scenario == "dup-error": calls.fail_fcntl.add((0, fcntl.F_DUPFD_CLOEXEC))
  if scenario == "low-result": calls.dup_returns[0] = 3
  if scenario == "conflict": calls.dup_returns[0] = 12
  if scenario == "register":
    original = module._remember
    def fail_new(owned, fd):
      if fd == 21: raise RuntimeError(SECRET)
      original(owned, fd)
    monkeypatch.setattr(module, "_remember", fail_new)
  if scenario == "identity": calls.dup_mutate = lambda node: setattr(node, "st_ino", 999)
  if scenario == "direction": calls.dup_mutate = lambda node: setattr(node, "status", os.O_WRONLY | os.O_NONBLOCK)
  if scenario == "nonblock": calls.dup_mutate = lambda node: setattr(node, "status", os.O_RDONLY)
  if scenario == "cloexec": calls.dup_mutate = lambda node: setattr(node, "descriptor", 0)
  if scenario == "inspect": calls.fail_fstat.add(21)
  if scenario == "old-close": calls.fail_close.add(0)
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == 1
  extra = () if scenario in ("dup-error", "conflict") else (3,) if scenario == "low-result" else (21,)
  assert_closed_once(calls, (0, 12) + extra)


def test_cleanup_close_errors_do_not_stop_other_owned_cleanup(fake):
  module, calls = fake
  calls.fail_pipe = 2
  calls.fail_close = {11, 12}
  rejected(module.create_initializer_pipes)
  assert_closed_once(calls, (11, 12))


def test_final_record_registration_failure_cleans_four_owned(fake, monkeypatch):
  module, calls = fake
  def failed(record): raise RuntimeError(SECRET)
  monkeypatch.setattr(module, "_register_record", failed)
  rejected(module.create_initializer_pipes)
  assert_closed_once(calls, (11, 12, 13, 14))


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev", "status", "descriptor", "closed", "unknown"])
def test_check_drift_is_rejected_without_create_close_or_path_io(fake, field):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  if field == "closed": calls.nodes.pop(11)
  elif field == "unknown": calls.fail_fstat.add(11)
  else: setattr(calls.nodes[11], field, getattr(calls.nodes[11], field) + 1)
  rejected(pipes.check)
  assert calls.pipe_calls == 2 and close_fds(calls) == []


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_rdev", "status", "descriptor", "closed", "unknown"])
def test_close_drift_retires_all_but_skips_foreign_and_continues_other_owned(fake, field):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  if field == "closed": calls.nodes.pop(11)
  elif field == "unknown": calls.fail_fstat.add(11)
  else: setattr(calls.nodes[11], field, getattr(calls.nodes[11], field) + 1)
  rejected(pipes.close)
  assert_closed_once(calls, (12, 13, 14))
  rejected(pipes.close)
  rejected(pipes.check)
  assert_closed_once(calls, (12, 13, 14))


def test_close_error_and_reentrancy_never_retry_and_continue_all_endpoints(fake):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  calls.fail_close = {11, 13}
  calls.on_close = lambda fd: (rejected(pipes.check), rejected(pipes.close))
  rejected(pipes.close)
  rejected(pipes.close)
  assert_closed_once(calls, (11, 12, 13, 14))


def test_wrong_thread_and_foreign_receiver_cannot_retire_original(fake):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  calls.thread = object()
  rejected(pipes.check)
  rejected(pipes.close)
  calls.thread = calls.main
  rejected(lambda: module.InitializerPipes.close(object.__new__(module.InitializerPipes)))
  pipes.check()
  pipes.close()
  assert_closed_once(calls, (11, 12, 13, 14))


@pytest.mark.parametrize("kind", ["raw", "foreign", "proxy", "subclass", "constructor", "copy", "deepcopy", "pickle"])
def test_no_reconstruction_or_foreign_receiver(fake, kind):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  if kind == "raw": action = lambda: module.InitializerPipes.check(object.__new__(module.InitializerPipes))
  elif kind == "foreign": action = lambda: module.InitializerPipes.check(object())
  elif kind == "proxy":
    class Proxy:
      def __getattr__(self, name): return getattr(pipes, name)
    action = lambda: module.InitializerPipes.check(Proxy())
  elif kind == "subclass":
    class Other(module.InitializerPipes): pass
    action = lambda: module.InitializerPipes.check(object.__new__(Other))
  elif kind == "constructor": action = module.InitializerPipes
  elif kind == "copy": action = lambda: copy(pipes)
  elif kind == "deepcopy": action = lambda: deepcopy(pipes)
  else: action = lambda: pickle.dumps(pipes)
  rejected(action)
  assert close_fds(calls) == []


def test_original_methods_receivers_and_thread_functions_are_captured(fake):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  def forbidden(*args): raise RuntimeError(SECRET)
  module.os.pipe2 = module.os.fstat = module.os.close = forbidden
  module.fcntl.fcntl = forbidden
  module.threading.current_thread = module.threading.main_thread = forbidden
  pipes.check()
  pipes.close()
  assert_closed_once(calls, (11, 12, 13, 14))


def test_size_time_and_nlink_are_not_identity_fields(fake):
  module, calls = fake
  pipes = module.create_initializer_pipes()
  for node in calls.nodes.values():
    node.st_size += 1
    node.st_mtime_ns += 1
    node.st_nlink += 1
  pipes.check()
  pipes.close()
  assert_closed_once(calls, (11, 12, 13, 14))


@pytest.mark.parametrize("name,expected", [("_Ownership", ()), ("_Methods", ()), ("_Endpoint", (11, 12)), ("_Record", (11, 12, 13, 14))])
def test_internal_allocation_failure_is_fixed_and_keeps_owned_cleanup(fake, monkeypatch, name, expected):
  module, calls = fake
  def failed(*args, **kwargs): raise RuntimeError(SECRET)
  monkeypatch.setattr(module, name, failed)
  rejected(module.create_initializer_pipes)
  assert_closed_once(calls, expected)
  if not expected: assert calls.events == []


@pytest.mark.parametrize("fd", [0, 1, 2, 3])
@pytest.mark.parametrize("failure", ["dup", "new-inspection", "old-close"])
def test_each_low_endpoint_failure_stops_followup_and_closes_each_known_once(fake, fd, failure):
  module, calls = fake
  calls.returns = [(0, 1), (2, 3)]
  if failure == "dup": calls.fail_fcntl.add((fd, fcntl.F_DUPFD_CLOEXEC))
  if failure == "new-inspection": calls.fail_fstat.add(21 + fd)
  if failure == "old-close": calls.fail_close.add(fd)
  rejected(module.create_initializer_pipes)
  acquired_old = (0, 1) if fd < 2 else (0, 1, 2, 3)
  acquired_new = tuple(range(21, 21 + fd + (failure != "dup")))
  assert_closed_once(calls, acquired_old + acquired_new)
  assert calls.pipe_calls == (1 if fd < 2 else 2)
  duplicates = [event for event in calls.events if event[0] == "fcntl" and event[2] == fcntl.F_DUPFD_CLOEXEC]
  assert len(duplicates) == fd + 1


def test_dup_is_registered_before_inspection_and_foreign_three_remains_untouched(fake, monkeypatch):
  module, calls = fake
  calls.returns = [(0, 1), (13, 14)]
  foreign = calls.node(99, 0)
  calls.nodes[3] = foreign
  remembered = set()
  original_remember = module._remember
  def remember(owned, fd):
    original_remember(owned, fd)
    remembered.add(fd)
  monkeypatch.setattr(module, "_remember", remember)
  original_stat = module.os.fstat
  def inspect_owned(fd):
    assert fd in remembered
    return original_stat(fd)
  module.os.fstat = inspect_owned
  pipes = module.create_initializer_pipes()
  pipes.check()
  pipes.close()
  assert calls.nodes[3] is foreign
  assert all(event[1] != 3 for event in calls.events if event[0] in ("fstat", "fcntl", "close"))
  assert_closed_once(calls, (0, 1, 21, 22, 13, 14))


@pytest.mark.parametrize("fd,value", [(11, os.O_WRONLY | os.O_NONBLOCK), (12, os.O_RDONLY | os.O_NONBLOCK)])
def test_read_and_write_direction_cannot_be_reversed(fake, fd, value):
  module, calls = fake
  original_stat = module.os.fstat
  def reversed_direction(endpoint):
    info = original_stat(endpoint)
    if endpoint == fd: info.status = value
    return info
  module.os.fstat = reversed_direction
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == 1
  assert_closed_once(calls, (11, 12))


def test_tuple_subclass_is_not_iterated_or_treated_as_owned(fake):
  module, calls = fake
  visited = []
  class ForeignTuple(tuple):
    def __iter__(self):
      visited.append("iter")
      raise RuntimeError(SECRET)
    def __len__(self):
      visited.append("len")
      raise RuntimeError(SECRET)
  calls.returns[0] = ForeignTuple((11, 12))
  rejected(module.create_initializer_pipes)
  assert calls.pipe_calls == 1 and visited == []
  assert close_fds(calls) == []


def test_post_insert_interrupt_retires_receiver_before_any_failure_cleanup(fake, monkeypatch):
  module, calls = fake
  inserted = []
  observed_retired = []
  original = module._register_record
  def interrupted(record):
    original(record)
    inserted.append(record)
    raise KeyboardInterrupt(SECRET)
  monkeypatch.setattr(module, "_register_record", interrupted)
  def cleanup_callback(fd):
    record = inserted[0]
    observed_retired.append(record.retired)
    rejected(record.receiver.check)
    rejected(record.receiver.close)
  calls.on_close = cleanup_callback
  rejected(module.create_initializer_pipes)
  assert inserted[0].retired is True
  assert observed_retired == [True, True, True, True]
  assert_closed_once(calls, (11, 12, 13, 14))
  assert calls.nodes == {}


def test_cleanup_never_allocates_fresh_set_before_known_owned_closes(fake, monkeypatch):
  module, calls = fake
  allocated = []
  def failing_set(*args):
    allocated.append(True)
    raise MemoryError(SECRET)
  monkeypatch.setattr(module, "set", failing_set, raising=False)
  calls.fail_pipe = 2
  rejected(module.create_initializer_pipes)
  assert allocated == []
  assert_closed_once(calls, (11, 12))
  assert calls.nodes == {}


def test_unexpected_cleanup_exception_is_fixed_without_release_claim(fake, monkeypatch):
  module, calls = fake
  calls.fail_pipe = 2
  def unknown_cleanup(methods, ownership): raise MemoryError(SECRET)
  monkeypatch.setattr(module, "_cleanup", unknown_cleanup)
  rejected(module.create_initializer_pipes)
  assert close_fds(calls) == []
  assert set(calls.nodes) == {11, 12}


@pytest.mark.parametrize("returns,fail_at,expected", [((11, 11, 15), 1, (11, 15)),
  ((11, 11, 15), 2, (11, 15)), ((11, 14), 3, (11, 12, 14))])
def test_pending_tuple_cleanup_deduplicates_unregistered_and_previous_owned(fake, monkeypatch, returns, fail_at, expected):
  module, calls = fake
  calls.returns[0 if fail_at <= 2 else 1] = returns
  original = module._remember
  count = 0
  def registration_failure(owned, fd):
    nonlocal count
    count += 1
    if count == fail_at: raise MemoryError(SECRET)
    original(owned, fd)
  monkeypatch.setattr(module, "_remember", registration_failure)
  rejected(module.create_initializer_pipes)
  assert_closed_once(calls, expected)
