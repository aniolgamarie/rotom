"""停止派发先记账且未知不重放；临时文件和虚构 manager。"""

from copy import copy, deepcopy
import json
import os
import pickle
from types import SimpleNamespace

import pytest

from agentcfg import run_owners
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.storage import Conflict, Tree


MANAGER = {"pid": 700001, "birth_id": "synthetic-manager-birth"}
HOST = {"pid": 700002, "birth_id": "synthetic-host-birth"}
RUN = "a" * 32


@pytest.fixture
def dispatches(tmp_path, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  binding = {"machine": "workstation", "local": "/synthetic/machine.toml", "profile": "dsh-default"}
  root = tmp_path / "stop-dispatches"
  journal = StopDispatches(root, binding)
  request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
    "request_id": "b" * 32, "batch_id": "c" * 32, "plan_id": "d" * 64,
    "run_id": RUN, "manager_identity": deepcopy(MANAGER), "host_identity": deepcopy(HOST),
    "deadline_ns": 5000000000}
  return SimpleNamespace(root=root, binding=binding, journal=journal, request=request)


def test_missing_read_never_creates_directory(dispatches):
  case = dispatches
  assert case.journal.read(RUN) is None and not case.root.exists()


def test_intent_then_sent_are_separate_durable_facts_and_never_release(dispatches):
  case = dispatches
  attempt = case.journal.begin(case.request)
  saved = case.journal.read(RUN)
  assert saved == {"request": case.request, "dispatch": "unknown"}
  assert case.root.stat().st_mode & 0o777 == 0o700
  assert (case.root / (RUN + ".json")).stat().st_mode & 0o777 == 0o600
  assert attempt.sent() is None
  assert case.journal.read(RUN) == {"request": case.request, "dispatch": "signal_sent"}
  assert (case.root / (RUN + ".sent.json")).stat().st_mode & 0o777 == 0o600
  with pytest.raises(Conflict): attempt.sent()
  with pytest.raises(Conflict): case.journal.begin(case.request)
  # 新 request/batch 也不能把同一个 run 的可能发送覆盖为新尝试。
  changed = {**case.request, "request_id": "e" * 32, "batch_id": "f" * 32}
  with pytest.raises(Conflict): case.journal.begin(changed)


@pytest.mark.parametrize("damage", ["manager", "invalid", "extra"])
def test_invalid_or_different_current_manager_cannot_create_intent(dispatches, monkeypatch, damage):
  case = dispatches
  if damage == "manager":
    monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "different"})
  elif damage == "invalid": case.request["action"] = "force"
  else: case.request["private-canary"] = "synthetic-secret"
  with pytest.raises(Conflict) as caught: case.journal.begin(case.request)
  assert "synthetic-secret" not in str(caught.value) and not case.root.exists()


@pytest.mark.parametrize("stage", ["before", "after"])
def test_intent_write_failure_never_produces_attempt_or_retries(dispatches, monkeypatch, stage):
  case = dispatches; write = Tree.write_new; calls = []
  def failing(tree, name, *args, **kwargs):
    calls.append(name)
    if stage == "before": raise OSError("synthetic-secret")
    write(tree, name, *args, **kwargs)
    raise OSError("synthetic-secret")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", failing)
    with pytest.raises(Conflict) as caught: case.journal.begin(case.request)
  assert "synthetic-secret" not in str(caught.value) and calls == [RUN + ".json"]
  assert case.journal.read(RUN) == (None if stage == "before" else {"request": case.request, "dispatch": "unknown"})
  if stage == "after":
    with pytest.raises(Conflict): case.journal.begin(case.request)


@pytest.mark.parametrize("stage", ["before", "after"])
def test_sent_result_failure_consumes_attempt_and_preserves_written_facts(dispatches, monkeypatch, stage):
  case = dispatches; attempt = case.journal.begin(case.request); write = Tree.write_new; calls = []
  def failing(tree, name, *args, **kwargs):
    calls.append(name)
    if stage == "before": raise OSError("synthetic-secret")
    write(tree, name, *args, **kwargs)
    raise OSError("synthetic-secret")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", failing)
    with pytest.raises(Conflict) as caught: attempt.sent()
  assert "synthetic-secret" not in str(caught.value) and calls == [RUN + ".sent.json"]
  assert case.journal.read(RUN)["dispatch"] == ("unknown" if stage == "before" else "signal_sent")
  with pytest.raises(Conflict): attempt.sent()


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_sent_control_interrupt_preserves_original_and_consumed_attempt(dispatches, monkeypatch, error):
  case = dispatches; attempt = case.journal.begin(case.request); write = Tree.write_new
  original = error("synthetic-control")
  def interrupt(tree, name, *args, **kwargs):
    write(tree, name, *args, **kwargs)
    raise original
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", interrupt)
    with pytest.raises(error) as caught: attempt.sent()
  assert caught.value is original
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"
  with pytest.raises(Conflict): attempt.sent()


