"""短元数据锁竞争只等待原截止点；真实临时目录、fake 时间，无宿主/信号。"""
from copy import deepcopy
import fcntl
from types import SimpleNamespace

import pytest

from agentcfg import stop_locks, run_owners
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.storage import Conflict
from test_rotom_stop_dispatches import dispatches, RUN
from test_rotom_stop_inbox import case as inbox_case, create, snapshot
from test_rotom_stop_service import case as service_case, build, submit
from test_rotom_stop_executor import controlled, fake


@pytest.fixture
def clock(monkeypatch):
  state = SimpleNamespace(now=0, sleeps=[], action=None)
  monkeypatch.setattr(stop_locks.time, "monotonic_ns", lambda: state.now)
  def sleep(seconds):
    assert 0 < seconds <= 0.01
    state.sleeps.append(seconds)
    state.now += max(1, int(seconds * 1000000000))
    if state.action is not None:
      action, state.action = state.action, None
      action()
  monkeypatch.setattr(stop_locks.time, "sleep", sleep)
  return state


def test_poll_busy_does_not_read_or_fail_service_and_next_tick_reads(service_case, clock, monkeypatch):
  case = service_case; current = build(case); submit(case)
  original = case.inbox._load; reads = []
  def load(tree): reads.append(True); return original(tree)
  monkeypatch.setattr(case.inbox, "_load", load)
  with case.inbox._registry._locked(nonblocking=True):
    assert current() is None
    assert not reads and current.belongs_to(RUN, case.host)
    with pytest.raises(Conflict): case.inbox.pending(expected=current._endpoint)
  assert current()["dispatch"] == "signal_sent" and len(case.signals) == 1
  assert reads and not clock.sleeps


@pytest.mark.parametrize("damage", ["malformed", "missing", "nonce"])
def test_poll_corruption_is_not_busy(inbox_case, damage):
  inbox = inbox_case; endpoint = create(inbox)
  path = inbox.root / "endpoint.json"
  if damage == "malformed": path.write_bytes(b"synthetic-private-canary")
  elif damage == "missing": path.unlink()
  else:
    value = deepcopy(endpoint); value["nonce"] = "d" * 32
    path.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict) as caught: inbox.pending(expected=endpoint, poll=True)
  assert "synthetic-private-canary" not in str(caught.value)


def test_poll_missing_root_fails_without_creation(inbox_case):
  with pytest.raises(Conflict): inbox_case.pending(expected={}, poll=True)
  assert not inbox_case.root.exists()


def test_describe_waits_only_to_original_deadline_then_can_read(inbox_case, clock):
  inbox = inbox_case; endpoint = create(inbox)
  held = inbox._registry._locked(nonblocking=True); held.__enter__()
  clock.action = lambda: held.__exit__(None, None, None)
  try:
    assert inbox.describe(deadline_ns=50000000) == endpoint
  finally:
    if clock.action is not None: held.__exit__(None, None, None)
  assert clock.sleeps == [0.01] and clock.now == 10000000


def test_describe_competition_never_rearms_budget(inbox_case, clock):
  inbox = inbox_case; create(inbox); before = snapshot(inbox.root)
  with inbox._registry._locked(nonblocking=True):
    with pytest.raises(Conflict): inbox.describe(deadline_ns=25000000)
  assert clock.now == 25000000
  assert clock.sleeps == [0.01, 0.01, 0.005]
  assert snapshot(inbox.root) == before
  with pytest.raises(Conflict): inbox.describe(deadline_ns=25000000)
  assert len(clock.sleeps) == 3


@pytest.mark.parametrize("waiting", [False, True])
def test_begin_short_contention_waits_only_when_opted_in(dispatches, clock, monkeypatch, waiting):
  case = dispatches; journal = StopDispatches(case.root, case.binding, wait_for_lock=waiting)
  original = fcntl.flock; attempts = []
  def flock(fd, operation):
    if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
      attempts.append(operation)
      if len(attempts) <= 2:
        assert not (case.root / (RUN + ".json")).exists()
        raise BlockingIOError()
    return original(fd, operation)
  monkeypatch.setattr(fcntl, "flock", flock)
  if waiting:
    attempt = journal.begin(case.request)
    assert attempt is not None and len(attempts) == 3 and len(clock.sleeps) == 2
    assert journal.read(RUN)["dispatch"] == "unknown"
  else:
    with pytest.raises(Conflict): journal.begin(case.request)
    assert len(attempts) == 1 and not clock.sleeps
    assert not (case.root / (RUN + ".json")).exists()


def test_sent_expired_can_immediately_record_fact_without_sleep(dispatches, clock):
  case = dispatches; journal = StopDispatches(case.root, case.binding, wait_for_lock=True)
  attempt = journal.begin(case.request)
  clock.now = case.request["deadline_ns"] + 1
  assert attempt.sent() is None
  assert journal.read(RUN)["dispatch"] == "signal_sent" and not clock.sleeps


