"""停止 CLI 控制门面；采集与执行全部 fake，不发送信号或启动宿主。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop, dsh_stop_plan, dsh_stop_client, dsh_stop_completion
from agentcfg.storage import Conflict
from rotom import cli
from rotom.context import InputGateway
from test_rotom_dsh_stop_plan import RUNS, source
from test_rotom_interaction import Stream
from test_rotom_stop_plan_cli import preview


_BATCH = "b" * 32
_CONFIRM = InputGateway.confirm


@pytest.fixture
def ready(preview, monkeypatch):
  args, local, calls, streams, collect = preview
  workspace = object()
  state = SimpleNamespace(executions=[], workspaces=[], closes=[], batches=[], statuses=[], status="stopped",
    close_reason=None, approve_results=[], workspace=workspace)
  def observed(*a, **kw):
    value = collect(*a, **kw)
    value["plan"]["control_capability"] = "supported"
    value["plan"] = dsh_stop_plan.normalize(value["plan"], verify=False)
    assert value["plan"]["readiness"] == "ready"
    return value
  monkeypatch.setattr(dsh_stop, "preview_for_scope", observed)
  plan = observed(local, selected_runs=RUNS[:1])["plan"]
  calls.clear()
  def workspace_for_scope(path, *, selected_runs, profile):
    state.workspaces.append((path, deepcopy(selected_runs), profile))
    return workspace
  monkeypatch.setattr(dsh_stop, "workspace_for_scope", workspace_for_scope)
  def result(status=None):
    return {"batch_id": _BATCH, "plan_id": plan["plan_id"], "scope": deepcopy(plan["scope"]),
      "status": status or state.status, "close_reason": state.close_reason, "protected": state.status == "pending",
      "targets": [{"run_id": RUNS[0], "lifecycle_state": "active", "request": "posted", "dispatch": "unknown"}],
      "continue_status": "not_sent", "resource_coverage": "unknown"}
  def execute(ws, *, expected_plan, approve, wait_seconds):
    assert ws is workspace
    state.executions.append((deepcopy(expected_plan), wait_seconds))
    approved = approve(deepcopy(expected_plan))
    state.approve_results.append(approved)
    if approved is not True: raise Conflict("synthetic-private-canary")
    return result()
  monkeypatch.setattr(dsh_stop_client, "execute_stop", execute)
  def workspace_for_batch(path, *, batch_id, profile=None):
    state.batches.append((path, batch_id, profile))
    return workspace
  monkeypatch.setattr(dsh_stop_client, "workspace_for_batch", workspace_for_batch)
  def status(ws, *, batch_id):
    assert ws is workspace and batch_id == _BATCH
    state.statuses.append(batch_id)
    return result()
  monkeypatch.setattr(dsh_stop_client, "status_stop", status)
  def close(ws, *, batch_id, plan_id, reason):
    assert ws is workspace
    state.closes.append((batch_id, plan_id, reason))
    state.status = reason
  monkeypatch.setattr(dsh_stop_completion, "close_stop", close)
  return SimpleNamespace(args=args, local=local, streams=streams, calls=calls, plan=plan,
    state=state, observed=observed, result=result)


def actual(ready, *extra):
  return ["--no-input", *ready.args, "--plan-id", ready.plan["plan_id"], *extra]


def maintenance(ready, action, *extra):
  return ["--no-input", *ready.args[:3], "--profile", "dsh-default", "maintenance", action,
    "--batch", _BATCH, "--format", "json", *extra]


@pytest.mark.parametrize("status,code", [("stopped", 0), ("pending", 4), ("unknown", 4)])
def test_ready_exact_noinput_executes_once_unique_json_and_trackable_batch(ready, capsys, status, code):
  ready.state.status = status
  assert cli.main(actual(ready, "--wait-seconds", "7")) == code
  value = json.loads(capsys.readouterr().out)
  assert value["batch_id"] == _BATCH and value["status"] == status
  assert value["continue_status"] == "not_sent" and value["resource_coverage"] == "unknown"
  assert "readonly" not in value
  assert ready.state.executions == [(ready.plan, 7)] and ready.state.approve_results == [True]
  assert ready.state.workspaces == [(ready.local, [RUNS[0]], "dsh-default")]
  assert ready.streams.stdin.reads == 0
  for action in ("status", "cancel"):
    assert value["next_commands"][action] == ["rotom", "agent", "--local", str(ready.local),
      "--profile", "dsh-default", "maintenance", action, "--batch", _BATCH]


def test_dry_run_ready_is_readonly_without_execution_or_confirmation(ready, capsys):
  assert cli.main(actual(ready, "--dry-run")) == 0
  value = json.loads(capsys.readouterr().out)
  assert value["readonly"] is True and value["readiness"] == "ready"
  assert not ready.state.executions and not ready.state.workspaces
  assert ready.streams.stdin.reads == 0


@pytest.mark.parametrize("mode", [[], ["--no-input"]])
def test_noinput_without_plan_id_never_collects_or_executes(ready, mode):
  assert cli.main([*mode, *ready.args]) == 2
  assert ready.calls == [] and not ready.state.executions and ready.streams.stdin.reads == 0


def test_stale_plan_id_blocks_before_workspace_or_execute(ready):
  assert cli.main(["--no-input", *ready.args, "--plan-id", "0" * 64]) == 4
  assert len(ready.calls) == 1 and not ready.state.workspaces and not ready.state.executions


def test_recheck_approval_cannot_approve_different_plan(ready, monkeypatch, capsys):
  def execute(ws, *, expected_plan, approve, wait_seconds):
    changed = deepcopy(expected_plan); changed["plan_id"] = "f" * 64
    assert approve(changed) is False
    raise Conflict("synthetic-private-canary")
  monkeypatch.setattr(dsh_stop_client, "execute_stop", execute)
  assert cli.main(actual(ready)) == 4
  assert ready.streams.stdin.reads == 0
  assert "synthetic-private-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("answer,code", [("yes\n", 0), ("no\n", 130), ("", 130)])
def test_interactive_confirmation_is_only_execute_callback_after_auditable_preview(ready, monkeypatch, capsys, answer, code):
  current = InputGateway(Stream(answer), Stream(), Stream())
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  monkeypatch.setattr(InputGateway, "confirm", _CONFIRM)
  original = dsh_stop_client.execute_stop
  def execute(*a, **kw):
    assert current.stdin.reads == 0
    return original(*a, **kw)
  monkeypatch.setattr(dsh_stop_client, "execute_stop", execute)
  assert cli.main(["--interactive", *ready.args]) == code
  output = capsys.readouterr()
  assert ready.plan["plan_id"] in output.err and RUNS[0] in output.err
  assert "synthetic-start" in output.err and "session_status" in output.err
  assert current.stdin.reads == 1 and len(ready.state.executions) == 1
  if code == 0: assert json.loads(output.out)["status"] == "stopped"
  else: assert output.out == "" and ready.state.approve_results == []


@pytest.mark.parametrize("status,code", [("pending", 0), ("stopped", 0), ("cancelled", 0), ("unknown", 4), ("snapshot_only", 4)])
def test_status_exact_scope_is_readonly_and_does_not_close(ready, capsys, status, code):
  ready.state.status = status
  assert cli.main(maintenance(ready, "status")) == code
  assert json.loads(capsys.readouterr().out)["status"] == status
  assert ready.state.batches == [(ready.local, _BATCH, "dsh-default")]
  assert ready.state.statuses == [_BATCH] and not ready.state.closes and not ready.state.executions
  assert ready.streams.stdin.reads == 0


def test_cancel_pending_uses_saved_plan_and_rereads_status(ready, capsys):
  ready.state.status = "pending"
  assert cli.main(maintenance(ready, "cancel")) == 0
  assert ready.state.closes == [(_BATCH, ready.plan["plan_id"], "cancelled")]
  assert ready.state.statuses == [_BATCH, _BATCH]
  assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
  assert ready.streams.stdin.reads == 0


@pytest.mark.parametrize("reason", ["stopped", "cancelled"])
def test_cancel_reconciles_known_close_reason_without_inventing_new_reason(ready, reason):
  ready.state.status, ready.state.close_reason = "pending", reason
  assert cli.main(maintenance(ready, "cancel")) == 0
  assert ready.state.closes == [(_BATCH, ready.plan["plan_id"], reason)]


@pytest.mark.parametrize("status", ["stopped", "cancelled"])
def test_closed_batch_is_not_written_again(ready, status):
  ready.state.status = status
  assert cli.main(maintenance(ready, "cancel")) == 0
  assert ready.state.statuses == [_BATCH] and not ready.state.closes


def test_cancel_unconfirmed_dispatch_remains_error_without_fake_success(ready, monkeypatch, capsys):
  ready.state.status = "pending"
  def close(*a, **kw): raise Conflict("synthetic-private-canary")
  monkeypatch.setattr(dsh_stop_completion, "close_stop", close)
  assert cli.main(maintenance(ready, "cancel")) == 4
  output = capsys.readouterr()
  assert output.out == "" and "synthetic-private-canary" not in output.err
  assert ready.state.statuses == [_BATCH]


@pytest.mark.parametrize("action", ["stop", "status", "cancel"])
def test_wrong_scope_never_falls_back_to_other_workspace(ready, monkeypatch, capsys, action):
  calls = []
  def reject(local, **kwargs):
    calls.append((local, kwargs)); raise Conflict("synthetic-private-canary")
  if action == "stop":
    monkeypatch.setattr(dsh_stop, "workspace_for_scope", reject)
    args = actual(ready)
  else:
    monkeypatch.setattr(dsh_stop_client, "workspace_for_batch", reject)
    args = maintenance(ready, action)
  assert cli.main(args) == 4
  assert len(calls) == 1 and calls[0][0] == ready.local
  assert not ready.state.executions and not ready.state.closes
  assert "synthetic-private-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("format", ["json", "human"])
def test_status_renders_saved_target_history_and_version_without_live_claim(ready, monkeypatch, capsys, format):
  value = ready.result("pending")
  target = {"manager_identity": {"pid": 12345, "birth_id": "synthetic-manager"},
    "host_identity": {"identity": {"pid": 12346, "birth_id": "synthetic-host"}},
    "start_cwd": {"path": "/synthetic-project\x1b[31m\ncontrol", "confirmation": "confirmed"},
    "session_cwd": None, "session_ref": {"native_ref": "saved-session"}, "session_status": "historical",
    "deployed_identity": {"deployment": "d" * 64, "runtime": "e" * 64}}
  value["targets"][0]["target"] = deepcopy(target)
  monkeypatch.setattr(dsh_stop_client, "status_stop", lambda *a, **kw: deepcopy(value))
  args = maintenance(ready, "status"); args[-1] = format
  assert cli.main(args) == 0
  output = capsys.readouterr().out
  if format == "json":
    shown = json.loads(output)
    assert shown["targets"][0]["target"] == target
    assert shown["continue_status"] == "not_sent" and shown["resource_coverage"] == "unknown"
  else:
    assert "manager=12345" in output and "host=12346" in output
    assert "saved-session (historical)" in output and "start_cwd=/synthetic-project" in output
    assert "d" * 64 in output and "e" * 64 in output
    assert "\x1b" not in output and target["start_cwd"]["path"] not in output
    assert "未发送继续" in output and "unknown" in output
  assert not ready.state.closes and not ready.state.executions and ready.streams.stdin.reads == 0
  assert value["targets"][0]["target"] == target
