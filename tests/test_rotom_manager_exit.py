"""只读 manager pidfd 行为验证；所有进程身份、句柄与 poll 均为 fake。"""
from copy import deepcopy
import select
from types import SimpleNamespace

import pytest

from agentcfg import manager_exit as module
from agentcfg.storage import Conflict


IDENTITY = {"pid": 13371337, "birth_id": "linux:00000000-0000-4000-8000-000000000001:111"}
FD = 8675309
CANARY = "synthetic-private-canary"


@pytest.fixture
def kernel(monkeypatch):
  state = SimpleNamespace(opens=[], closes=[], identities=[], polls=[], registrations=[], events=[],
    inheritable=False, observed=deepcopy(IDENTITY), open_error=None, poll_error=None, close_error=None)
  monkeypatch.setattr(module.sys, "platform", "linux")
  def observe(pid):
    state.identities.append(pid)
    if isinstance(state.observed, BaseException): raise state.observed
    return deepcopy(state.observed)
  def open_fd(pid, flags):
    state.opens.append((pid, flags))
    if state.open_error is not None: raise state.open_error
    return FD
  real_close = module.os.close
  def close(fd):
    if fd != FD: return real_close(fd)
    state.closes.append(fd)
    if state.close_error is not None: raise state.close_error
  class Poll:
    def register(self, fd, flags): state.registrations.append((fd, flags))
    def poll(self, timeout):
      state.polls.append(timeout)
      if state.poll_error is not None: raise state.poll_error
      return deepcopy(state.events)
  monkeypatch.setattr(module.run_owners, "observed_process_identity", observe)
  monkeypatch.setattr(module.os, "pidfd_open", open_fd)
  monkeypatch.setattr(module.os, "get_inheritable", lambda fd: state.inheritable if fd == FD else pytest.fail("unexpected fd"))
  monkeypatch.setattr(module.os, "close", close)
  monkeypatch.setattr(module.select, "poll", Poll)
  def forbidden(*args, **kwargs): pytest.fail("exit observation cannot send signals")
  monkeypatch.setattr(module.os, "kill", forbidden)
  return state


def test_alive_then_exit_uses_original_handle_without_reopening_or_reobserving(kernel):
  identity = deepcopy(IDENTITY)
  with module.ManagerExit(identity) as handle:
    identity["birth_id"] = "external-change"
    assert handle.exited() is False
    kernel.observed = None
    kernel.events = [(FD, select.POLLIN)]
    assert handle.exited() is True
    kernel.events = [(FD, select.POLLIN | select.POLLHUP)]
    assert handle.exited() is True
    assert kernel.opens == [(IDENTITY["pid"], 0)]
    assert kernel.identities == [IDENTITY["pid"], IDENTITY["pid"]]
    assert kernel.polls == [0, 0, 0, 0]
    assert all(item == (FD, select.POLLIN | select.POLLERR | select.POLLHUP) for item in kernel.registrations)
  assert kernel.closes == [FD]
  handle.close()
  assert kernel.closes == [FD]
  with pytest.raises(Conflict): handle.exited()
  assert not hasattr(handle, "send_signal") and not hasattr(handle, "send_sigterm_once")


@pytest.mark.parametrize("identity", [None, True, {}, {**IDENTITY, "pid": True}, {**IDENTITY, "pid": 0},
  {**IDENTITY, "birth_id": ""}, {**IDENTITY, "extra": 1}])
def test_bad_identity_fails_before_open(kernel, identity):
  with pytest.raises(Conflict): module.ManagerExit(identity)
  assert kernel.opens == [] and kernel.closes == []


def test_nonlinux_fails_without_observing_or_opening(kernel, monkeypatch):
  monkeypatch.setattr(module.sys, "platform", "darwin")
  with pytest.raises(Conflict): module.ManagerExit(IDENTITY)
  assert not kernel.identities and not kernel.opens


@pytest.mark.parametrize("observation", [None, {**IDENTITY, "birth_id": "reused"},
  PermissionError(CANARY), ProcessLookupError(CANARY)])
def test_initial_observation_unknown_or_reused_is_not_exit(kernel, observation):
  kernel.observed = observation
  with pytest.raises(Conflict) as caught: module.ManagerExit(IDENTITY)
  assert CANARY not in str(caught.value) and not kernel.opens and not kernel.closes


@pytest.mark.parametrize("observation", [None, {**IDENTITY, "birth_id": "reused"},
  PermissionError(CANARY), ProcessLookupError(CANARY)])
def test_identity_change_after_open_closes_handle_without_poll(kernel, monkeypatch, observation):
  def open_fd(pid, flags):
    kernel.opens.append((pid, flags)); kernel.observed = observation
    return FD
  monkeypatch.setattr(module.os, "pidfd_open", open_fd)
  with pytest.raises(Conflict) as caught: module.ManagerExit(IDENTITY)
  assert CANARY not in str(caught.value)
  assert kernel.closes == [FD] and not kernel.polls


