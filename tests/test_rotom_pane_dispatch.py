"""位置分发先验证环境再保存意图；未知不自动换终端。"""
from contextlib import contextmanager
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.storage import Conflict
from agentcfg.sessions import SessionError
from rotom import pane_dispatch as dispatch
from rotom.context import InputGateway


def case(tmp_path):
  workspace = SimpleNamespace(agent="pi", profile="pi-base", local_path=tmp_path / "local.toml",
    state_root=tmp_path / "state", binding={"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": "pi-base"})
  gateway = InputGateway(io.StringIO(), io.StringIO(), io.StringIO())
  return workspace, SimpleNamespace(input_gateway=gateway, output_mode="json")


def test_unadmitted_location_does_not_reserve_or_start(tmp_path, monkeypatch):
  workspace, context = case(tmp_path)
  monkeypatch.setattr(dispatch, "_runtime", lambda ws: "synthetic-runtime")
  monkeypatch.setattr(dispatch, "reserve", lambda *args, **kwargs: pytest.fail("unadmitted must be read-only"))
  for location in ("original", "new-tab"):
    assert dispatch.dispatch_location(workspace, "a" * 32, "b" * 32, context, location=location) == 5
  assert context.input_gateway.stdout.getvalue() == ""
  assert "--here" in context.input_gateway.stderr.getvalue()
  assert not workspace.state_root.exists()


def test_new_tab_uses_context_manager_and_closes_client(tmp_path, monkeypatch):
  from termcfg import work, work_config, restore_tabs, herdr
  workspace, context = case(tmp_path)
  monkeypatch.setattr(dispatch, "_runtime", lambda ws: "synthetic-runtime")
  monkeypatch.setattr(dispatch, "_admitted", lambda *args: True)
  monkeypatch.setenv("HERDR_PANE_ID", "pane-a")
  events = []
  client = SimpleNamespace(request=lambda *args: {"pane": {"workspace_id": "workspace-a"}})
  settings = object()
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: settings if kwargs == {"local": workspace.local_path} else pytest.fail("scope changed"))
  @contextmanager
  def connected(selected, deadline, *, start):
    assert selected is settings and start is False
    events.append("connect")
    yield client, "prepared-herdr"
    events.append("close")
  monkeypatch.setattr(work, "connected", connected)
  monkeypatch.setattr(herdr, "require_startup_evidence", lambda *args: events.append("verify"))
  store = object()
  def reserve(*args, **kwargs):
    events.append("reserve")
    return store
  monkeypatch.setattr(dispatch, "reserve", reserve)
  def create(actual_client, actual_settings, actual_store, **kwargs):
    assert (actual_client, actual_settings, actual_store) == (client, settings, store)
    assert kwargs == {"workspace_id": "workspace-a", "caller_id": "pane-a"}
    events.append("create")
    return {"request_id": "c" * 32, "created": True, "handoff": True, "phase": "handoff", "terminal_ref": {}}
  monkeypatch.setattr(restore_tabs, "create_restore_tab", create)
  assert dispatch.dispatch_location(workspace, "a" * 32, "b" * 32, context, location="new-tab") == 0
  assert events == ["connect", "verify", "reserve", "create", "close"]
  assert '"load_confirmation": "unknown"' in context.input_gateway.stdout.getvalue()


def test_missing_herdr_never_consumes_restore_intent(tmp_path, monkeypatch):
  from termcfg import work_config
  from termcfg.errors import TermcfgError
  workspace, context = case(tmp_path)
  monkeypatch.setattr(dispatch, "_runtime", lambda ws: "synthetic-runtime")
  monkeypatch.setattr(dispatch, "_admitted", lambda *args: True)
  def unavailable(**kwargs): raise TermcfgError(5, "fixture_unavailable")
  monkeypatch.setattr(work_config, "read_settings", unavailable)
  monkeypatch.setattr(dispatch, "reserve", lambda *args, **kwargs: pytest.fail("Herdr missing must not consume"))
  assert dispatch.dispatch_location(workspace, "a" * 32, "b" * 32, context, location="new-tab") == 5
  assert not workspace.state_root.exists()


