"""真实临时派发记录与假内核/通道；不发信号，不操作真实pidfd或宿主。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import run_owners
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_executor import StopRequestHandler
from agentcfg.storage import Conflict, Tree
from test_rotom_spawned_host import fake, capture, stat, MANAGER, IDENTITY


RUN = "a" * 32


@pytest.fixture
def controlled(fake, tmp_path, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(fake.manager))
  journal = StopDispatches(tmp_path / "dispatches",
    {"machine": "workstation", "local": "/synthetic/machine.toml", "profile": "dsh-default"})
  handle = capture(fake)
  case = SimpleNamespace(fake=fake, journal=journal, host=handle, now=1000000000, events=[], signals=[])
  case.request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
    "request_id": "b" * 32, "batch_id": "c" * 32, "plan_id": "d" * 64,
    "run_id": RUN, "manager_identity": deepcopy(MANAGER), "host_identity": deepcopy(IDENTITY),
    "deadline_ns": 2000000000}
  def verify(request):
    assert request == case.request
    case.events.append("verify")
    return True
  def send(host):
    assert host is handle
    assert journal.read(RUN)["dispatch"] == "unknown"
    case.events.append("send"); case.signals.append(host)
  case.verify, case.send = verify, send
  case.handler = StopRequestHandler(RUN, handle, journal, verify=verify, send=send, clock=lambda: case.now)
  return case


def test_intent_precedes_channel_and_verification_repeats_after_sync(controlled, monkeypatch):
  case = controlled; write = Tree.write_new
  def observe(tree, name, *args, **kwargs):
    case.events.append("intent" if name == RUN + ".json" else "sent")
    return write(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_new", observe)
  assert case.handler.handle(case.request) == {"run_id": RUN, "request_id": "b" * 32, "dispatch": "signal_sent"}
  assert case.events == ["verify", "intent", "verify", "send", "sent"]
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"
  assert case.signals == [case.host] and case.fake.closes == []
  with pytest.raises(Conflict): case.handler.handle(case.request)
  assert case.events == ["verify", "intent", "verify", "send", "sent"]


@pytest.mark.parametrize("change", ["run", "manager", "host", "action", "extra", "expired", "too-far"])
def test_invalid_target_or_deadline_never_verifies_writes_or_sends(controlled, change):
  case = controlled; request = deepcopy(case.request)
  if change == "run": request["run_id"] = "f" * 32
  elif change in ("manager", "host"): request[change + "_identity"]["birth_id"] = "other-birth"
  elif change == "action": request["action"] = "force"
  elif change == "extra": request["text"] = "synthetic-private-canary"
  elif change == "expired": request["deadline_ns"] = case.now
  else: request["deadline_ns"] = case.now + 301000000000
  with pytest.raises(Conflict) as caught: case.handler.handle(request)
  assert "synthetic-private-canary" not in str(caught.value)
  assert case.events == case.signals == [] and not case.journal.root.exists()


@pytest.mark.parametrize("answer", [False, None, 1, "true"])
def test_verify_requires_explicit_true_and_cannot_mutate_bound_request(controlled, answer):
  case = controlled
  def reject(request):
    request["run_id"] = "f" * 32
    return answer
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=reject, send=case.send, clock=lambda: case.now)
  with pytest.raises(Conflict): handler.handle(case.request)
  assert case.request["run_id"] == RUN and not case.journal.root.exists() and not case.signals


@pytest.mark.parametrize("drift", ["host", "manager", "deadline", "clock-rollback", "approval"])
def test_change_during_intent_publication_preserves_unknown_without_send(controlled, monkeypatch, drift):
  case = controlled; write = Tree.write_new
  def changed(tree, name, *args, **kwargs):
    result = write(tree, name, *args, **kwargs)
    if name == RUN + ".json":
      if drift == "host": case.fake.stat = stat(start="100")
      elif drift == "manager": case.fake.manager["birth_id"] = "different"
      elif drift == "deadline": case.now = case.request["deadline_ns"]
      elif drift == "clock-rollback": case.now -= 1
    return result
  calls = []
  def verify(request):
    calls.append(True)
    return not (drift == "approval" and len(calls) == 2)
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=verify, send=case.send, clock=lambda: case.now)
  monkeypatch.setattr(Tree, "write_new", changed)
  with pytest.raises(Conflict): handler.handle(case.request)
  assert not case.signals and case.journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): handler.handle(case.request)
  assert not case.signals


@pytest.mark.parametrize("stage", ["intent-before", "intent-after", "send", "sent-before", "sent-after"])
def test_ambiguous_dispatch_never_retries_even_with_new_request_id(controlled, monkeypatch, stage):
  case = controlled; write = Tree.write_new
  def failed(tree, name, *args, **kwargs):
    kind = "intent" if name == RUN + ".json" else "sent"
    if stage == kind + "-before": raise OSError("synthetic-private-canary")
    result = write(tree, name, *args, **kwargs)
    if stage == kind + "-after": raise OSError("synthetic-private-canary")
    return result
  def send(host):
    case.send(host)
    if stage == "send": raise OSError("synthetic-private-canary")
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=case.verify, send=send, clock=lambda: case.now)
  monkeypatch.setattr(Tree, "write_new", failed)
  with pytest.raises(Conflict) as caught: handler.handle(case.request)
  assert "synthetic-private-canary" not in str(caught.value)
  signals = len(case.signals)
  assert signals == (0 if stage.startswith("intent") else 1)
  with pytest.raises(Conflict): handler.handle({**case.request, "request_id": "e" * 32})
  assert len(case.signals) == signals
  saved = case.journal.read(RUN)
  assert (saved is None) == (stage == "intent-before")
  if saved: assert saved["dispatch"] == ("signal_sent" if stage == "sent-after" else "unknown")


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_control_exception_after_dispatch_intent_stays_unknown_and_original(controlled, error):
  case = controlled; original = error("synthetic-control")
  def interrupted(host):
    case.send(host)
    raise original
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=case.verify,
    send=interrupted, clock=lambda: case.now)
  with pytest.raises(error) as caught: handler.handle(case.request)
  assert caught.value is original and len(case.signals) == 1
  assert case.journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): handler.handle(case.request)


def test_clock_expiry_during_send_still_records_already_sent_fact(controlled):
  case = controlled
  def send(host):
    case.send(host)
    case.now = case.request["deadline_ns"] + 1
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=case.verify, send=send, clock=lambda: case.now)
  assert handler.handle(case.request)["dispatch"] == "signal_sent"
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"


def test_expired_request_still_preserves_monotonic_clock_history(controlled):
  case = controlled
  case.now = 4000000000
  with pytest.raises(Conflict): case.handler.handle(case.request)
  assert not case.journal.root.exists()
  case.now = 3000000000
  case.request["deadline_ns"] = 5000000000
  with pytest.raises(Conflict): case.handler.handle(case.request)
  assert not case.journal.root.exists() and not case.signals


@pytest.mark.parametrize("argument", ["host", "journal", "verify", "send", "clock", "run"])
def test_untrusted_constructor_cannot_bind_serialized_host_or_missing_callbacks(controlled, argument):
  case = controlled
  args = {"run_id": RUN, "host": case.host, "journal": case.journal,
    "verify": case.verify, "send": case.send, "clock": lambda: case.now}
  if argument == "host": args["host"] = case.host.snapshot()
  elif argument == "run": args["run_id"] = "not-a-run"
  else: args[argument] = object()
  with pytest.raises(Conflict): StopRequestHandler(**args)
  assert not case.journal.root.exists() and not case.signals
