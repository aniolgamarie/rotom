"""停止计划门面只读预览；fake 采集，不准入任何停止或批准。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop, dsh_stop_plan, run_owners
from rotom import cli
from rotom.context import InputGateway
from test_rotom_dsh_stop_plan import RUNS, source
from test_rotom_interaction import Stream


@pytest.fixture
def preview(source, tmp_path, monkeypatch):
  calls = []
  from rotom import preferences
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  streams = InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False))
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  def collect(local, *, selected_runs, profile=None, operation="stop_only"):
    calls.append((local, deepcopy(selected_runs), profile, operation))
    data = deepcopy(source)
    scope = data["scope"] | {"local": str(local), "profile": profile or "dsh-default"}
    data["scope"] = scope
    for run in data["runs"]: run["scope"] = deepcopy(scope)
    binding = {k: scope[k] for k in ("machine", "local", "profile")}
    data["coordinator"]["binding_digest"] = hashlib.sha256(run_owners._encode(binding)).hexdigest()
    data.update(operation=operation, selected_runs=deepcopy(selected_runs), control_capability="unavailable")
    value = dsh_stop_plan.build(**data)
    targets = [{"run_id": run, "manager_identity": {"pid": 12345, "birth_id": "synthetic-manager"},
      "deployed_identity": {"deployment": "b" * 64, "runtime": "c" * 64},
      "host_identity": None, "start_cwd": {"path": "/synthetic-start", "confirmation": "confirmed"},
      "session_cwd": None, "session_ref": None, "session_status": "unknown"} for run in value["selected_runs"]]
    if len(targets) > 1:
      targets[1].update(host_identity={"identity": {"pid": 12346, "birth_id": "synthetic-host"}},
        session_cwd={"path": "/synthetic-session", "confirmation": "historical"},
        session_ref={"native_ref": "synthetic-session"}, session_status="historical")
    return {"plan": value, "targets": targets}
  monkeypatch.setattr(dsh_stop, "preview_for_scope", collect, raising=False)
  local = tmp_path / "local.toml"
  args = ["agent", "--local", str(local), "instances", "stop", "--run", RUNS[0]]
  def confirm(*a, **kw): pytest.fail("unadmitted stop cannot request confirmation")
  monkeypatch.setattr(InputGateway, "confirm", confirm)
  from agentcfg import stop_review, dsh_stop_scope
  monkeypatch.setattr(stop_review, "review_stop_plan", confirm)
  monkeypatch.setattr(stop_review, "consume_stop_review", confirm)
  monkeypatch.setattr(dsh_stop_scope, "save_manual_snapshot", confirm)
  return args, local, calls, streams, collect


def test_dry_run_json_full_scope_targets_blockers_next_preview(preview, capsys):
  args, local, calls, streams, collect = preview
  assert cli.main(["--no-input", *args, "--run", RUNS[1], "--dry-run"]) == 0
  value = json.loads(capsys.readouterr().out)
  assert value["readonly"] is True and value["scope"]["local"] == str(local)
  assert value["selected_runs"] == RUNS[:2] and value["plan_id"] == value["plan"]["plan_id"]
  assert value["targets"][0]["session_status"] == "unknown" and value["targets"][0]["session_cwd"] is None
  assert value["targets"][1]["session_status"] == "historical"
  assert "stop-capability-unavailable" in value["plan"]["blockers"]
  assert calls == [(local, RUNS[:2], None, "stop_only")]
  assert value["next_commands"]["preview"] == ["rotom", "agent", "--local", str(local), "--profile", "dsh-default",
    "instances", "stop", "--run", RUNS[0], "--run", RUNS[1], "--dry-run"]
  assert streams.stdin.reads == 0 and not local.exists()


def test_explicit_profile_hard_filter_passed(preview, capsys):
  args, local, calls, streams, collect = preview
  assert cli.main(args[:3] + ["--profile", "dsh-profile"] + args[3:] + ["--dry-run"]) == 0
  assert calls[0][2] == "dsh-profile"


def test_human_output_escapes_controls_and_marks_history(preview, monkeypatch, capsys):
  args, local, calls, streams, collect = preview
  monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
  def altered(*a, **kw):
    value = collect(*a, **kw)
    value["targets"][0]["start_cwd"]["path"] = "/synthetic\x1b[31m\ncontrol"
    return value
  monkeypatch.setattr(dsh_stop, "preview_for_scope", altered)
  assert cli.main(args + ["--run", RUNS[1], "--dry-run"]) == 0
  text = capsys.readouterr().out
  assert "只读" in text and "未" in text and "historical" in text and "unknown" in text
  assert "\x1b" not in text and "/synthetic\x1b[31m\ncontrol" not in text
  assert "12345" in text and "12346" in text and "synthetic-session" in text
  assert "deployment=" + "b" * 64 in text and "runtime=" + "c" * 64 in text


@pytest.mark.parametrize("extra", [["--run", RUNS[0]], ["--run", "bad"], ["--plan-id", "bad"],
  ["--run", "A" * 32], ["--plan-id", "F" * 64], ["--wait-seconds", "0"], ["--wait-seconds", "301"]])
def test_invalid_explicit_inputs_before_collection_or_interaction(preview, extra, monkeypatch):
  args, local, calls, streams, collect = preview
  current = InputGateway(Stream(), Stream(), Stream())
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  from rotom import preferences
  monkeypatch.setattr(preferences, "load_preferences", lambda: pytest.fail("invalid target before scope reads"))
  assert cli.main(["--interactive", *args, *extra, "--dry-run"]) == 2
  assert calls == [] and streams.stdin.reads == 0


@pytest.mark.parametrize("mode", [[], ["--no-input"]])
def test_noninteractive_without_plan_id_is_usage_no_collection(preview, mode):
  args, local, calls, streams, collect = preview
  assert cli.main([*mode, *args]) == 2
  assert calls == [] and streams.stdin.reads == 0


@pytest.mark.parametrize("dry", [False, True])
def test_exact_plan_id_mismatch_is_conflict(preview, dry):
  args, local, calls, streams, collect = preview
  assert cli.main([*args, "--plan-id", "0" * 64, *(["--dry-run"] if dry else [])]) == 4
  assert len(calls) == 1 and streams.stdin.reads == 0


@pytest.mark.parametrize("dry", [False, True])
def test_matching_plan_id_is_only_preview_not_approval(preview, capsys, dry):
  args, local, calls, streams, collect = preview
  plan = collect(local, selected_runs=RUNS[:1])["plan"]; calls.clear()
  assert cli.main(["--no-input", *args, "--plan-id", plan["plan_id"], *(["--dry-run"] if dry else [])]) == (0 if dry else 5)
  value = json.loads(capsys.readouterr().out)
  assert value["readonly"] is True
  assert len(calls) == 1 and streams.stdin.reads == 0 and not local.exists()


def test_interactive_unadmitted_without_id_never_confirms(preview, monkeypatch, capsys):
  args, local, calls, streams, collect = preview
  current = InputGateway(Stream("yes\n"), Stream(), Stream())
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main(["--interactive", *args]) == 5
  assert current.stdin.reads == 0 and len(calls) == 1


@pytest.mark.parametrize("format", ["json", "human", "auto"])
def test_maintenance_setup_plan_readonly(preview, capsys, format):
  args, local, calls, streams, collect = preview
  assert cli.main(["--no-input", *args[:3], "maintenance", "plan", "--operation", "setup", "--run", RUNS[0], "--format", format]) == 0
  assert calls == [(local, RUNS[:1], None, "setup")]
  text = capsys.readouterr().out
  if format != "human": assert json.loads(text)["readonly"] is True
  else: assert "只读" in text
  assert streams.stdin.reads == 0


def test_maintenance_batch_stays_unadmitted_without_queries(preview):
  args, local, calls, streams, collect = preview
  assert cli.main([*args[:3], "maintenance", "plan", "--batch", "a" * 32]) == 5
  assert calls == []


@pytest.mark.parametrize("command", [["instances", "stop"], ["maintenance", "plan"], ["maintenance", "stop"]])
def test_static_help_no_scope_queries_and_no_admission(preview, command, monkeypatch, capsys):
  args, local, calls, streams, collect = preview
  from rotom import preferences
  monkeypatch.setattr(preferences, "load_preferences", lambda: pytest.fail("static help cannot read preferences"))
  assert cli.main(["agent", *command, "--help"]) == 0
  text = capsys.readouterr().out
  assert "尚未准入" in text or "待准入" in text
  assert calls == []


@pytest.mark.parametrize("tty", [(False, True, True), (True, False, True), (True, True, False)])
def test_any_non_tty_without_plan_id_no_input_or_collection(preview, tty, monkeypatch):
  args, local, calls, streams, collect = preview
  current = InputGateway(*(Stream(tty=flag) for flag in tty))
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main(args) == 2
  assert current.stdin.reads == 0 and calls == []


def test_target_session_projection_does_not_mutate_helper(preview, monkeypatch, capsys):
  args, local, calls, streams, collect = preview
  original = []
  def statuses(*a, **kw):
    value = collect(*a, **kw)
    value["targets"][0]["session_ref"] = {"native_ref": "unknown-reference"}
    value["targets"][1]["session_status"] = "confirmed"
    original.append(value)
    return value
  monkeypatch.setattr(dsh_stop, "preview_for_scope", statuses)
  assert cli.main(args + ["--run", RUNS[1], "--dry-run"]) == 0
  value = json.loads(capsys.readouterr().out)
  assert value["targets"][0]["session_status"] == "unknown"
  assert value["targets"][1]["session_status"] == "historical"
  assert original[0]["targets"][1]["session_status"] == "confirmed"


def test_machine_scope_and_collection_conflict(preview, monkeypatch, capsys):
  args, local, calls, streams, collect = preview
  from agentcfg.paths import xdg_config_home
  from agentcfg.storage import Conflict
  assert cli.main(["agent", "--machine", "synthetic", "instances", "stop", "--run", RUNS[0], "--dry-run"]) == 0
  assert calls[0][0] == xdg_config_home() / "agentcfg/machines/synthetic.toml"
  def conflict(*a, **kw): raise Conflict("private-canary")
  monkeypatch.setattr(dsh_stop, "preview_for_scope", conflict)
  assert cli.main(args + ["--dry-run"]) == 4
  assert "private-canary" not in capsys.readouterr().err


def test_unknown_resource_coverage_is_retained_and_native_capability_still_blocks(preview, source, capsys):
  source["resources"][0]["coverage"] = "unknown"
  assert cli.main(preview[0] + ["--dry-run"]) == 0
  value = json.loads(capsys.readouterr().out)
  assert value["readonly"] is True and value["readiness"] == "blocked"
  assert value["blockers"] == ["stop-capability-unavailable"]
  assert any(resource["coverage"] == "unknown" for resource in value["plan"]["resources"])


def test_human_plan_discloses_unknown_resource_coverage(preview, source, monkeypatch, capsys):
  source["resources"][0]["coverage"] = "unknown"
  monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
  assert cli.main(preview[0] + ["--dry-run"]) == 0
  text = capsys.readouterr().out
  assert "coverage=unknown" in text and "reference_runs=" in text