def test_sent_expired_busy_consumes_attempt_unknown_no_retry(dispatches, clock):
  case = dispatches; journal = StopDispatches(case.root, case.binding, wait_for_lock=True)
  attempt = journal.begin(case.request)
  clock.now = case.request["deadline_ns"] + 1
  with journal._registry._locked(nonblocking=True):
    with pytest.raises(Conflict): attempt.sent()
  assert not clock.sleeps and journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): attempt.sent()
  assert journal.read(RUN)["dispatch"] == "unknown"


@pytest.mark.parametrize("value", [None, 1, "yes"])
def test_wait_for_lock_requires_exact_bool(dispatches, value):
  with pytest.raises(Conflict): StopDispatches(dispatches.root, dispatches.binding, wait_for_lock=value)
  assert not dispatches.root.exists()


@pytest.mark.parametrize("deadline", [None, True, 0, -1, 1.0, 2**63, 300000000001])
def test_invalid_deadline_has_no_creation_or_sleep(dispatches, clock, deadline):
  with pytest.raises(Conflict):
    with stop_locks.locked(dispatches.journal._registry, deadline, create=True): pytest.fail("invalid deadline")
  assert not dispatches.root.exists() and not clock.sleeps


def test_clock_backwards_during_busy_wait_is_not_retried(inbox_case, clock):
  create(inbox_case); clock.now = 10
  clock.action = lambda: setattr(clock, "now", 9)
  with inbox_case._registry._locked(nonblocking=True):
    with pytest.raises(Conflict): inbox_case.describe(deadline_ns=100000000)
  assert len(clock.sleeps) == 1


def test_check_after_rejects_expiry_and_releases_lock(inbox_case, clock):
  create(inbox_case)
  with pytest.raises(Conflict):
    with stop_locks.locked(inbox_case._registry, 100, check_after=True): clock.now = 100
  with inbox_case._registry._locked(nonblocking=True): pass


@pytest.mark.parametrize("error", [PermissionError("synthetic-private-canary"), OSError("synthetic-private-canary")])
def test_nonbusy_lock_error_never_waits(inbox_case, clock, monkeypatch, error):
  create(inbox_case)
  def fail(*args): raise error
  monkeypatch.setattr(fcntl, "flock", fail)
  with pytest.raises(Conflict) as caught:
    with stop_locks.try_locked(inbox_case._registry): pytest.fail("not busy")
  assert "synthetic-private-canary" not in str(caught.value) and not clock.sleeps


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_control_exception_in_body_preserves_original_and_unlocks(inbox_case, clock, error):
  create(inbox_case)
  with pytest.raises(type(error)) as caught:
    with stop_locks.locked(inbox_case._registry, 100): raise error
  assert caught.value is error
  with inbox_case._registry._locked(nonblocking=True): pass


def test_sent_contention_expires_original_budget_and_keeps_unknown(dispatches, clock):
  case = dispatches
  value = deepcopy(case.request); value["deadline_ns"] = 25000000
  journal = StopDispatches(case.root, case.binding, wait_for_lock=True)
  attempt = journal.begin(value)
  with journal._registry._locked(nonblocking=True):
    with pytest.raises(Conflict): attempt.sent()
  assert clock.now == 25000000 and clock.sleeps == [0.01, 0.01, 0.005]
  assert journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): attempt.sent()
  assert len(clock.sleeps) == 3


def test_service_two_endpoint_checks_share_request_deadline(service_case, clock, monkeypatch):
  case = service_case; current = build(case)
  original = case.inbox.describe; deadlines = []
  def describe(deadline_ns=None):
    deadlines.append(deadline_ns)
    return original(deadline_ns=deadline_ns)
  monkeypatch.setattr(case.inbox, "describe", describe)
  assert current._verify_request(case.request) is True
  assert deadlines == [case.request["deadline_ns"], case.request["deadline_ns"]]


@pytest.mark.parametrize("allow,contended", [(False, False), (True, True)])
def test_acquisition_time_consumes_budget_even_after_success(inbox_case, clock, monkeypatch, allow, contended):
  create(inbox_case); original = fcntl.flock; attempts = []; body = []
  def flock(fd, operation):
    if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
      attempts.append(True)
      if contended and len(attempts) == 1: raise BlockingIOError()
      original(fd, operation)
      clock.now = 25000000
      return
    return original(fd, operation)
  monkeypatch.setattr(fcntl, "flock", flock)
  with pytest.raises(Conflict):
    with stop_locks.locked(inbox_case._registry, 25000000, allow_expired_once=allow): body.append(True)
  assert body == []
  with inbox_case._registry._locked(nonblocking=True): pass


@pytest.mark.parametrize("mode", ["locked", "try_locked"])
def test_root_replaced_after_read_is_rejected(inbox_case, clock, mode):
  create(inbox_case)
  guard = (stop_locks.locked(inbox_case._registry, 100) if mode == "locked"
    else stop_locks.try_locked(inbox_case._registry))
  old = inbox_case.root.with_name("moved-inbox")
  with pytest.raises(Conflict):
    with guard:
      inbox_case.root.rename(old)
      inbox_case.root.mkdir(mode=0o700)
  assert (old / "endpoint.json").exists() and not (inbox_case.root / "endpoint.json").exists()
