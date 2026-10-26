"""临时真实inbox/journal和完整fake pidfd/通道；不发真实信号。"""
from copy import copy, deepcopy
import pickle

import pytest

from agentcfg import run_owners, spawned_host, stop_service as service, stop_executor
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.storage import Conflict, Tree
from test_rotom_stop_executor import controlled, fake, RUN
from test_rotom_spawned_host import stat


@pytest.fixture
def case(controlled, tmp_path, monkeypatch):
  case = controlled
  # 锁等待与处理器使用同一个合成单调时钟，保留过期用例的原判断。
  monkeypatch.setattr("agentcfg.stop_locks.time.monotonic_ns", lambda: case.now)
  case.inbox = StopInbox(tmp_path / "inbox", case.journal.binding)
  def signal(fd, number, info, flags):
    assert (fd, number, info, flags) == (77, 15, None, 0)
    return case.send(case.host)
  monkeypatch.setattr(spawned_host.signal, "SIGTERM", 15, raising=False)
  monkeypatch.setattr(spawned_host.signal, "pidfd_send_signal", signal, raising=False)
  return case


def build(case, **overrides):
  options = {"inbox": case.inbox, "journal": case.journal, "verify": case.verify, "clock": lambda: case.now}
  options.update(overrides)
  return service.StopService(RUN, case.host, **options)


def submit(case, request=None):
  case.inbox.submit(case.request if request is None else request, expected=case.inbox.describe())


def test_constructor_order_original_handle_and_empty_tick_do_not_write_journal(case, monkeypatch):
  trace = []; snapshot = spawned_host.SpawnedHost.snapshot; create = StopInbox.create; initialize = stop_executor.StopRequestHandler.__init__
  def observed(host): trace.append("snapshot"); return snapshot(host)
  def created(self, **kwargs): trace.append("create"); result = create(self, **kwargs); trace.append("created"); return result
  def handler(self, *args, **kwargs): trace.append("handler"); initialize(self, *args, **kwargs)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", observed)
  monkeypatch.setattr(StopInbox, "create", created)
  monkeypatch.setattr(stop_executor.StopRequestHandler, "__init__", handler)
  current = build(case)
  assert trace == ["snapshot", "create", "created", "handler", "snapshot", "snapshot"]
  assert current.belongs_to(RUN, case.host) is True and current.belongs_to("f" * 32, case.host) is False
  assert current() is None and not case.journal.root.exists() and case.signals == []
  assert case.fake.closes == []


def test_first_success_only_one_original_host_send_then_no_read_or_replay(case, monkeypatch):
  current = build(case); submit(case)
  assert current() == {"run_id": RUN, "request_id": case.request["request_id"], "dispatch": "signal_sent"}
  assert case.signals == [case.host] and case.journal.read(RUN)["dispatch"] == "signal_sent"
  def forbidden(*args, **kwargs): pytest.fail("completed service must not read inbox again")
  monkeypatch.setattr(StopInbox, "pending", forbidden)
  assert current() is None and current() is None
  assert current.belongs_to(RUN, case.host) is True and case.fake.closes == []
  assert len(list(case.inbox.root.iterdir())) == 2 and len(list(case.journal.root.iterdir())) == 2


def test_multiple_requests_only_sorted_first_is_processed_and_all_files_remain(case):
  current = build(case)
  submit(case, {**case.request, "request_id": "f" * 32}); submit(case)
  assert current()["request_id"] == case.request["request_id"]
  assert current() is None and len(case.signals) == 1
  assert len(case.inbox.pending(expected=case.inbox.describe())) == 2


