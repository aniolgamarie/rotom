"""恢复位置请求先落盘、一次交接；元数据不能重放宿主。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.storage import Conflict
from test_rotom_tool_maintenance import workflow, update, BATCH, RUNS


def request(root):
  return {"schema_version": 1, "request_id": "a" * 32, "mode": "new-tab",
    "scope": {"machine": "fixture", "local": str(root / "local.toml"), "profile": "pi-base", "agent": "pi"},
    "batch_id": "b" * 32, "run_id": "c" * 32,
    "session_ref": {"agent": "pi", "backend": "managed", "native_home_ref": "native-home", "native_ref": "session-example"},
    "cwd": str(root), "deployment_digest": "d" * 64, "workflow_revision": 3,
    "workflow_digest": "e" * 64, "manager_code_identity": "f" * 64,
    "terminal_ref": None, "rotom_root": str(root / "repository")}


def test_missing_reads_do_not_create(tmp_path):
  from agentcfg.restore_locations import LocationStore
  store = LocationStore(tmp_path / "request")
  assert store.read_request() is None and store.read_receipt() is None
  assert not store.root.exists()


def test_intent_is_immutable_and_receipt_cas_is_single_use(tmp_path):
  from agentcfg.restore_locations import LocationStore
  store = LocationStore(tmp_path / "request")
  value = request(tmp_path)
  saved = store.create(value)
  assert {key: item for key, item in saved.items() if key != "root_identity"} == value
  assert store.read_request() == saved
  first = store.read_receipt()
  assert first["phase"] == "prepared"
  following = {**first, "phase": "dispatched"}
  assert store.transition(first, following) == following
  with pytest.raises(Conflict):
    store.transition(first, following)
  with pytest.raises(Conflict):
    store.create(value)
  assert store.read_request() == saved


@pytest.mark.parametrize("damage", ["unknown", "version-bool", "float", "bad-cwd", "wrong-agent", "command"])
def test_invalid_request_cannot_create(tmp_path, damage):
  from agentcfg.restore_locations import LocationStore
  value = request(tmp_path)
  if damage == "unknown": value["extra"] = "unexpected"
  if damage == "version-bool": value["schema_version"] = True
  if damage == "float": value["workflow_revision"] = 1.0
  if damage == "bad-cwd": value["cwd"] = "/tmp/../escape"
  if damage == "wrong-agent": value["session_ref"]["agent"] = "dsh"
  if damage == "command": value["argv"] = ["sh", "-c", "never"]
  store = LocationStore(tmp_path / "request")
  with pytest.raises(Conflict): store.create(value)
  assert not store.root.exists()


@pytest.mark.parametrize("phase", ["unknown", "failed"])
def test_unknown_or_failed_does_not_allow_replay(tmp_path, phase):
  from agentcfg.restore_locations import LocationStore
  store = LocationStore(tmp_path / "request")
  store.create(request(tmp_path))
  first = store.read_receipt()
  terminal = store.transition(first, {**first, "phase": phase, "reason": "synthetic-failure"})
  with pytest.raises(Conflict): store.transition(terminal, {**terminal, "phase": "dispatched"})


def test_partial_create_and_duplicate_keys_preserve_evidence(tmp_path):
  from agentcfg.restore_locations import LocationStore
  store = LocationStore(tmp_path / "request")
  store.root.mkdir(mode=0o700)
  broken = store.root / "request.json"
  broken.write_text('{"schema_version":1,"schema_version":1}')
  broken.chmod(0o600)
  before = broken.read_bytes()
  with pytest.raises(Conflict): store.read_request()
  with pytest.raises(Conflict): store.create(request(tmp_path))
  assert broken.read_bytes() == before


def terminal(cwd):
  return {"socket_path": "/tmp/synthetic-herdr.sock", "server_identity": [1, 2],
    "workspace_id": "workspace-a", "tab_id": "tab-a", "pane_id": "pane-a", "terminal_id": "terminal-a", "cwd": cwd}


def handoff(store):
  first = store.read_receipt()
  first = store.transition(first, {**first, "phase": "dispatched"})
  first = store.transition(first, {**first, "phase": "ready", "terminal_ref": terminal(store.read_request()["cwd"])})
  first = store.transition(first, {**first, "phase": "committed"})
  return store.transition(first, {**first, "phase": "handoff"})


def test_reserved_location_blocks_normal_restore_and_launches_once(workflow, monkeypatch):
  from agentcfg.restore_locations import reserve
  from agentcfg import tool_maintenance as flow
  from rotom.restore_child import execute
  from termcfg import work
  monkeypatch.setattr(work, "source_digest", lambda *args: "f" * 64)
  state = workflow
  update(state)
  store = reserve(state.ws, BATCH, RUNS[0], mode="new-tab")
  assert flow.status(state.ws, BATCH)["restores"][RUNS[0]]["action"] == "restore-intent"
  with pytest.raises(Conflict):
    flow.restore(state.ws, BATCH, run_id=RUNS[0], launch=lambda *args, **kwargs: pytest.fail("reserved replay"))
  handoff(store)
  launched = []
  def launch(target, **kwargs):
    assert store.read_receipt()["phase"] == "executing"
    launched.append((target, kwargs))
    return 17
  assert execute(store, load_workspace=lambda *args: state.ws, verify=lambda ref: True, launch=launch) == 17
  assert store.read_receipt()["phase"] == "exited" and len(launched) == 1
  assert flow.status(state.ws, BATCH)["restores"][RUNS[0]]["exit_code"] == 17
  with pytest.raises(Conflict):
    execute(store, load_workspace=lambda *args: state.ws, verify=lambda ref: True, launch=launch)
  assert len(launched) == 1


@pytest.mark.parametrize("damage", ["cancel", "workflow-digest", "session", "cwd", "deployment"])
def test_reserved_restore_rechecks_original_intent_before_agent(workflow, monkeypatch, damage):
  from agentcfg.restore_locations import reserve
  from agentcfg import tool_maintenance as flow
  from termcfg import work
  monkeypatch.setattr(work, "source_digest", lambda *args: "f" * 64)
  state = workflow
  update(state)
  store = reserve(state.ws, BATCH, RUNS[0], mode="new-tab")
  request = store.read_request()
  if damage == "cancel":
    value = flow.Store(state.ws, BATCH).read()
    flow.Store(state.ws, BATCH).append(value, "cancel")
  elif damage == "workflow-digest": request["workflow_digest"] = "0" * 64
  elif damage == "session": request["session_ref"]["native_ref"] = "different-session"
  elif damage == "cwd": request["cwd"] = str(state.ws.instance)
  elif damage == "deployment": request["deployment_digest"] = "0" * 64
  with pytest.raises(Conflict):
    flow.restore_reserved(state.ws, request, launch=lambda *args, **kwargs: pytest.fail("invalid reservation launched"))


def test_request_directory_replacement_is_rejected_by_fresh_reader(tmp_path):
  from agentcfg.restore_locations import LocationStore
  store = LocationStore(tmp_path / "request")
  store.create(request(tmp_path))
  content = {name: (store.root / name).read_bytes() for name in ("request.json", "receipt.json")}
  store.root.rename(tmp_path / "old-request")
  store.root.mkdir(mode=0o700)
  for name, data in content.items():
    (store.root / name).write_bytes(data)
    (store.root / name).chmod(0o600)
  with pytest.raises(Conflict): LocationStore(store.root).read_request()


def test_cancel_during_reserved_lookup_prevents_agent_dispatch(workflow, monkeypatch):
  from agentcfg.restore_locations import reserve
  from agentcfg import tool_maintenance as flow
  from termcfg import work
  monkeypatch.setattr(work, "source_digest", lambda *args: "f" * 64)
  state = workflow
  update(state)
  store = reserve(state.ws, BATCH, RUNS[0], mode="new-tab")
  original_lookup = flow.lookup_session
  def cancel_then_lookup(*args):
    current = flow.Store(state.ws, BATCH).read()
    flow.Store(state.ws, BATCH).append(current, "cancel")
    return original_lookup(*args)
  monkeypatch.setattr(flow, "lookup_session", cancel_then_lookup)
  with pytest.raises(Conflict):
    flow.restore_reserved(state.ws, store.read_request(), launch=lambda *args, **kwargs: pytest.fail("cancelled launch"))


def test_internal_child_bad_root_has_static_error(tmp_path, capsys):
  from rotom.restore_child import main
  assert main(["--request-root", "relative-root"]) == 4
  assert "Traceback" not in capsys.readouterr().err