def test_copy_keeps_same_attempt_and_pickle_cannot_recreate_it(dispatches):
  attempt = dispatches.journal.begin(dispatches.request)
  assert copy(attempt) is deepcopy(attempt) is attempt
  with pytest.raises((Conflict, TypeError)): pickle.dumps(attempt)
  attempt.sent()
  with pytest.raises(Conflict): copy(attempt).sent()


def test_new_store_can_read_but_cannot_reconstruct_attempt(dispatches):
  case = dispatches; case.journal.begin(case.request)
  reopened = StopDispatches(case.root, case.binding)
  assert reopened.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): reopened.begin(case.request)


@pytest.mark.parametrize("damage", ["binding", "request", "orphan", "result-digest", "mode", "symlink"])
def test_read_rejects_unpaired_changed_or_unsafe_facts(dispatches, damage):
  case = dispatches; attempt = case.journal.begin(case.request)
  intent = case.root / (RUN + ".json"); result = case.root / (RUN + ".sent.json")
  if damage == "binding":
    changed = {**case.binding, "machine": "another"}
    case.journal = StopDispatches(case.root, changed)
  elif damage == "request":
    attempt.sent()
    value = json.loads(intent.read_bytes()); value["request"]["host_identity"]["birth_id"] = "changed"
    intent.write_bytes(run_owners._encode(value))
  elif damage == "orphan": attempt.sent(); intent.unlink()
  elif damage == "result-digest":
    attempt.sent(); value = json.loads(result.read_bytes()); value["intent_digest"] = "0" * 64
    result.write_bytes(run_owners._encode(value))
  elif damage == "mode": intent.chmod(0o644)
  else:
    target = case.root / "synthetic-file"; intent.rename(target); intent.symlink_to(target)
  with pytest.raises(Conflict): case.journal.read(RUN)


def test_replaced_directory_cannot_receive_result_from_old_attempt(dispatches):
  case = dispatches; attempt = case.journal.begin(case.request)
  raw = (case.root / (RUN + ".json")).read_bytes()
  case.root.rename(case.root.with_name("original")); case.root.mkdir(mode=0o700)
  with Tree(case.root) as tree: tree.write_new(RUN + ".json", raw)
  with pytest.raises(Conflict): attempt.sent()
  assert not (case.root / (RUN + ".sent.json")).exists()


def test_manager_change_after_intent_cannot_record_success(dispatches, monkeypatch):
  case = dispatches; attempt = case.journal.begin(case.request)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "different"})
  with pytest.raises(Conflict): attempt.sent()
  assert case.journal.read(RUN)["dispatch"] == "unknown"


def test_new_journal_parent_is_synced_before_attempt_is_returned(dispatches, monkeypatch):
  case = dispatches; fsync = os.fsync; seen = []
  expected = case.root.parent.stat()
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
      assert (case.root / (RUN + ".json")).is_file()
      seen.append("parent")
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  case.journal.begin(case.request)
  assert seen == ["parent"]


def test_parent_sync_failure_leaves_intent_and_never_returns_attempt(dispatches, monkeypatch):
  case = dispatches; fsync = os.fsync; expected = case.root.parent.stat()
  def failed(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
      raise OSError("synthetic-private-canary")
    return fsync(fd)
  with monkeypatch.context() as patch:
    patch.setattr(os, "fsync", failed)
    with pytest.raises(Conflict) as caught: case.journal.begin(case.request)
    assert "synthetic-private-canary" not in str(caught.value)
  assert case.journal.read(RUN)["dispatch"] == "unknown"
  with pytest.raises(Conflict): case.journal.begin(case.request)