@pytest.mark.parametrize("failure_stage", ["reserve", "create"])
def test_create_response_unknown_keeps_request_and_does_not_retry(tmp_path, monkeypatch, failure_stage):
  from termcfg import work, work_config, restore_tabs, herdr
  workspace, context = case(tmp_path)
  monkeypatch.setattr(dispatch, "_runtime", lambda ws: "synthetic-runtime")
  monkeypatch.setattr(dispatch, "_admitted", lambda *args: True)
  monkeypatch.setenv("HERDR_PANE_ID", "pane-a")
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: object())
  @contextmanager
  def connected(*args, **kwargs):
    yield SimpleNamespace(request=lambda *a: {"pane": {"workspace_id": "workspace-a"}}), "binary"
  monkeypatch.setattr(work, "connected", connected)
  monkeypatch.setattr(herdr, "require_startup_evidence", lambda *args: None)
  calls = []
  def reserve(*args, **kwargs):
    calls.append("intent")
    if failure_stage == "reserve":
      raise Conflict("synthetic post-intent persistence failure")
    return object()
  monkeypatch.setattr(dispatch, "reserve", reserve)
  def unknown(*args, **kwargs):
    calls.append("create")
    raise Conflict("synthetic")
  monkeypatch.setattr(restore_tabs, "create_restore_tab", unknown)
  assert dispatch.dispatch_location(workspace, "a" * 32, "b" * 32, context, location="new-tab") == 4
  assert calls == (["intent"] if failure_stage == "reserve" else ["intent", "create"])
  assert context.input_gateway.stdout.getvalue() == ""
  assert "意图已保存或结果未知" in context.input_gateway.stderr.getvalue()


def test_container_lookup_absent_is_read_only(tmp_path, monkeypatch):
  workspace, _ = case(tmp_path)
  monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
  assert dispatch.container_for(workspace, "b" * 32) is None
  assert not (tmp_path / "xdg-state").exists()


@pytest.mark.parametrize("route,allowed", [(None, True), ("local", True), ("ssh", False)])
def test_runtime_gate_distinguishes_local_and_remote_execution(tmp_path, monkeypatch, route, allowed):
  from agentcfg import deployment
  workspace, _ = case(tmp_path)
  workspace.agent = "dsh"
  contract = {"lock_identity": "synthetic-runtime", "environment": [] if route is None else [
    {"name": "AGENTCFG_DSH_EXECUTION", "literal": route, "required": True}]}
  monkeypatch.setattr(deployment, "read_state", lambda state: {"current": {"binding": workspace.binding, "launch": contract}})
  if allowed:
    assert dispatch._runtime(workspace) == "synthetic-runtime"
  else:
    with pytest.raises(SessionError) as error:
      dispatch._runtime(workspace)
    assert error.value.code == 5


def test_herdr_remote_launch_keeps_original_command(tmp_path, monkeypatch, capsys):
  from agentcfg import workspace as workspace_module
  from termcfg import work_config
  workspace, _ = case(tmp_path)
  settings = SimpleNamespace(local_path=workspace.local_path, dsh_profile="dsh-remote")
  monkeypatch.setattr(work_config, "_prepared_agent", lambda *args: {"identity": "same-public-package"})
  monkeypatch.setattr(workspace_module, "load_instance_workspaces", lambda *args, **kwargs: [workspace])
  monkeypatch.setattr(dispatch, "_admitted", lambda *args: True)
  def remote(_workspace):
    raise SessionError(5, "position_requires_local_managed_backend")
  monkeypatch.setattr(dispatch, "_runtime", remote)
  command = ["fixed-rotom", "run", "dsh"]
  assert dispatch.wrap_launch(settings, "dsh", command, tmp_path, None, {}) is command
  assert "原 pane 恢复不可用" in capsys.readouterr().err


def test_incomplete_launch_contract_cannot_break_read_only_location_diagnostics(tmp_path, monkeypatch):
  from agentcfg import deployment
  workspace, _ = case(tmp_path)
  monkeypatch.setattr(deployment, "read_state", lambda state: {"current": {
    "binding": workspace.binding, "launch": {"lock_identity": "legacy-fixture"}}})
  with pytest.raises(Conflict):
    dispatch._runtime(workspace)
  assert dispatch.describe_options(workspace, "a" * 32)["original"]["status"] == "unknown"
  assert not workspace.state_root.exists()


