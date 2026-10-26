"""输入接收假原型；不向宿主、模型、剪贴板、PTY 或 shell 输入。"""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from agentcfg.sessions import SessionRef
from agentcfg.storage import Conflict
from test_rotom_resume_cli import setup as resume_setup


BODY = "synthetic-approved-private-body"


@pytest.fixture
def module(monkeypatch):
  path = Path(__file__).parent / "fixtures/rotom/input-channel-probe.py"
  spec = importlib.util.spec_from_file_location("rotom_input_probe", path)
  value = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, spec.name, value)
  spec.loader.exec_module(value)
  return value


@pytest.fixture
def case(module):
  def build():
    agent = object()
    target = module.InputTarget("a" * 32, SessionRef("dsh", "managed", "home-a", "session-a"),
      agent, 1, True, True, True, True)
    current = [target]
    trace, intents = [], []
    class Transport:
      calls = 0
      listener = None
      subscribe_hook = None
      send_hook = None
      unsubscribe_hook = None
      def subscribe(self, listener):
        trace.append("subscribe")
        self.listener = listener
        if self.subscribe_hook:
          self.subscribe_hook(listener)
        def cancel():
          trace.append("unsubscribe")
          if self.unsubscribe_hook:
            self.unsubscribe_hook(listener)
          self.listener = None
        return cancel
      def followup(self, selected, message_id, approved_text):
        # 此签名是 fake 接缝，非宿主 UserMessage 构造器；正文仅在调用栈检查。
        assert selected is agent and approved_text == BODY
        self.calls += 1
        trace.append("send")
        if self.send_hook:
          self.send_hook(message_id)
        else:
          self.listener({"agent": agent, "message": {"id": message_id}})
    transport = Transport()
    persist_hook = [None]
    def persist(intent):
      trace.append("persist")
      intents.append(dict(intent))
      if persist_hook[0]:
        persist_hook[0]()
    probe = module.InputProbe(target, transport=transport,
      current_target=lambda: current[0], persist_intent=persist)
    return probe, transport, current, trace, intents, persist_hook
  return build


def request(probe):
  return probe.request_followup(BODY)


def unknown(probe):
  with pytest.raises(Conflict) as error:
    request(probe)
  assert error.value.__cause__ is None and BODY not in str(error.value)
  assert probe.snapshot()["status"] == "unknown"


