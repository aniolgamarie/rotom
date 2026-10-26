"""临时 DSH 部署的只读停止预览；不运行宿主或读取会话正文。"""
from copy import deepcopy
import json

import pytest

from agentcfg import dsh_stop, dsh_stop_scope, lifecycle, run_owners, run_stop_fence
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import MANAGER, observation


def state_files(ws):
  return {str(p.relative_to(ws.state_root)): p.read_bytes()
    for p in ws.state_root.rglob("*") if p.is_file()}


def test_preview_three_select_two_is_readonly_and_honest_about_unknowns(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  before = state_files(ws)
  original = dsh_stop_scope.inspect_deployment
  calls = []
  def inspect(*a, **kw):
    assert_exclusive_busy(ws.instance)
    assert_exclusive_busy(ws.state_root / "instance.lock")
    with pytest.raises(Conflict):
      with registry._locked(nonblocking=True): pass
    calls.append(a[1]["run_id"])
    return original(*a, **kw)
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
  result = dsh_stop.preview_stop(ws, selected_runs=runs[:2])
  plan = result["plan"]
  assert plan["selected_runs"] == sorted(runs[:2])
  assert plan["coordinator"]["kind"] == "dsh-instance-registry"
  assert plan["control_capability"] == "unavailable" and plan["readiness"] == "blocked"
  assert set(plan["blockers"]) == {"stop-capability-unavailable", "control-observation-unknown"}
  assert all(resource["coverage"] == "unknown" for resource in plan["resources"])
  assert all(resource["reference_runs"] == sorted(runs) for resource in plan["resources"])
  assert all("domain_id" not in resource for resource in plan["resources"])
  assert {row["run_id"] for row in result["targets"]} == set(runs[:2])
  assert all(row["session_ref"] is None and row["session_cwd"] is None for row in result["targets"])
  assert all(row["deployed_identity"] == args["expected_records"][row["run_id"]]["deployed_identity"]
    for row in result["targets"])
  assert state_files(ws) == before and calls == sorted(runs[:2])


def test_plan_changes_when_unselected_owner_changes(prepared):
  ws, registry, args, runs = prepared
  before = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  registry.mark_unknown(runs[2], MANAGER)
  after = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
  assert after["plan_id"] != before["plan_id"]
  assert after["coordinator"]["records_digest"] != before["coordinator"]["records_digest"]
  assert after["selected_runs"] == before["selected_runs"]


def test_setup_preview_keeps_unselected_blocker(prepared):
  ws, registry, args, runs = prepared
  result = dsh_stop.preview_stop(ws, selected_runs=runs[:2], operation="setup")
  assert "unselected-run-reference" in result["plan"]["blockers"]


@pytest.mark.parametrize("selection", [[], ["bad"], ["a" * 32, "a" * 32], "a" * 32])
def test_bad_selection_is_input_error_before_reading_workspace(selection):
  with pytest.raises(ValueError): dsh_stop.preview_stop(None, selected_runs=selection)


@pytest.mark.parametrize("change", ["missing", "unknown", "idle", "launcher", "owner-lock", "state-lock", "fence"])
def test_unconfirmed_target_or_scope_has_no_side_effect(prepared, change):
  ws, registry, args, runs = prepared
  selected = runs[:2]
  if change == "missing": selected = ["f" * 32]
  elif change == "unknown": registry.mark_unknown(runs[0], MANAGER)
  elif change == "idle": registry.finish_current(runs[0], MANAGER, run_owners.ReleaseObservation(runs[0], MANAGER, True, True))
  elif change == "launcher": (ws.instance / "launch.mjs").write_text("synthetic-private-canary")
  elif change == "state-lock": (ws.state_root / "instance.lock").unlink()
  elif change == "fence":
    dsh_stop_scope.save_manual_snapshot(ws, **args)
  before = state_files(ws)
  if change == "owner-lock":
    with registry._locked(nonblocking=True), pytest.raises(Conflict):
      dsh_stop.preview_stop(ws, selected_runs=selected)
  else:
    with pytest.raises(Conflict) as caught: dsh_stop.preview_stop(ws, selected_runs=selected)
    assert "synthetic-private-canary" not in str(caught.value)
  assert state_files(ws) == before


def test_changed_owner_during_deployment_inspection_invalidates_preview(prepared, monkeypatch):
  ws, registry, args, runs = prepared; original = dsh_stop_scope.inspect_deployment
  def inspect(*a, **kw):
    result = original(*a, **kw)
    record = deepcopy(args["expected_records"][runs[-1]])
    record["start_cwd"]["path"] = "/synthetic-changed"
    (registry.root / (runs[-1] + ".json")).write_bytes(run_owners._encode(record))
    return result
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
  with pytest.raises(Conflict): dsh_stop.preview_stop(ws, selected_runs=runs[:2])
  assert run_stop_fence.read(registry) is None


def test_legacy_unknown_is_retained_in_resource_reference_without_adoption(prepared):
  ws, registry, args, runs = prepared
  legacy = {"schema_version": 1, "binding_digest": registry.binding_digest, "run_id": runs[-1],
    "manager_identity": MANAGER, "session_ref": None, "state": "unknown",
    "affected_resources": ["instance", "runtime", "native-home"],
    "observation": {"kind": "manager_scope_ended", "observed_at_ns": 1, "coverage": "unknown"}}
  path = registry.root / (runs[-1] + ".json");path.write_bytes(run_owners._encode(legacy)); before=path.read_bytes()
  result = dsh_stop.preview_stop(ws, selected_runs=runs[:2])
  assert all(runs[-1] in resource["reference_runs"] for resource in result["plan"]["resources"])
  assert path.read_bytes() == before


@pytest.mark.parametrize("confirmation", ["historical", "confirmed", "final", "unknown"])
def test_history_is_shown_without_session_body_or_upgrading_confirmation(prepared, confirmation):
  ws, registry, args, runs = prepared
  record = deepcopy(args["expected_records"][runs[0]])
  record["session_observation"] = {"session": {"agent": "dsh", "backend": "managed",
    "native_home_ref": run_owners.native_home_key(record["native_home_ref"]), "native_ref": "synthetic-session"},
    "run_id": runs[0], "emitter_epoch": "synthetic-emitter", "sequence": 1,
    "confirmation": confirmation, "source": "synthetic-event", "observed_at_ns": 2}
  (registry.root / (runs[0] + ".json")).write_bytes(run_owners._encode(record))
  if confirmation == "final":
    # final 必须有完整释放，active 记录不能被展示层宽容读取。
    with pytest.raises(Conflict):
      dsh_stop.preview_stop(ws, selected_runs=[runs[0]])
    return
  result = dsh_stop.preview_stop(ws, selected_runs=[runs[0]])
  assert result["targets"][0]["session_ref"]["native_ref"] == "synthetic-session"
  assert result["targets"][0]["session_status"] == confirmation
  assert result["plan"]["runs"][0]["restore"]["session_status"] == ("unknown" if confirmation == "unknown" else "historical")
  assert result["targets"][0]["session_cwd"] is None


def test_scope_selection_loads_machine_once_and_uses_actual_matching_profile(prepared, monkeypatch):
  from agentcfg import local, workspace
  ws, registry, args, runs = prepared; calls=[]
  monkeypatch.setattr(local, "available_profiles", lambda: [(ws.profile, "dsh"), ("unhandled-profile", "unsupported")])
  def load(path, profiles):
    assert str(path) == ws.binding["local"] and profiles == [ws.profile]
    calls.append(1)
    return [ws]
  monkeypatch.setattr(workspace, "load_instance_workspaces", load)
  result = dsh_stop.preview_for_scope(ws.local_path, selected_runs=runs[:2])
  assert len(calls) == 1 and result["plan"]["scope"]["profile"] == ws.profile
  assert result["plan"]["selected_runs"] == sorted(runs[:2])


def test_scope_selection_rejects_unsupported_or_ambiguous_without_profile_default(prepared, monkeypatch):
  from agentcfg import local, workspace
  from agentcfg.process import DependencyError
  ws, registry, args, runs = prepared
  monkeypatch.setattr(local, "available_profiles", lambda: [(ws.profile, "dsh"), ("unhandled-profile", "unsupported"), ("dsh-other", "dsh")])
  with pytest.raises(DependencyError):
    dsh_stop.preview_for_scope(ws.local_path, selected_runs=runs[:2], profile="unhandled-profile")
  with pytest.raises(ValueError):
    dsh_stop.preview_for_scope(ws.local_path, selected_runs=runs[:2], profile="missing")
  # 重复发现相同run也不能默认取第一个，显式范围才消除歧义。
  monkeypatch.setattr(workspace, "load_instance_workspaces", lambda path, profiles: [ws, ws])
  with pytest.raises(Conflict): dsh_stop.preview_for_scope(ws.local_path, selected_runs=runs[:2])


@pytest.mark.parametrize("command", ["dry-run", "setup-plan", "stop-unadmitted"])
def test_cli_uses_real_scope_and_deployment_without_writes(prepared, monkeypatch, capsys, command):
  from rotom import cli
  from rotom.context import InputGateway
  from test_rotom_interaction import Stream
  ws, registry, args, runs = prepared
  before = state_files(ws)
  gateway = InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False))
  monkeypatch.setattr(cli, "InputGateway", lambda: gateway)
  def forbidden(*a, **kw): pytest.fail("read-only plan cannot accept or publish")
  monkeypatch.setattr(InputGateway, "confirm", forbidden)
  monkeypatch.setattr(dsh_stop_scope, "save_manual_snapshot", forbidden)
  tokens = ["--no-input", "agent", "--local", str(ws.local_path)]
  # 无显式 profile 时也不得将机器默认配方当成查询过滤器。
  if command == "setup-plan":
    from agentcfg import tool_maintenance
    from agentcfg.dsh_sessions import scope_key
    from agentcfg.sessions import KnownSession, SessionRef
    tokens += ["maintenance", "plan", "--operation", "setup", "--format", "json"]
    targets = {}
    for index, run in enumerate(runs[:2]):
      identifier = "synthetic-session-" + str(index)
      record = args["expected_records"][run]
      targets[identifier] = KnownSession(SessionRef("dsh", "managed",
        run_owners.native_home_key(record["native_home_ref"]), identifier), scope_key(ws.binding),
        ws.profile, record["start_cwd"]["path"], "historical", "historical", 1, run)
      tokens += ["--session", run + "=" + identifier]
    # 本例验证 scope/部署/只读组合，显式会话选择的公开查询用合成结果；不授予 stop。
    monkeypatch.setattr(tool_maintenance, "lookup_session", lambda selected, identifier: targets[identifier])
  else: tokens += ["instances", "stop"]
  for run in runs[:2]: tokens += ["--run", run]
  if command == "dry-run": tokens += ["--dry-run"]
  elif command == "stop-unadmitted":
    plan = dsh_stop.preview_stop(ws, selected_runs=runs[:2])["plan"]
    tokens += ["--plan-id", plan["plan_id"]]
  assert cli.main(tokens) == (5 if command == "stop-unadmitted" else 0)
  output = json.loads(capsys.readouterr().out)
  assert output["scope"] == {**ws.binding, "agent": "dsh"}
  assert output["readonly"] is True and output["selected_runs"] == sorted(runs[:2])
  assert output["plan"]["coordinator"]["records_digest"] == dsh_stop._digest(registry.snapshot())
  assert all(item["reference_runs"] == sorted(runs) for item in output["plan"]["resources"])
  assert "stop-capability-unavailable" in output["blockers"]
  assert state_files(ws) == before and gateway.stdin.reads == 0
