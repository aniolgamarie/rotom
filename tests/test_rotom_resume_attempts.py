"""恢复请求事实独立于真实会话观察；临时私人文件和合成 owner。"""

from dataclasses import replace
import importlib
import json
import os

import pytest

from agentcfg import run_owners, sessions
from agentcfg.dsh_sessions import scope_key
from agentcfg.storage import Conflict, StateError, Tree
from test_rotom_run_records import store, v2_record


@pytest.fixture
def attempt_store(store):
  module = importlib.import_module("agentcfg.resume_attempts")
  owner = v2_record(store)
  target = sessions.KnownSession(sessions.SessionRef("dsh", "managed",
    run_owners.native_home_key(owner["native_home_ref"]), "synthetic-session"),
    scope_key(store.binding), store.binding["profile"], str(store.cwd), "historical", "historical", 1, "b" * 32)
  journal = module.ResumeAttempts(store.registry.root.parent / "resume-attempts", store.binding)
  return journal, target, owner


def test_read_absent_is_read_only(attempt_store):
  journal, target, owner = attempt_store
  assert journal.read(owner["run_id"]) is None
  assert not journal.root.exists()


def test_request_intent_and_spawn_exit_never_become_loaded(attempt_store):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  record = journal.read(owner["run_id"])
  assert record["dispatch"]["state"] == "intent" and record["exit_code"] is None
  assert record["requested"]["session"]["native_ref"] == "synthetic-session"
  assert record["requested"]["cwd"] == target.cwd
  assert record["requested"]["previous_run_id"] == target.run_id
  assert record["load_confirmation"] == "unknown" and record["continue_status"] == "not_sent"
  assert owner["session_observation"] is None and owner["session_cwd"] is None
  assert journal.root.stat().st_mode & 0o777 == 0o700
  assert (journal.root / (owner["run_id"] + ".json")).stat().st_mode & 0o777 == 0o600
  handle.launched()
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "launched"
  handle.exited(0)
  record = journal.read(owner["run_id"])
  assert record["exit_code"] == 0 and record["load_confirmation"] == "unknown"
  with pytest.raises(Conflict):
    journal.begin(target, owner)
  assert journal.read(owner["run_id"]) == record


@pytest.mark.parametrize("field", ["scope", "profile", "cwd", "run_id", "backend", "home"])
def test_wrong_owner_binding_refuses_before_any_write(attempt_store, field):
  journal, target, owner = attempt_store
  if field in ("scope", "profile"):
    target = replace(target, **{field: "other"})
  elif field == "cwd":
    target = replace(target, cwd=str(journal.root.parent))
  elif field == "run_id":
    target = replace(target, run_id=owner["run_id"])
  else:
    target = replace(target, ref=replace(target.ref,
      **{"native_home_ref" if field == "home" else field: "other"}))
  with pytest.raises(Conflict):
    journal.begin(target, owner)
  assert not journal.root.exists()


@pytest.mark.parametrize("field,value", [("lifecycle_state", "unknown"), ("schema_version", 1),
  ("extra", "synthetic-secret"), ("manager_identity", {"pid": True, "birth_id": "example"})])
def test_invalid_owner_never_creates_journal(attempt_store, field, value):
  journal, target, owner = attempt_store
  owner[field] = value
  with pytest.raises(Conflict):
    journal.begin(target, owner)
  assert not journal.root.exists()


@pytest.mark.parametrize("code", [True, -1, 256, 0.0, None, "0"])
def test_invalid_exit_is_not_saved(attempt_store, code):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  handle.launched()
  before = journal.read(owner["run_id"])
  with pytest.raises(Conflict):
    handle.exited(code)
  assert journal.read(owner["run_id"]) == before


def test_no_exit_before_spawn_or_repeated_launch(attempt_store):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  with pytest.raises(Conflict):
    handle.exited(0)
  handle.launched()
  with pytest.raises(Conflict):
    handle.launched()
  handle.exited(17)
  with pytest.raises(Conflict):
    handle.exited(0)
  assert journal.read(owner["run_id"])["exit_code"] == 17


@pytest.mark.parametrize("failure_stage", ["before", "after"])
def test_lost_spawn_write_keeps_intent_then_native_exit_can_record_facts(attempt_store, monkeypatch, failure_stage):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  original = Tree.replace
  def broken(tree, *args, **kwargs):
    if failure_stage == "after":
      original(tree, *args, **kwargs)
    raise StateError("synthetic disk failure")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", broken)
    with pytest.raises(StateError):
      handle.launched()
  assert journal.read(owner["run_id"])["dispatch"]["state"] == ("intent" if failure_stage == "before" else "launched")
  handle.exited(7)
  result = journal.read(owner["run_id"])
  assert result["dispatch"]["state"] == "launched" and result["exit_code"] == 7
  assert result["load_confirmation"] == "unknown"