@pytest.mark.parametrize("error", [PermissionError(CANARY), ProcessLookupError(CANARY), OSError(CANARY)])
def test_open_failure_does_not_claim_exit_or_close_unowned_fd(kernel, error):
  kernel.open_error = error
  with pytest.raises(Conflict) as caught: module.ManagerExit(IDENTITY)
  assert CANARY not in str(caught.value) and not kernel.closes


def test_inheritable_handle_is_rejected_and_closed(kernel):
  kernel.inheritable = True
  with pytest.raises(Conflict): module.ManagerExit(IDENTITY)
  assert kernel.closes == [FD] and not kernel.polls


@pytest.mark.parametrize("events", [[(FD, select.POLLIN)], [(FD, select.POLLIN | select.POLLHUP)]])
def test_already_exited_at_capture_is_rejected_and_closed(kernel, events):
  kernel.events = events
  with pytest.raises(Conflict): module.ManagerExit(IDENTITY)
  assert kernel.closes == [FD]


@pytest.mark.parametrize("events", [[(FD, select.POLLERR)], [(FD, select.POLLNVAL)], [(FD, select.POLLHUP)],
  [(FD, select.POLLOUT)], [(FD, select.POLLIN | select.POLLERR)], [(FD, select.POLLIN | select.POLLNVAL)],
  [(FD + 1, select.POLLIN)], [(FD, select.POLLIN), (FD, select.POLLIN)]])
def test_invalid_poll_events_never_prove_exit(kernel, events):
  with module.ManagerExit(IDENTITY) as handle:
    kernel.events = events
    with pytest.raises(Conflict): handle.exited()
  assert kernel.closes == [FD] and len(kernel.opens) == 1


@pytest.mark.parametrize("error", [OSError(CANARY), PermissionError(CANARY), ProcessLookupError(CANARY)])
def test_poll_failure_does_not_reopen_or_send(kernel, error):
  with module.ManagerExit(IDENTITY) as handle:
    kernel.poll_error = error
    with pytest.raises(Conflict) as caught: handle.exited()
    assert CANARY not in str(caught.value)
  assert kernel.closes == [FD] and len(kernel.opens) == 1


@pytest.mark.parametrize("error", [KeyboardInterrupt(CANARY), SystemExit(7)])
@pytest.mark.parametrize("stage", ["observe-after-open", "initial-poll", "later-poll"])
def test_control_exceptions_propagate_and_owned_fd_is_closed(kernel, monkeypatch, error, stage):
  if stage == "observe-after-open":
    def open_fd(pid, flags): kernel.observed = error; return FD
    monkeypatch.setattr(module.os, "pidfd_open", open_fd)
  elif stage == "initial-poll": kernel.poll_error = error
  if stage == "later-poll":
    with pytest.raises(type(error)) as caught:
      with module.ManagerExit(IDENTITY) as handle:
        kernel.poll_error = error
        handle.exited()
  else:
    with pytest.raises(type(error)) as caught: module.ManagerExit(IDENTITY)
  assert caught.value is error and kernel.closes == [FD]


def test_close_oserror_is_suppressed_without_retry_or_reusing_fd(kernel):
  handle = module.ManagerExit(IDENTITY)
  kernel.close_error = OSError(CANARY)
  handle.close(); handle.close()
  assert kernel.closes == [FD]
  with pytest.raises(Conflict): handle.exited()


def test_body_exception_is_not_changed_by_ordinary_close_failure(kernel):
  error = KeyboardInterrupt(CANARY)
  kernel.close_error = OSError(CANARY)
  with pytest.raises(KeyboardInterrupt) as caught:
    with module.ManagerExit(IDENTITY): raise error
  assert caught.value is error and kernel.closes == [FD]


@pytest.mark.parametrize("fd", [None, True, -1, 1.0, "1337"])
def test_bad_pidfd_result_does_not_close_unowned_number(kernel, monkeypatch, fd):
  monkeypatch.setattr(module.os, "pidfd_open", lambda *a: fd)
  with pytest.raises(Conflict): module.ManagerExit(IDENTITY)
  assert not kernel.closes and not kernel.polls


@pytest.mark.parametrize("error", [OSError(CANARY), KeyboardInterrupt(CANARY), SystemExit(7)])
def test_inheritability_observation_failure_closes_owned_handle(kernel, monkeypatch, error):
  def fail(fd): raise error
  monkeypatch.setattr(module.os, "get_inheritable", fail)
  with pytest.raises(Conflict if isinstance(error, Exception) else type(error)) as caught:
    module.ManagerExit(IDENTITY)
  if not isinstance(error, Exception): assert caught.value is error
  else: assert CANARY not in str(caught.value)
  assert kernel.closes == [FD]


def test_empty_or_none_poll_never_reports_exit(kernel):
  with module.ManagerExit(IDENTITY) as handle:
    kernel.events = None
    assert handle.exited() is False
    kernel.events = []
    assert handle.exited() is False
  assert kernel.closes == [FD]