def test_subscribe_before_single_send_and_digest_only_intent(case):
  import hashlib
  probe, transport, _, trace, intents, _ = case()
  result = request(probe)
  assert trace == ["persist", "subscribe", "send", "unsubscribe"]
  assert transport.calls == 1 and result["status"] == "accepted"
  assert result["execution_complete"] is False and result["cross_restart_deduplication"] is False
  assert intents[0]["text_sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
  assert intents[0]["message_id"] == result["message_id"]
  assert BODY not in json.dumps(intents) + repr(vars(probe)) + json.dumps(result)
  with pytest.raises(Conflict):
    request(probe)
  assert transport.calls == 1


def test_unique_message_identity_for_independent_attempts(case):
  first, second = case(), case()
  assert request(first[0])["message_id"] != request(second[0])["message_id"]


@pytest.mark.parametrize("change", [{"run_id": "b" * 32}, {"session": SessionRef("dsh", "managed", "home-a", "other")},
  {"agent": object()}, {"foreground_generation": 2}, {"input_ready": False},
  {"writer_covered": False}, {"load_confirmed": False}, {"observation_complete": False}])
@pytest.mark.parametrize("stage", ["before", "persist", "subscribe"])
def test_target_changes_at_each_boundary_prevent_any_send(case, change, stage):
  probe, transport, current, _, intents, persist_hook = case()
  def mutate(*args):
    current[0] = replace(current[0], **change)
  if stage == "before":
    mutate()
  elif stage == "persist":
    persist_hook[0] = mutate
  else:
    transport.subscribe_hook = mutate
  unknown(probe)
  assert transport.calls == 0
  assert len(intents) == (0 if stage == "before" else 1)
  unknown(probe)
  assert transport.calls == 0


@pytest.mark.parametrize("event", ["wrong-agent", "old-id", "malformed", "duplicate", "conflict", "missing"])
def test_wrong_old_duplicate_conflicting_or_missing_insertions_stay_unknown(case, event):
  probe, transport, current, _, intents, _ = case()
  def send(message_id):
    correct = {"agent": current[0].agent, "message": {"id": message_id}}
    if event in ("duplicate", "conflict"):
      transport.listener(correct)
    if event == "missing":
      return
    payload = {"agent": object() if event == "wrong-agent" else current[0].agent,
      "message": {"id": "old-message" if event in ("old-id", "conflict") else message_id}}
    transport.listener(None if event == "malformed" else payload)
  transport.send_hook = send
  unknown(probe)
  unknown(probe)
  assert transport.calls == 1 and len(intents) == 1


@pytest.mark.parametrize("stage", ["subscribe", "unsubscribe"])
def test_matching_insertion_outside_send_window_is_not_accepted(case, stage):
  probe, transport, current, _, intents, _ = case()
  def early_or_late(listener):
    listener({"agent": current[0].agent, "message": {"id": intents[0]["message_id"]}})
  setattr(transport, stage + "_hook", early_or_late)
  unknown(probe)
  assert transport.calls == (0 if stage == "subscribe" else 1)


@pytest.mark.parametrize("stage", ["persist", "subscribe", "send", "unsubscribe"])
def test_exceptions_or_response_loss_never_retry_and_never_expose_text(case, stage):
  probe, transport, current, _, intents, persist_hook = case()
  def fail(*args):
    raise OSError(BODY)
  if stage == "persist":
    persist_hook[0] = fail
  elif stage == "send":
    def accepted_then_lost(message_id):
      transport.listener({"agent": current[0].agent, "message": {"id": message_id}})
      fail()
    transport.send_hook = accepted_then_lost
  else:
    setattr(transport, stage + "_hook", fail)
  unknown(probe)
  unknown(probe)
  assert transport.calls == (1 if stage in ("send", "unsubscribe") else 0)
  assert len(intents) == 1 and BODY not in repr(vars(probe)) + json.dumps(intents)


def test_observation_loss_after_matching_event_does_not_claim_acceptance(case):
  probe, transport, current, _, _, _ = case()
  def send(message_id):
    transport.listener({"agent": current[0].agent, "message": {"id": message_id}})
    current[0] = replace(current[0], observation_complete=False)
  transport.send_hook = send
  unknown(probe)
  assert transport.calls == 1


def test_every_actual_tool_remains_unavailable():
  path = Path(__file__).parent / "fixtures/rotom/input-capabilities.json"
  value = json.loads(path.read_text())
  assert value["status"] == "fake-only"
  assert set(value["tools"]) == {"dsh", "pi", "omp"}
  assert all(row["automatic_continue"] == "unavailable" for row in value["tools"].values())


def test_target_change_while_unsubscribing_stays_unknown(case):
  probe, transport, current, _, _, _ = case()
  def change(listener):
    current[0] = replace(current[0], foreground_generation=2)
  transport.unsubscribe_hook = change
  unknown(probe)
  assert transport.calls == 1


@pytest.mark.parametrize("field,value", [("foreground_generation", 2), ("writer_covered", False), ("input_ready", False)])
def test_target_change_during_send_before_insertion_cannot_be_accepted(case, field, value):
  probe, transport, current, _, _, _ = case()
  def send(message_id):
    current[0] = replace(current[0], **{field: value})
    transport.listener({"agent": current[0].agent, "message": {"id": message_id}})
  transport.send_hook = send
  unknown(probe)
  unknown(probe)
  assert transport.calls == 1


def test_missing_cancel_handle_refuses_send(case):
  probe, transport, _, _, _, _ = case()
  transport.subscribe = lambda listener: None
  unknown(probe)
  assert transport.calls == 0


def test_late_callback_after_unsubscribe_cannot_keep_an_accepted_receipt(case):
  probe, transport, current, _, intents, _ = case()
  saved = []
  transport.subscribe_hook = saved.append
  assert request(probe)["status"] == "accepted"
  saved[0]({"agent": current[0].agent, "message": {"id": intents[0]["message_id"]}})
  assert probe.snapshot()["status"] == "unknown"
  unknown(probe)
  assert transport.calls == 1


@pytest.mark.parametrize("change", [{"run_id": None}, {"run_id": "old"}, {"session": None},
  {"agent": None}, {"foreground_generation": True}, {"input_ready": 1}, {"observation_complete": 1}])
def test_fake_preconditions_reject_inexact_or_missing_identity(case, change):
  _, _, current, _, _, _ = case()
  with pytest.raises(Conflict):
    replace(current[0], **change)


def test_ordinary_resume_does_not_use_input_probe(case, resume_setup, monkeypatch):
  from rotom import cli, resume
  probe, transport, _, trace, _, _ = case()
  target, candidate, calls, _, _, loads = resume_setup
  monkeypatch.setattr(resume, "dsh_candidate", candidate)
  assert cli.main(["--no-input", "resume", "dsh", "--session", target.ref.native_ref, "--here"]) == 0
  assert calls == [target] and len(loads) == 1
  assert probe.snapshot()["status"] == "bound" and transport.calls == 0 and trace == []


def test_unencodable_approval_is_fixed_rejection_before_intent_or_send(case):
  probe, transport, _, trace, intents, _ = case()
  with pytest.raises(Conflict) as error:
    probe.request_followup("\ud800" + BODY)
  assert BODY not in str(error.value) and error.value.__cause__ is None
  assert trace == intents == [] and transport.calls == 0
  assert probe.snapshot()["message_id"] is None and probe.snapshot()["text_sha256"] is None