@pytest.mark.parametrize("change", ["unknown-field", "loaded", "exit-with-intent", "bool-time", "float-time", "manager", "binding", "request", "duplicate", "permissions", "symlink"])
def test_corrupt_saved_record_cannot_be_read_or_overwritten(attempt_store, change):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  path = journal.root / (owner["run_id"] + ".json")
  record = json.loads(path.read_bytes())
  if change == "unknown-field": record["text"] = "synthetic-secret"
  elif change == "loaded": record["load_confirmation"] = "confirmed"
  elif change == "exit-with-intent": record["exit_code"] = 0
  elif change in ("bool-time", "float-time"):
    record["dispatch"]["observed_at_ns"] = True if change == "bool-time" else 1.0
  elif change == "manager": record["manager_identity"]["pid"] = True
  elif change == "binding": record["binding_digest"] = "0" * 64
  elif change == "request": record["requested"]["session"]["native_ref"] = "other"
  if change == "duplicate":
    path.write_text('{"schema_version":1,' + path.read_text()[1:])
  elif change == "permissions": path.chmod(0o644)
  elif change == "symlink":
    original = journal.root.parent / "synthetic-original.json"
    path.rename(original)
    path.symlink_to(original)
  else: path.write_text(json.dumps(record))
  before = path.read_bytes()
  # 合法但被换掉的请求只能由持有原始身份的写入者发现，读取不冒充真实性证明。
  if change != "request":
    with pytest.raises(Conflict): journal.read(owner["run_id"])
  with pytest.raises(Conflict): handle.launched()
  assert path.read_bytes() == before


def test_replaced_root_does_not_receive_old_handle_updates(attempt_store):
  journal, target, owner = attempt_store
  handle = journal.begin(target, owner)
  journal.root.rename(journal.root.with_name("saved-attempts"))
  journal.root.mkdir(mode=0o700)
  saved = journal.root.with_name("saved-attempts") / (owner["run_id"] + ".json")
  replacement = journal.root / saved.name
  replacement.write_bytes(saved.read_bytes())
  replacement.chmod(0o600)
  before = replacement.read_bytes()
  with pytest.raises(Conflict): handle.launched()
  assert replacement.read_bytes() == before


def test_intent_fsync_failure_is_not_safe_to_replay(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  original = Tree.write_new
  def lost(tree, *args, **kwargs):
    original(tree, *args, **kwargs)
    raise StateError("synthetic acknowledgement lost")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", lost)
    with pytest.raises(StateError): journal.begin(target, owner)
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"
  with pytest.raises(Conflict): journal.begin(target, owner)


def test_native_only_previous_run_is_null_through_intent_launch_exit_projection(attempt_store):
  journal, target, owner = attempt_store
  target = replace(target, run_id=None)
  handle = journal.begin(target, owner)
  record = journal.read(owner["run_id"])
  assert record["requested"]["previous_run_id"] is None
  assert record["run_id"] == owner["run_id"]
  assert journal.for_owner(owner)["previous_run_id"] is None
  handle.launched()
  handle.exited(0)
  record = journal.read(owner["run_id"])
  assert record["requested"]["previous_run_id"] is None
  assert record["dispatch"]["state"] == "launched" and record["exit_code"] == 0
  assert journal.for_owner(owner)["status"] == "launch_dispatched"
  assert owner["session_observation"] is None and owner["session_cwd"] is None
  assert record["load_confirmation"] == "unknown" and record["continue_status"] == "not_sent"
  with pytest.raises(Conflict):
    journal.begin(target, owner)


def test_parent_sync_precedes_return_of_resume_attempt(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  fsync = os.fsync; parent = journal.root.parent.stat(); seen = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
      assert (journal.root / (owner["run_id"] + ".json")).is_file()
      seen.append("parent")
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  journal.begin(target, owner)
  assert seen == ["parent"]


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_parent_sync_failure_preserves_intent_and_forbids_resume_replay(attempt_store, monkeypatch, kind):
  journal, target, owner = attempt_store
  fsync = os.fsync; parent = journal.root.parent.stat(); error = kind("synthetic-private-canary")
  def failed(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino): raise error
    return fsync(fd)
  with monkeypatch.context() as patch:
    patch.setattr(os, "fsync", failed)
    with pytest.raises(Conflict if kind is OSError else kind) as caught: journal.begin(target, owner)
  if kind is OSError: assert "synthetic-private-canary" not in str(caught.value)
  else: assert caught.value is error
  assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"
  with pytest.raises(Conflict): journal.begin(target, owner)


def test_root_replaced_during_parent_sync_cannot_return_resume_attempt(attempt_store, monkeypatch):
  journal, target, owner = attempt_store
  fsync = os.fsync; parent = journal.root.parent.stat(); changed = []
  def sync(fd):
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino) and not changed:
      changed.append(True)
      journal.root.rename(journal.root.with_name("saved-attempts"))
      journal.root.mkdir(mode=0o700)
    return fsync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  with pytest.raises(Conflict): journal.begin(target, owner)
  assert changed and list(journal.root.iterdir()) == []


@pytest.mark.parametrize("previous", [True, 1, 1.0, "", "invalid"])
def test_nullable_previous_run_still_rejects_invalid_nonnull_identity(attempt_store, previous):
  journal, target, owner = attempt_store
  journal.begin(target, owner)
  path = journal.root / (owner["run_id"] + ".json")
  record = json.loads(path.read_bytes())
  record["requested"]["previous_run_id"] = previous
  path.write_text(json.dumps(record))
  with pytest.raises(Conflict):
    journal.read(owner["run_id"])
