"""已证实退出后的 owner 锁竞争；真实临时 fd，不启动宿主。"""

from copy import deepcopy
import errno
import fcntl
import json
import os
import threading
import time

import pytest

from agentcfg import resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_owners import RUN, MANAGER, setup_case, held, attach, owner_path


@pytest.fixture(autouse=True)
def synthetic_manager(monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))


def proof():
  return run_owners.ReleaseObservation(RUN, deepcopy(MANAGER), True, True)


def dispatched(root):
  ws, domain, cache, anchor = setup_case(root)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    owners.dispatch_owner(domain, RUN, **args)
  return ws, domain, cache, anchor


def pending(domain, args, monkeypatch):
  original = Tree.replace
  def replace(tree, name, data, *a, **kw):
    if name == RUN + ".json" and json.loads(data).get("lifecycle_state") == "idle_confirmed":
      raise OSError("synthetic-before-owner-idle")
    return original(tree, name, data, *a, **kw)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict):
      owners.finish_owner(domain, RUN, observation=proof(), **args)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "release_pending"


def invoke(phase, domain, args):
  operation = owners.finish_owner if phase == "dispatched" else owners.reconcile_owner_release
  return operation(domain, RUN, observation=proof(), **args)


def contend(ws, domain, operation, monkeypatch):
  """查询持 owner EX 时，退出线程不得持 Domain 等待查询结束。"""
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  original = fcntl.flock
  busy_seen, done = threading.Event(), threading.Event()
  outcome, owner_attempts = [], []
  with registry._locked() as query:
    registry._records(query)
    identity = os.fstat(query.fd)
    key = (identity.st_dev, identity.st_ino)
    def flock(fd, operation):
      current = os.fstat(fd)
      if fd != query.fd and (current.st_dev, current.st_ino) == key and operation & fcntl.LOCK_EX:
        assert operation & fcntl.LOCK_NB, "不能在 Domain 内阻塞等待 owner"
        owner_attempts.append(operation)
        try:
          return original(fd, operation)
        except BlockingIOError:
          busy_seen.set()
          raise
      return original(fd, operation)
    monkeypatch.setattr(fcntl, "flock", flock)
    def worker():
      try:
        outcome.append(operation())
      except BaseException as error:
        outcome.append(error)
      finally:
        done.set()
    thread = threading.Thread(target=worker)
    thread.start()
    try:
      assert busy_seen.wait(1), "未观察到真实 owner 锁竞争"
      deadline = time.monotonic() + 0.5
      domain_available = False
      with Tree(domain.root) as independent:
        while time.monotonic() < deadline and not done.is_set():
          try:
            original(independent.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
          except BlockingIOError:
            time.sleep(0.001)
          else:
            original(independent.fd, fcntl.LOCK_UN)
            domain_available = True
            break
      assert domain_available, "等待 owner 期间必须释放 Domain，而不是提前失败"
      assert not done.is_set(), "查询仍持 owner 锁，退出操作不应提前放弃"
    finally:
      original(query.fd, fcntl.LOCK_UN)
      thread.join(timeout=3)
  assert not thread.is_alive(), "退出操作未在有界时间内结束"
  assert outcome == [RUN], outcome
  assert owner_attempts


@pytest.mark.parametrize("phase", ["dispatched", "release_pending"])
def test_release_waits_for_readonly_owner_query_without_holding_domain(tmp_path, monkeypatch, phase):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    if phase == "release_pending":
      pending(domain, args, monkeypatch)
    contend(ws, domain, lambda: invoke(phase, domain, args), monkeypatch)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "released"
  assert json.loads(owner_path(ws).read_bytes())["lifecycle_state"] == "idle_confirmed"


@pytest.mark.parametrize("phase", ["dispatched", "release_pending"])
def test_release_owner_wait_budget_exhaustion_never_publishes(tmp_path, monkeypatch, phase):
  monkeypatch.setattr(owners, "_RELEASE_LOCK_WAIT_NS", 50_000_000)
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    if phase == "release_pending":
      pending(domain, args, monkeypatch)
    before_domain = (domain.root / "coordination.json").read_bytes()
    before_owner = owner_path(ws).read_bytes()
    registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
    with registry._locked() as query:
      registry._records(query)
      started = time.monotonic()
      with pytest.raises(Conflict):
        invoke(phase, domain, args)
      elapsed = time.monotonic() - started
    assert 0.03 <= elapsed < 0.5
    assert (domain.root / "coordination.json").read_bytes() == before_domain
    assert owner_path(ws).read_bytes() == before_owner


@pytest.mark.parametrize("target", ["pending", "owner-idle", "released"])
def test_release_write_response_loss_never_retries_even_with_eagain(tmp_path, monkeypatch, target):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = Tree.replace
  calls = []
  def replace(tree, name, data, *a, **kw):
    value = json.loads(data)
    phase = value.get("reservations", {}).get(RUN, {}).get("phase")
    matches = (name == "coordination.json" and phase == {
      "pending": "release_pending", "released": "released"}.get(target)) or (
      target == "owner-idle" and name == RUN + ".json" and value.get("lifecycle_state") == "idle_confirmed")
    if matches:
      calls.append(name)
      result = original(tree, name, data, *a, **kw)
      if len(calls) == 1:
        raise BlockingIOError(errno.EAGAIN, "synthetic-committed-response-loss")
      return result
    return original(tree, name, data, *a, **kw)
  monkeypatch.setattr(Tree, "replace", replace)
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    owners.finish_owner(domain, RUN, observation=proof(), **args)
  assert len(calls) == 1
  saved = domain.snapshot()["reservations"][RUN]
  assert saved["phase"] == ("released" if target == "released" else "release_pending")


def test_release_does_not_retry_owner_permission_error(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  before_domain = (domain.root / "coordination.json").read_bytes()
  before_owner = owner_path(ws).read_bytes()
  info = (ws.state_root / "run-owners").stat()
  original = fcntl.flock
  attempts = []
  def flock(fd, operation):
    current = os.fstat(fd)
    if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino) and operation & fcntl.LOCK_EX:
      attempts.append(operation)
      raise PermissionError(errno.EACCES, "synthetic-owner-permission-error")
    return original(fd, operation)
  monkeypatch.setattr(fcntl, "flock", flock)
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    owners.finish_owner(domain, RUN, observation=proof(), **args)
  assert len(attempts) == 1
  assert (domain.root / "coordination.json").read_bytes() == before_domain
  assert owner_path(ws).read_bytes() == before_owner


@pytest.mark.parametrize("phase", ["dispatched", "release_pending"])
@pytest.mark.parametrize("shared", [False, True])
def test_release_waits_for_first_domain_lock_before_any_body(tmp_path, monkeypatch, phase, shared):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = fcntl.flock
  busy, done = threading.Event(), threading.Event()
  outcome = []
  with held(ws, cache, anchor) as args:
    if phase == "release_pending": pending(domain, args, monkeypatch)
    with Tree(domain.root) as query:
      original(query.fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
      key = (os.fstat(query.fd).st_dev, os.fstat(query.fd).st_ino)
      def flock(fd, operation):
        info = os.fstat(fd)
        if fd != query.fd and (info.st_dev, info.st_ino) == key and operation & fcntl.LOCK_EX:
          assert operation & fcntl.LOCK_NB
          try: return original(fd, operation)
          except BlockingIOError:
            busy.set()
            raise
        return original(fd, operation)
      monkeypatch.setattr(fcntl, "flock", flock)
      def worker():
        try: outcome.append(invoke(phase, domain, args))
        except BaseException as error: outcome.append(error)
        finally: done.set()
      thread = threading.Thread(target=worker)
      thread.start()
      try:
        assert busy.wait(1), "必须实际遇到独立 Domain fd 竞争"
        assert not done.wait(0.02), "首次锁未取得时应等待，不能放弃本次完整退出观察"
      finally:
        original(query.fd, fcntl.LOCK_UN)
        thread.join(timeout=3)
      assert not thread.is_alive() and outcome == [RUN], outcome
  assert domain.snapshot()["reservations"][RUN]["phase"] == "released"
  assert json.loads(owner_path(ws).read_bytes())["lifecycle_state"] == "idle_confirmed"


@pytest.mark.parametrize("phase", ["dispatched", "release_pending"])
def test_first_domain_lock_expiry_keeps_both_original_records(tmp_path, monkeypatch, phase):
  monkeypatch.setattr(owners, "_RELEASE_LOCK_WAIT_NS", 50_000_000)
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    if phase == "release_pending": pending(domain, args, monkeypatch)
    before_domain = (domain.root / "coordination.json").read_bytes()
    before_owner = owner_path(ws).read_bytes()
    with Tree(domain.root) as query:
      fcntl.flock(query.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with pytest.raises(Conflict): invoke(phase, domain, args)
    assert (domain.root / "coordination.json").read_bytes() == before_domain
    assert owner_path(ws).read_bytes() == before_owner


def test_first_domain_permission_error_is_not_retried(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  key = (domain.root.stat().st_dev, domain.root.stat().st_ino)
  original = fcntl.flock
  attempts = []
  def flock(fd, operation):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == key and operation & fcntl.LOCK_EX:
      attempts.append(operation)
      raise PermissionError(errno.EACCES, "synthetic domain permission failure")
    return original(fd, operation)
  with held(ws, cache, anchor) as args:
    before = (domain.root / "coordination.json").read_bytes()
    monkeypatch.setattr(fcntl, "flock", flock)
    with pytest.raises(Conflict): invoke("dispatched", domain, args)
    assert attempts and len(attempts) == 1
    assert (domain.root / "coordination.json").read_bytes() == before


def test_domain_busy_from_entered_body_does_not_repeat_release(tmp_path, monkeypatch):
  from agentcfg.resource_coordination import DomainLockBusy
  ws, domain, cache, anchor = dispatched(tmp_path)
  calls = []
  def nested(*args, **kwargs):
    calls.append("body")
    raise DomainLockBusy("synthetic nested transaction contention")
  with held(ws, cache, anchor) as args:
    before = (domain.root / "coordination.json").read_bytes()
    monkeypatch.setattr(owners, "_check_link", nested)
    with pytest.raises(Conflict): invoke("dispatched", domain, args)
    assert calls == ["body"]
    assert (domain.root / "coordination.json").read_bytes() == before