@pytest.fixture
def live_container(tmp_path, monkeypatch):
  from agentcfg import lifecycle, run_owners
  from agentcfg.pane_records import ContainerStore
  from test_rotom_restore_capabilities import terminal
  workspace, _ = case(tmp_path)
  monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "position-state"))
  manager = {"pid": 100, "birth_id": "synthetic-parent"}
  child = {"pid": 200, "birth_id": "synthetic-child"}
  run_id = "b" * 32
  owners = {run_id: {"schema_version": 2, "agent": workspace.agent, "backend": "managed",
    "profile": workspace.profile, "manager_identity": child}}
  reads = []
  @contextmanager
  def observe(selected):
    assert selected is workspace
    reads.append("observe")
    yield
  monkeypatch.setattr(lifecycle, "observation_guard", observe)
  monkeypatch.setattr(run_owners.Registry, "snapshot", lambda registry: owners)
  def create(identifier="e" * 32, **patch):
    root = tmp_path / "position-state/rotom/panes" / identifier
    store = ContainerStore(root, identifier)
    value = {"schema_version": 1, "container_id": identifier, "generation": 1,
      "manager_identity": manager, "terminal_ref": terminal(), "manager_code_identity": "a" * 64,
      "control_protocol": 1, "endpoint_identity": {"path": str(root / "control.sock"), "device": 1, "inode": 2},
      "scope": {"local": str(workspace.local_path), "profile": workspace.profile, "agent": workspace.agent},
      "state": "running", "run_id": None, "child_identity": child,
      "consumed_request_ids": [], "last_request_id": None, **patch}
    store.create(value)
    return store
  return SimpleNamespace(ws=workspace, run=run_id, manager=manager, child=child,
    owners=owners, reads=reads, create=create)


def test_active_container_is_linked_by_exact_birth_without_writing_run(live_container):
  state = live_container
  store = state.create()
  before = store.read()
  found = dispatch.container_for(state.ws, state.run)
  assert found == (store.root, before)
  assert before["run_id"] is None and state.reads == ["observe"]
  assert store.read() == before


@pytest.mark.parametrize("change", ["birth", "agent", "backend", "profile"])
def test_active_container_rejects_reused_pid_or_foreign_owner(live_container, change):
  state = live_container
  state.create()
  owner = state.owners[state.run]
  if change == "birth": owner["manager_identity"] = {**state.child, "birth_id": "reused"}
  else: owner[change] = "other"
  assert dispatch.container_for(state.ws, state.run) is None


def test_foreign_container_scope_does_not_read_selected_owner(live_container):
  state = live_container
  state.create(scope={"local": str(state.ws.local_path), "profile": "other", "agent": state.ws.agent})
  assert dispatch.container_for(state.ws, state.run) is None
  assert state.reads == []


def test_duplicate_live_container_birth_is_not_a_unique_position(live_container):
  state = live_container
  state.create()
  state.create("f" * 32)
  with pytest.raises(Conflict): dispatch.container_for(state.ws, state.run)


@pytest.mark.parametrize("state_name,stored_run", [("running", None), ("parked", "c" * 32)])
def test_original_ready_requires_parked_saved_run_even_for_found_candidate(live_container, monkeypatch, state_name, stored_run):
  from agentcfg import run_owners
  from rotom import resident
  state = live_container
  store = state.create(state=state_name, run_id=stored_run,
    child_identity=None if state_name == "parked" else state.child)
  monkeypatch.setattr(dispatch, "container_for", lambda *args: (store.root, store.read()))
  monkeypatch.setattr(resident, "_source_identity", lambda: "a" * 64)
  monkeypatch.setattr(run_owners, "observed_process_identity", lambda pid: state.manager)
  monkeypatch.setattr(resident, "_verify_terminal", lambda ref: pytest.fail("invalid active/run candidate cannot reach terminal handoff"))
  with pytest.raises(Conflict): dispatch._original_ready(state.ws, state.run)
  assert store.read()["consumed_request_ids"] == []
