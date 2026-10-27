"""Domain 只在首次元数据锁前等待；真实独立 FD，无宿主。"""
from contextlib import contextmanager
import errno
import fcntl
import os
import threading
import time

import pytest

from agentcfg import resource_coordination as core
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_coordination import enrolled, owner, RUN_A, OP_A


@contextmanager
def held(domain, *, shared=False, release=False):
  fd = os.open(domain.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
  timer = None
  released = threading.Event()
  def unlock():
    fcntl.flock(fd, fcntl.LOCK_UN)
    released.set()
  try:
    if release:
      timer = threading.Timer(0.05, unlock)
      timer.start()
    yield released
  finally:
    if timer is not None:
      timer.cancel()
      timer.join()
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@pytest.mark.parametrize("shared", [False, True])
def test_default_write_waits_only_before_first_body(tmp_path, shared):
  domain = core.initialize_domain(tmp_path / "domain")
  calls = []
  with held(domain, shared=shared, release=True) as released:
    with domain._transaction(write=True) as state:
      calls.append(state["revision"])
  assert released.is_set() and calls == [0]
  assert domain.snapshot()["revision"] == 1


@pytest.mark.parametrize("write", [False, True])
def test_original_deadline_does_not_renew_and_expiry_never_enters_body(tmp_path, write):
  domain = core.initialize_domain(tmp_path / "domain")
  before = (domain.root / "coordination.json").read_bytes()
  deadline = time.monotonic_ns() + 30_000_000
  with held(domain):
    with pytest.raises(Conflict):
      with domain._transaction(write=write, deadline_ns=deadline):
        pytest.fail("expired first lock entered body")
  assert time.monotonic_ns() >= deadline
  assert (domain.root / "coordination.json").read_bytes() == before


def test_default_read_remains_nonblocking(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  monkeypatch.setattr(time, "sleep", lambda _: pytest.fail("default read waited"))
  with held(domain):
    with pytest.raises(core.DomainLockBusy):
      domain.snapshot()


def test_first_permission_error_is_not_retried(tmp_path, monkeypatch):
  domain = core.initialize_domain(tmp_path / "domain")
  before = (domain.root / "coordination.json").read_bytes()
  attempts = []
  def flock(fd, operation):
    attempts.append(operation)
    raise PermissionError(errno.EACCES, "synthetic permission")
  monkeypatch.setattr(fcntl, "flock", flock)
  with pytest.raises(Conflict):
    with domain._transaction(write=True):
      pytest.fail("permission failure entered body")
  assert attempts == [fcntl.LOCK_EX | fcntl.LOCK_NB]
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("failure", ["body-eagain", "body-busy", "commit-eagain", "commit-busy", "unlock-eagain"])
def test_entered_transaction_is_never_replayed(tmp_path, monkeypatch, failure):
  domain = core.initialize_domain(tmp_path / "domain")
  body, writes = [], []
  original_replace, original_flock = Tree.replace, fcntl.flock
  def error():
    return core.DomainLockBusy("synthetic nested busy") if failure.endswith("busy") else BlockingIOError(errno.EAGAIN, "synthetic after entry")
  def replace(tree, name, data, **kwargs):
    writes.append(name)
    result = original_replace(tree, name, data, **kwargs)
    if failure.startswith("commit"):
      raise error()
    return result
  def flock(fd, operation):
    result = original_flock(fd, operation)
    if failure == "unlock-eagain" and operation == fcntl.LOCK_UN:
      raise error()
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    patch.setattr(fcntl, "flock", flock)
    with pytest.raises(Conflict):
      with domain._transaction(write=True):
        body.append(True)
        if failure.startswith("body"):
          raise error()
  assert body == [True]
  assert len(writes) == (0 if failure.startswith("body") else 1)
  assert domain.snapshot()["revision"] == (0 if failure.startswith("body") else 1)


def test_locked_reserve_preserves_cas_and_returns_only_after_commit(tmp_path, monkeypatch):
  domain, cache, anchor = enrolled(tmp_path)
  revision = domain.snapshot()["revision"]
  values = {"run_id": RUN_A, "op_id": OP_A, "owner_ref": owner(tmp_path),
    "resources": [anchor["resource_id"]], "expected_revision": revision}
  with domain._transaction(write=True) as state:
    with pytest.raises(Conflict):
      domain._reserve_locked(state, **(values | {"expected_revision": revision - 1}))
    receipt = domain._reserve_locked(state, **values)
    assert receipt == state["reservations"][RUN_A]
    receipt["phase"] = "unknown"
    assert state["reservations"][RUN_A]["phase"] == "reserved"
  assert domain.snapshot()["reservations"][RUN_A]["phase"] == "reserved"
  domain2, cache2, anchor2 = enrolled(tmp_path / "second")
  def fail(*args, **kwargs):
    raise OSError("synthetic commit failure")
  monkeypatch.setattr(Tree, "replace", fail)
  with pytest.raises(Conflict):
    domain2.reserve(**(values | {"resources": [anchor2["resource_id"]], "expected_revision": domain2.snapshot()["revision"]}))