@pytest.mark.parametrize("change", ["expired", "denied", "not-true", "host-drift"])
def test_unconfirmed_tick_is_permanently_failed_no_replay(case, monkeypatch, change):
  options = {}
  if change in ("denied", "not-true"): options["verify"] = lambda request: False if change == "denied" else 1
  current = build(case, **options)
  if change == "expired": case.now = case.request["deadline_ns"]
  submit(case)
  if change == "host-drift": case.fake.stat = stat(start="100")
  with pytest.raises(Conflict): current()
  calls = []
  monkeypatch.setattr(StopInbox, "pending", lambda *args, **kwargs: calls.append(True) or [])
  with pytest.raises(Conflict): current()
  assert not calls and not case.signals and current.belongs_to(RUN, case.host) is False
  assert not case.journal.root.exists()


@pytest.mark.parametrize("stage", ["intent-before", "intent-after", "sent-before", "sent-after"])
@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_write_fault_response_loss_or_control_preserves_files_never_retries(case, monkeypatch, stage, kind):
  current = build(case); submit(case); original = Tree.write_new; error = kind("synthetic-private-canary")
  def write(tree, name, data):
    phase = "intent" if name == RUN + ".json" else "sent"
    if stage == phase + "-before": raise error
    original(tree, name, data)
    if stage == phase + "-after": raise error
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict if kind is OSError else kind) as caught: current()
  if kind is not OSError: assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  count = len(case.signals)
  assert count == (0 if stage.startswith("intent") else 1)
  saved = case.journal.read(RUN)
  assert (saved is None) == (stage == "intent-before")
  if saved: assert saved["dispatch"] == ("signal_sent" if stage == "sent-after" else "unknown")
  with pytest.raises(Conflict): current()
  assert len(case.signals) == count and not current.belongs_to(RUN, case.host)


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_send_response_loss_is_unknown_and_service_never_retries(case, monkeypatch, kind):
  current = build(case); submit(case); original = case.send; error = kind("synthetic-private-canary")
  def send(host): original(host); raise error
  case.send = send
  with pytest.raises(Conflict if kind is OSError else kind) as caught: current()
  if kind is not OSError: assert caught.value is error
  assert len(case.signals) == 1 and case.journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): current()
  assert len(case.signals) == 1


@pytest.mark.parametrize("stage", ["before", "during"])
def test_verify_checks_pinned_endpoint_before_and_after_user_verify(case, monkeypatch, stage):
  calls = []; original_pending = StopInbox.pending
  def mutate():
    path = case.inbox.root / "endpoint.json"
    value = case.inbox.describe(); value["nonce"] = "f" * 32; path.write_bytes(run_owners._encode(value))
  def verify(request):
    calls.append(True)
    if stage == "during": mutate()
    return True
  current = build(case, verify=verify); submit(case)
  def pending(self, **kwargs):
    result = original_pending(self, **kwargs)
    if stage == "before": mutate()
    return result
  monkeypatch.setattr(StopInbox, "pending", pending)
  with pytest.raises(Conflict): current()
  assert calls == ([] if stage == "before" else [True]) and not case.signals and not case.journal.root.exists()
  with pytest.raises(Conflict): current()


@pytest.mark.parametrize("change", ["inbox-type", "journal-type", "host-type", "verify", "clock", "binding", "same-root", "run"])
def test_invalid_construction_does_not_create_endpoint(case, tmp_path, change):
  options = dict(inbox=case.inbox, journal=case.journal, verify=case.verify, clock=lambda: case.now)
  host, run = case.host, RUN
  if change == "inbox-type": options["inbox"] = {}
  elif change == "journal-type": options["journal"] = {}
  elif change == "host-type": host = object()
  elif change == "verify": options["verify"] = None
  elif change == "clock": options["clock"] = False
  elif change == "binding": options["journal"] = StopDispatches(tmp_path / "other-journal", {**case.journal.binding, "profile": "other"})
  elif change == "same-root": options["journal"] = StopDispatches(case.inbox.root, case.journal.binding)
  else: run = "bad"
  with pytest.raises(Conflict): service.StopService(run, host, **options)
  assert not case.inbox.root.exists() and not case.journal.root.exists() and case.fake.closes == []


