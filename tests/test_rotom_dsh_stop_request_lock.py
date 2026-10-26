"""只读 manager owner 锁竞争；无宿主、真实进程或信号。"""
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop_scope


@pytest.fixture
def guarded(tmp_path, monkeypatch):
  root = tmp_path / "owners"; root.mkdir(mode=0o700)
  state = {"now": 1000000000, "locks": [], "sleeps": [], "checked": 0}
  def verify(tree): state["checked"] += 1
  registry = SimpleNamespace(root=root, _verify_root=verify)
  monkeypatch.setattr(dsh_stop_scope.time, "monotonic_ns", lambda: state["now"])
  def sleep(seconds):
    state["sleeps"].append(seconds); state["now"] += int(seconds * 1000000000)
  monkeypatch.setattr(dsh_stop_scope.time, "sleep", sleep)
  def flock(fd, op): state["locks"].append(op)
  monkeypatch.setattr(dsh_stop_scope.fcntl, "flock", flock)
  return registry, state


def test_contention_sleeps_without_lock_and_uses_original_deadline(guarded, monkeypatch):
  registry, state = guarded
  flags = dsh_stop_scope.fcntl
  def flock(fd, op):
    state["locks"].append(op)
    if op != flags.LOCK_UN and len(state["locks"]) < 3: raise BlockingIOError()
  monkeypatch.setattr(flags, "flock", flock)
  with dsh_stop_scope._request_owner(registry, 1100000000):
    assert state["sleeps"] == [0.01, 0.01] and state["checked"] == 1
  assert state["locks"] == [flags.LOCK_EX | flags.LOCK_NB] * 3 + [flags.LOCK_UN]
  assert state["checked"] == 2


def test_contention_expires_without_unlocking_unowned_lock(guarded, monkeypatch):
  registry, state = guarded
  def busy(fd, op):
    state["locks"].append(op); raise BlockingIOError()
  monkeypatch.setattr(dsh_stop_scope.fcntl, "flock", busy)
  with pytest.raises(ValueError):
    with dsh_stop_scope._request_owner(registry, 1005000000): pytest.fail("expired")
  assert state["sleeps"] == [0.005] and len(state["locks"]) == 1


@pytest.mark.parametrize("deadline", [1000000000, 999999999, 301000000001])
def test_expired_or_excessive_budget_never_locks(guarded, deadline):
  registry, state = guarded
  with pytest.raises(ValueError):
    with dsh_stop_scope._request_owner(registry, deadline): pytest.fail("invalid")
  assert state["locks"] == [] and state["sleeps"] == []


@pytest.mark.parametrize("failure", ["io", "clock", "root", "body", "after-deadline"])
def test_non_contention_error_never_retries_and_owned_lock_is_released(guarded, monkeypatch, failure):
  registry, state = guarded
  if failure == "io":
    def fail(fd, op): state["locks"].append(op); raise PermissionError()
    monkeypatch.setattr(dsh_stop_scope.fcntl, "flock", fail)
  elif failure == "clock":
    calls = iter([1000000000, 999999999])
    monkeypatch.setattr(dsh_stop_scope.time, "monotonic_ns", lambda: next(calls))
  elif failure == "root":
    def fail(tree): raise ValueError()
    registry._verify_root = fail
  with pytest.raises((ValueError, PermissionError)):
    with dsh_stop_scope._request_owner(registry, 1100000000):
      if failure == "body": raise ValueError()
      if failure == "after-deadline": state["now"] = 1100000000
  assert state["sleeps"] == []
  if failure != "io": assert state["locks"][-1] == dsh_stop_scope.fcntl.LOCK_UN
