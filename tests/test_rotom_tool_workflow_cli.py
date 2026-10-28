"""三工具 CLI 新维护流程：真实临时部署/Store/setup，停止和宿主替身。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop, dsh_stop_client, dsh_stop_plan, local, run_owners, tool_maintenance as flow, workspace
from agentcfg.sessions import HostResumeBackend, LaunchReceipt, SessionError
from agentcfg.storage import Conflict
from rotom import cli, maintenance, preferences, resume
from rotom.context import InputGateway
from test_rotom_interaction import Stream
from test_rotom_tool_maintenance import workflow, Progress, RUNS, SESSION, SECOND


_BACKEND_FOR_WORKSPACE = resume.backend_for_workspace


@pytest.fixture
def command(workflow, monkeypatch):
  state = workflow
  ws = state.ws
  state.streams = InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False))
  state.stop_calls, state.backend_calls, state.deployment_bindings = [], [], []
  monkeypatch.setattr(cli, "InputGateway", lambda: state.streams)
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  monkeypatch.setattr(local, "available_profiles", lambda: [(ws.profile, ws.agent)])
  monkeypatch.setattr(workspace, "load_instance_workspaces", lambda path, profiles: [ws] if ws.profile in profiles else [])
  monkeypatch.setattr(workspace, "load_workspace", lambda path, profile: ws)
  monkeypatch.setattr(dsh_stop, "workspace_for_scope", lambda *args, **kwargs: ws)
  monkeypatch.setattr(cli, "_profile_tool", lambda profile: ws.agent)
  def stopped(selected, *, expected_plan, batch_id, approve, wait_seconds):
    assert selected is ws and approve(expected_plan) is True
    state.stop_calls.append((batch_id, deepcopy(expected_plan), wait_seconds))
    state.stop_result["status"] = "stopped"
    return deepcopy(state.stop_result)
  monkeypatch.setattr(dsh_stop_client, "execute_stop", stopped)
  class Backend(HostResumeBackend):
    def resume_session(self, target, *, location, before_dispatch, after_dispatch):
      assert location == "here"
      state.backend_calls.append(target)
      before_dispatch("f" * 32)
      after_dispatch("f" * 32)
      return LaunchReceipt("f" * 32, 17)
  def backend(selected, target, *, expected_deployment):
    assert selected is ws
    state.deployment_bindings.append(expected_deployment)
    return Backend()
  monkeypatch.setattr(resume, "backend_for_workspace", backend)
  state.prefix = ["--no-input", "agent", "--local", str(ws.local_path), "--profile", ws.profile, "maintenance"]
  state.target_args = ["--run", RUNS[0], "--run", RUNS[1], "--session", RUNS[0] + "=" + SESSION,
    "--session", RUNS[1] + "=" + SECOND]
  return state


def invoke(state, action, *args):
  return cli.main([*state.prefix, action, *args, "--format", "json"])


def take(capsys):
  return json.loads(capsys.readouterr().out)


def stopped(state, capsys):
  assert invoke(state, "stop", *state.target_args, "--plan-id", state.plan["plan_id"]) == 0
  result = take(capsys)
  state.batch = result["batch_id"]
  return result


def updated(state, capsys):
  stopped(state, capsys)
  assert invoke(state, "plan", "--batch", state.batch) == 0
  preview = take(capsys)["setup_preview"]
  assert invoke(state, "execute", "--batch", state.batch, "--plan-id", preview["plan_id"]) == 0
  return take(capsys)


def test_three_tool_cli_plan_stop_independent_update_single_restore_and_cancel(command, capsys):
  state = command
  assert invoke(state, "plan", *state.target_args) == 0
  planned = take(capsys)
  assert planned["readonly"] is True and planned["plan_id"] == state.plan["plan_id"]
  assert not (state.ws.state_root / "maintenance-workflows").exists()
  result = updated(state, capsys)
  assert result["status"] == "updated" and (state.ws.instance / "rules.md").read_text() == "B"
  assert len(state.stop_calls) == 1 and len(state.syncs) == 1
  assert result["next_commands"]["restore"][RUNS[0]][-2:] == ["--run", RUNS[0]]
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0]) == 17
  result = take(capsys)
  assert state.deployment_bindings == [result["setup"]["deployment"]]
  assert len(state.backend_calls) == 1 and state.backend_calls[0] == state.sessions[SESSION]
  assert result["load_confirmation"] == "unknown" and result["continue_status"] == "not_sent"
  assert result["restores"][RUNS[1]] is None
  assert RUNS[0] not in result["next_commands"]["restore"]
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0]) == 4
  capsys.readouterr()
  assert len(state.backend_calls) == 1
  assert invoke(state, "cancel", "--batch", state.batch) == 0
  cancelled = take(capsys)
  assert cancelled["cancelled"] is True and cancelled["setup"]["exit_code"] == 0
  assert invoke(state, "status", "--batch", state.batch) == 0
  assert take(capsys)["status"] == "cancelled"
  assert (state.ws.instance / "rules.md").read_text() == "B"


@pytest.mark.parametrize("args", [
  ["plan"], ["stop", "--run", RUNS[0]], ["execute", "--batch", "b" * 32],
  ["restore", "--batch", "b" * 32], ["status"], ["cancel"],
])
def test_no_input_missing_exact_target_or_approval_does_not_read_stdin(command, capsys, args):
  state = command
  assert cli.main([*state.prefix, *args]) == 2
  assert state.streams.stdin.reads == 0 and state.stop_calls == state.syncs == state.backend_calls == []
  assert not (state.ws.state_root / "maintenance-workflows").exists()
  assert "必要参数" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [
  ["--session", RUNS[0] + "=" + SESSION, "--session", RUNS[0] + "=" + SECOND],
  ["--session", "bad=" + SESSION], ["--session", RUNS[0] + "="],
  ["--session", RUNS[0] + "=/outside"], ["--session", RUNS[2] + "=" + SESSION],
  ["--run", RUNS[0]],
])
def test_duplicate_or_malformed_session_mapping_fails_before_business(command, monkeypatch, extra):
  state = command
  monkeypatch.setattr(dsh_stop, "workspace_for_scope", lambda *a, **kw: pytest.fail("invalid syntax reached scope discovery"))
  assert invoke(state, "plan", "--run", RUNS[0], *extra) == 2
  assert state.streams.stdin.reads == 0


def test_batch_plan_rejects_new_selection_and_missing_session_requires_explicit_input(command):
  state = command
  assert invoke(state, "plan", "--batch", "b" * 32, "--run", RUNS[0]) == 2
  assert invoke(state, "plan", "--run", RUNS[0], "--run", RUNS[1]) == 2
  assert state.streams.stdin.reads == 0 and not state.stop_calls


def test_restore_no_input_requires_run_even_one_remaining(command, capsys):
  state = command
  updated(state, capsys)
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0]) == 17
  capsys.readouterr()
  assert invoke(state, "restore", "--batch", state.batch) == 2
  assert len(state.backend_calls) == 1 and state.streams.stdin.reads == 0


def test_tty_stop_review_and_restore_choose_are_separate_from_setup_approval(command, capsys):
  state = command
  state.prefix = state.prefix[1:]
  state.streams = InputGateway(Stream("yes\nyes\n2\n"), Stream(), Stream())
  assert invoke(state, "stop", *state.target_args) == 0
  state.batch = take(capsys)["batch_id"]
  assert state.syncs == [] and state.backend_calls == []
  assert invoke(state, "execute", "--batch", state.batch) == 0
  take(capsys)
  assert len(state.syncs) == 1
  assert invoke(state, "restore", "--batch", state.batch) == 17
  result = take(capsys)
  assert state.backend_calls == [state.sessions[SECOND]]
  assert result["restores"][RUNS[0]] is None
  assert state.streams.stdin.reads == 3
  text = state.streams.stderr.getvalue()
  assert "更新配置须另行批准" in text and "可能联网" in text and "加载待确认" in text


def test_tty_missing_run_uses_only_selected_machine_profile_listing(command, monkeypatch, capsys):
  state = command
  state.prefix = state.prefix[1:]
  state.streams = InputGateway(Stream("1\n"), Stream(), Stream())
  seen = []
  def instances(path, **scope):
    seen.append((path, scope))
    return {"instances": [{"kind": "registered", "agent": state.ws.agent, "profile": state.ws.profile,
      "run_id": RUNS[0], "process": {"ownership_state": "active"}}]}
  monkeypatch.setattr(run_owners, "instances", instances)
  single = deepcopy(state.stop_plan)
  single["selected_runs"] = [RUNS[0]]
  single["runs"] = [row for row in single["runs"] if row["run_id"] == RUNS[0]]
  required = set(single["runs"][0]["resource_ids"])
  single["resources"] = [row for row in single["resources"] if row["resource_id"] in required]
  state.stop_plan = dsh_stop_plan.normalize(single, verify=False)
  monkeypatch.setattr(maintenance, "_choose_sessions", lambda ws, runs, supplied, context: {runs[0]: SESSION})
  assert invoke(state, "plan") == 0
  take(capsys)
  assert seen == [(state.ws.local_path, {"agent": None, "profile": state.ws.profile})]
  assert state.streams.stdin.reads == 1


def test_batch_source_rebinding_fails_closed(command, capsys, monkeypatch):
  state = command
  stopped(state, capsys)
  other = SimpleNamespace(**{**vars(state.ws), "binding": {**state.ws.binding, "machine": "other"}})
  monkeypatch.setattr(workspace, "load_workspace", lambda *a, **kw: other)
  assert invoke(state, "execute", "--batch", state.batch, "--plan-id", state.plan["setup"]["plan_id"]) == 4
  assert state.syncs == []


def test_legacy_batch_query_is_explicit_fallback_without_workflow_mutation(command, capsys, monkeypatch):
  state = command
  seen = []
  legacy = lambda invocation, args: seen.append((invocation.context.scope, args.batch)) or 13
  monkeypatch.setattr(cli, "dispatch_stop_status", legacy)
  monkeypatch.setattr(cli, "dispatch_setup_maintenance_status", legacy)
  assert invoke(state, "status", "--batch", "b" * 32) == 13
  assert seen[0][0].local == str(state.ws.local_path) and seen[0][1] == "b" * 32
  assert not (state.ws.state_root / "maintenance-workflows").exists()


def test_backend_factory_routes_each_tool_without_claiming_loaded(command, monkeypatch):
  import agentcfg.dsh_sessions
  import agentcfg.tool_sessions
  state = command
  seen = []
  for module, name in ((agentcfg.dsh_sessions, "DshResumeCandidate"),
      (agentcfg.tool_sessions, "PiResumeCandidate"), (agentcfg.tool_sessions, "OmpResumeCandidate")):
    monkeypatch.setattr(module, name, lambda selected, name=name: seen.append((name, selected)) or name)
  target = state.sessions[SESSION]
  expected = {"dsh": "DshResumeCandidate", "pi": "PiResumeCandidate", "omp": "OmpResumeCandidate"}[state.ws.agent]
  assert _BACKEND_FOR_WORKSPACE(state.ws, target) == expected
  assert seen == [(expected, state.ws)]


def test_pi_auxiliary_observation_suppresses_session_prompt(command, monkeypatch):
  if command.ws.agent != "pi":
    pytest.skip("Pi-only auxiliary observation")
  import agentcfg.pi_session_observation
  state = command
  state.streams = InputGateway(Stream(), Stream(), Stream())
  target = replace(state.sessions[SESSION], run_id=RUNS[0])
  monkeypatch.setattr(agentcfg.pi_session_observation, "from_records", lambda ws, records: (target,))
  context = SimpleNamespace(input_gateway=state.streams, input_policy="auto")
  assert maintenance._choose_sessions(state.ws, [RUNS[0]], {}, context) == {}
  assert state.streams.stdin.reads == 0


@pytest.mark.parametrize("action", ["plan", "stop", "execute", "restore", "status", "cancel"])
def test_maintenance_help_is_static_three_tool_and_scoped_to_cooperative_pi(action, monkeypatch, capsys):
  monkeypatch.setattr(workspace, "load_workspace", lambda *a, **kw: pytest.fail("help loaded workspace"))
  assert cli.main(["agent", "maintenance", action, "--help"]) == 0
  shown = capsys.readouterr().out
  assert "DSH/Pi/OMP" in shown and "Rotom 合作实例" in shown
  assert "setup维护尚未准入" not in shown and "Pi/OMP 尚不支持" not in shown
  assert "不发送继续" in shown
  assert "分叉 session" in shown and "核对实际 ID" in shown
  assert "cancel 已保存但停止仍未知时返回4，保护保留" in shown


def test_resume_help_avoids_blanket_tool_denial_and_preserves_pending_loading(capsys):
  assert cli.main(["resume", "--help"]) == 0
  shown = capsys.readouterr().out
  assert "DSH/Pi/OMP" in shown and "Rotom 合作实例" in shown and "加载待确认" in shown
  assert "Pi/OMP、其他平台或位置返回 5" not in shown
  assert "分叉 session" in shown and "核对实际 ID" in shown


def test_pi_known_sessions_append_verified_auxiliary_and_propagate_corruption(command, monkeypatch):
  if command.ws.agent != "pi":
    pytest.skip("Pi-only auxiliary observation")
  import agentcfg.pi_session_observation
  from agentcfg.dsh_sessions import scope_key
  from rotom.context import Scope
  state = command
  target = replace(state.sessions[SESSION], run_id=RUNS[0])
  seen = []
  def observed(ws, records):
    seen.append((ws, deepcopy(records)))
    return (target,)
  monkeypatch.setattr(agentcfg.pi_session_observation, "from_records", observed)
  key, rows = resume.load_known(Scope(local=str(state.ws.local_path), profile=state.ws.profile, agent="pi"))
  assert key == scope_key(state.ws.binding) and rows == (target,)
  assert seen == [(state.ws, {})]
  def corrupted(ws, records):
    raise SessionError(4, "synthetic-private-canary")
  monkeypatch.setattr(agentcfg.pi_session_observation, "from_records", corrupted)
  with pytest.raises(SessionError) as error:
    resume.load_known(Scope(local=str(state.ws.local_path), profile=state.ws.profile, agent="pi"))
  assert error.value.code == 4


def test_corrupted_workflow_batch_does_not_fall_back_to_legacy(command, monkeypatch, capsys):
  state = command
  stopped(state, capsys)
  store = flow.Store(state.ws, state.batch)
  path = store.registry.root / "manifest.json"
  value = json.loads(path.read_bytes())
  value["schema_version"] = 99
  path.write_bytes(run_owners._encode(value))
  monkeypatch.setattr(cli, "dispatch_stop_status", lambda *a: pytest.fail("corrupt batch fell back"))
  monkeypatch.setattr(cli, "dispatch_setup_maintenance_status", lambda *a: pytest.fail("corrupt batch fell back"))
  assert invoke(state, "status", "--batch", state.batch) == 4
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("outcome", ["unknown", "dispatched", 0, 23])
def test_restore_distinguishes_unknown_dispatch_from_known_native_exit(command, capsys, monkeypatch, outcome):
  state = command
  updated(state, capsys)
  class Backend(HostResumeBackend):
    def resume_session(self, target, *, location, before_dispatch, after_dispatch):
      state.backend_calls.append(target)
      before_dispatch("f" * 32)
      if outcome == "unknown":
        raise ConnectionError("synthetic-private-response-loss")
      after_dispatch("f" * 32)
      return LaunchReceipt("f" * 32, None if outcome == "dispatched" else outcome)
  monkeypatch.setattr(resume, "backend_for_workspace", lambda *a, **kwargs: Backend())
  expected = 4 if type(outcome) is str else outcome
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0]) == expected
  shown = capsys.readouterr()
  result = flow.status(state.ws, state.batch)
  saved = result["restores"][RUNS[0]]
  assert saved["action"] == ("restore-intent" if type(outcome) is str else "restore-result")
  assert saved["exit_code"] == (None if type(outcome) is str else outcome)
  assert result["load_confirmation"] == "unknown" and result["continue_status"] == "not_sent"
  assert "private" not in shown.err
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0]) == 4
  assert len(state.backend_calls) == 1


@pytest.mark.parametrize("args", [
  ["restore", "--batch", "b" * 32, "--run", RUNS[0], "--run", RUNS[1]],
  ["status", "--batch", "b" * 32, "--batch", "c" * 32],
  ["execute", "--batch", "b" * 32, "--plan-id", "a" * 64, "--plan-id", "c" * 64],
])
def test_single_target_and_approval_cannot_be_shadowed_by_repeated_options(command, monkeypatch, args):
  state = command
  monkeypatch.setattr(maintenance, "_batch_workspace", lambda *a: pytest.fail("duplicate selector reached business"))
  assert cli.main([*state.prefix, *args]) == 2
  assert state.streams.stdin.reads == 0 and state.backend_calls == []


@pytest.mark.parametrize("digest", [None, "a" * 64])
def test_factory_preserves_optional_approved_deployment_for_all_three_tools(command, monkeypatch, digest):
  import agentcfg.dsh_sessions
  import agentcfg.tool_sessions
  state = command
  seen = []
  def candidate(selected, **kwargs):
    seen.append((selected, kwargs))
    return object()
  for module, name in ((agentcfg.dsh_sessions, "DshResumeCandidate"),
      (agentcfg.tool_sessions, "PiResumeCandidate"), (agentcfg.tool_sessions, "OmpResumeCandidate")):
    monkeypatch.setattr(module, name, candidate)
  _BACKEND_FOR_WORKSPACE(state.ws, state.sessions[SESSION], expected_deployment=digest)
  assert seen == [(state.ws, {} if digest is None else {"expected_deployment": digest})]


@pytest.mark.parametrize("stop_state", ["unknown", "missing"])
def test_cancel_reports_unresolved_stop_without_repeating_dispatch(command, monkeypatch, capsys, stop_state):
  state = command
  stopped(state, capsys)
  calls = []
  def inspect(*args, **kwargs):
    calls.append(True)
    if stop_state == "missing":
      raise Conflict("synthetic-first-snapshot-absent")
    return {**state.stop_result, "status": "unknown", "plan_id": state.stop_plan["plan_id"]}
  monkeypatch.setattr(dsh_stop_client, "status_stop", inspect)
  for _ in range(2):
    assert invoke(state, "cancel", "--batch", state.batch) == 4
    result = take(capsys)
    assert result["cancelled"] and result["stop_status"] == "unknown"
  events = flow.Store(state.ws, state.batch).read()["events"]
  assert [row["action"] for row in events] == ["cancel"]
  assert len(state.stop_calls) == 1 and not state.backend_calls and not state.syncs
  assert state.streams.stdin.reads == 0 and calls


@pytest.mark.parametrize("phase", ["stop-pending", "setup", "restore"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_status_does_not_mask_unresolved_stage_with_cancel(command, capsys, phase, cancelled):
  state = command
  if phase == "restore":
    updated(state, capsys)
  else:
    stopped(state, capsys)
  store = flow.Store(state.ws, state.batch)
  if phase == "stop-pending":
    state.stop_result["status"] = "pending"
  elif phase == "setup":
    store.append(store.read(), "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  else:
    store.append(store.read(), "restore-intent", run_id=RUNS[0])
  if cancelled:
    store.append(store.read(), "cancel")
  before = store.read()
  calls = (len(state.stop_calls), len(state.syncs), len(state.backend_calls))
  assert invoke(state, "status", "--batch", state.batch) == 4
  result = take(capsys)
  assert result["cancelled"] is cancelled
  assert store.read() == before
  assert (len(state.stop_calls), len(state.syncs), len(state.backend_calls)) == calls


@pytest.mark.parametrize("location", ["original", "new-tab"])
def test_maintenance_restore_location_dispatches_saved_workflow(command, capsys, monkeypatch, location):
  import sys
  state = command
  updated(state, capsys)
  calls = []
  def dispatch_location(ws, batch_id, run_id, context, *, location, deadline=None):
    assert deadline is not None
    calls.append((ws, batch_id, run_id, location))
    return 19
  monkeypatch.setitem(sys.modules, "rotom.pane_dispatch", SimpleNamespace(dispatch_location=dispatch_location))
  assert invoke(state, "restore", "--batch", state.batch, "--run", RUNS[0], "--" + location) == 19
  assert calls == [(state.ws, state.batch, RUNS[0], location)]
  assert state.backend_calls == []