def test_existing_endpoint_cannot_construct_new_service(case):
  build(case); before = (case.inbox.root / "endpoint.json").read_bytes()
  with pytest.raises(Conflict): build(case)
  assert (case.inbox.root / "endpoint.json").read_bytes() == before and case.fake.closes == []


def test_constructor_final_host_drift_keeps_already_written_endpoint(case, monkeypatch):
  original = stop_executor.StopRequestHandler.__init__
  def changed(self, *args, **kwargs): original(self, *args, **kwargs); case.fake.stat = stat(start="100")
  monkeypatch.setattr(stop_executor.StopRequestHandler, "__init__", changed)
  with pytest.raises(Conflict): build(case)
  assert (case.inbox.root / "endpoint.json").exists() and not case.journal.root.exists()


def test_close_only_revokes_service_keeps_borrowed_host_and_files(case):
  current = build(case); submit(case); before = (case.inbox.root / "endpoint.json").read_bytes()
  current.close(); current.close()
  assert not current.belongs_to(RUN, case.host) and case.fake.closes == []
  assert case.host.snapshot()["identity"] == case.request["host_identity"]
  with pytest.raises(Conflict): current()
  assert (case.inbox.root / "endpoint.json").read_bytes() == before and not case.signals


def test_copy_aliases_no_serialization_and_same_host_object_required(case):
  current = build(case)
  assert copy(current) is current and deepcopy(current) is current
  assert not current.belongs_to(RUN, object.__new__(spawned_host.SpawnedHost))
  with pytest.raises((TypeError, Conflict)): pickle.dumps(current)
  current.close()
  assert not copy(current).belongs_to(RUN, case.host)


def test_reentrant_failure_cannot_release_outer_lock_or_be_swallowed_into_send(case):
  current = None; inner = []
  def verify(request):
    try: current()
    except Conflict: inner.append(True)
    assert current._lock.acquire(blocking=False) is False
    return True
  current = build(case, verify=verify); submit(case)
  with pytest.raises(Conflict): current()
  assert inner == [True] and not case.signals and not case.journal.root.exists()
  assert current._lock.acquire(blocking=False)
  current._lock.release()
  with pytest.raises(Conflict): current()


def test_reentry_during_sent_receipt_keeps_sent_fact_but_fails_service(case, monkeypatch):
  current = build(case); submit(case); write = Tree.write_new
  def reentered(tree, name, data):
    write(tree, name, data)
    if name == RUN + ".sent.json":
      with pytest.raises(Conflict): current()
  monkeypatch.setattr(Tree, "write_new", reentered)
  with pytest.raises(Conflict): current()
  assert len(case.signals) == 1 and case.journal.read(RUN)["dispatch"] == "signal_sent"
  assert not current.belongs_to(RUN, case.host)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("site", ["pending", "verify"])
def test_read_or_verify_control_exception_is_original_and_permanently_disables(case, monkeypatch, kind, site):
  error = kind("synthetic-private-canary")
  def fail(*args, **kwargs): raise error
  current = build(case, **({"verify": fail} if site == "verify" else {})); submit(case)
  if site == "pending": monkeypatch.setattr(StopInbox, "pending", fail)
  with pytest.raises(kind) as caught: current()
  assert caught.value is error and not current.belongs_to(RUN, case.host)
  with pytest.raises(Conflict): current()
  assert not case.signals and case.fake.closes == [] and not case.journal.root.exists()


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_constructor_interrupt_after_endpoint_publication_keeps_file_without_closing_host(case, monkeypatch, kind):
  original = StopInbox.create; error = kind("synthetic-control")
  def interrupted(self, **kwargs): original(self, **kwargs); raise error
  monkeypatch.setattr(StopInbox, "create", interrupted)
  with pytest.raises(kind) as caught: build(case)
  assert caught.value is error
  assert (case.inbox.root / "endpoint.json").exists() and case.fake.closes == []
  assert case.host.snapshot()["identity"] == case.request["host_identity"]
