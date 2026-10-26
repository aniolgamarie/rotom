"""显式 OMP 范围的只读状态门面；后端替身不读取宿主或历史路径。"""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest

from agentcfg.storage import Conflict
from rotom import cli, preferences
from rotom.context import InputGateway
from test_rotom_interaction import Stream


BATCH = "b" * 32


@pytest.fixture
def status(tmp_path, monkeypatch):
  backend = importlib.import_module("agentcfg.maintenance_status")
  streams = InputGateway(Stream(tty=False), Stream(tty=False), Stream(tty=False))
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  monkeypatch.setattr(cli, "_profile_tool", lambda profile: {"workbench": "omp", "omp-looking": "dsh"}[profile])
  local = tmp_path / "explicit-local.toml"
  value = {"kind": "setup-maintenance-status", "readonly": True, "batch_id": BATCH, "revision": 8,
    "intent_generation": 4, "intent_phase": "completed", "scope": {"agent": "omp", "machine": "example",
      "local": str(local), "profile": "workbench"}, "phase": "maintenance_succeeded", "operation": "setup",
    "maintenance_dispatch": {"state": "confirmed", "dispatch_id": "c" * 32,
      "setup_plan_digest": "d" * 64, "target_deployment_digest": "e" * 64},
    "operation_result": {"operation": "setup", "status": "succeeded", "exit_code": 0, "result_digest": "f" * 64},
    "review_required": False, "items": [{"run_id": "a" * 32, "stop_phase": "stopped_confirmed",
      "restore_phase": "manual", "facts": {"exit_confirmed": True, "resources_released": True},
      "launch_dispatch": {"state": "not_dispatched", "dispatch_id": None, "new_run_id": None}}],
    "observation": {"target_state": "target-matches", "resources_checked": True, "pending_journal": False,
      "reason": None}, "protected": False, "continue_status": "not_sent", "exit_code": 0}
  calls, dsh_calls = [], []
  def setup(args, batch_id):
    calls.append((args, batch_id))
    return deepcopy(value)
  monkeypatch.setattr(backend, "status_setup", setup)
  monkeypatch.setattr(cli, "dispatch_stop_status", lambda invocation, args: dsh_calls.append(
    (invocation.context.scope, args.maintenance_command)) or 13)
  argv = ["--no-input", "agent", "--local", str(local), "--profile", "workbench", "maintenance", "status",
    "--batch", BATCH]
  return SimpleNamespace(backend=backend, local=local, value=value, calls=calls, dsh_calls=dsh_calls,
    streams=streams, argv=argv)


@pytest.mark.parametrize("output", ["json", "auto"])
@pytest.mark.parametrize("code", [0, 4, 5, 6])
def test_explicit_omp_status_returns_one_json_exact_scope_and_backend_exit(status, capsys, output, code):
  status.value["exit_code"] = code
  assert cli.main([*status.argv, "--format", output]) == code
  shown = json.loads(capsys.readouterr().out)
  assert shown == status.value | {"next_commands": {"status": ["rotom", "agent", "--local", str(status.local),
    "--profile", "workbench", "maintenance", "status", "--batch", BATCH]}}
  args, batch = status.calls[0]
  assert len(status.calls) == 1 and batch == BATCH
  assert vars(args) == {"local": status.local, "profile": "workbench", "agent": "omp"}
  assert status.dsh_calls == [] and status.streams.stdin.reads == 0 and not status.local.exists()


def test_explicit_machine_uses_selected_xdg_path_without_discovery(status):
  from agentcfg.paths import xdg_config_home
  args = ["--no-input", "agent", "--machine", "workstation", *status.argv[4:]]
  assert cli.main(args) == 0
  assert status.calls[0][0].local == xdg_config_home() / "agentcfg/machines/workstation.toml"
  assert status.streams.stdin.reads == 0


def test_human_and_tty_auto_escape_controls_and_show_original_result(status, monkeypatch, capsys):
  status.value["phase"] = "partial\x1b[31m\ncontrol"
  status.value["observation"]["reason"] = "unconfirmed\x1b[2J\ncontrol"
  status.value["operation_result"].update(status="partial", exit_code=4)
  status.value["exit_code"] = 4
  for output in ("human", "auto"):
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    assert cli.main([*status.argv, "--format", output]) == 4
    shown = capsys.readouterr()
    for expected in (BATCH, "revision=8", "completed", "partial", "exit_code=4", "stopped_confirmed",
        "manual", "target-matches", "not_sent"):
      assert expected in shown.out
    assert "\x1b" not in shown.out and "\x1b" not in shown.err
    assert "只读" in shown.err and "不等于" in shown.err
  assert status.streams.stdin.reads == 0


@pytest.mark.parametrize("mode", ["no-profile", "dsh-profile", "cancel", "execute", "restore", "stop"])
def test_new_route_never_opens_other_scope_or_operations(status, mode):
  args = list(status.argv)
  if mode == "no-profile": del args[4:6]
  elif mode == "dsh-profile": args[5] = "omp-looking"
  elif mode == "stop":
    args = [*args[:7], "stop", "--operation", "setup", "--run", "a" * 32, "--plan-id", "d" * 64]
  else: args[7] = mode
  assert cli.main(args) == (13 if mode in ("no-profile", "dsh-profile", "cancel") else 5)
  assert status.calls == [] and status.streams.stdin.reads == 0


@pytest.mark.parametrize("batch", ["bad", "B" * 32, "b" * 31])
def test_invalid_batch_fails_before_backend_or_stdin(status, batch):
  assert cli.main([*status.argv[:-1], batch]) == 2
  assert status.calls == [] and status.dsh_calls == [] and status.streams.stdin.reads == 0


def test_backend_error_stays_private_without_json_or_fallback(status, monkeypatch, capsys):
  def fail(*args): raise Conflict("synthetic-private-canary")
  monkeypatch.setattr(status.backend, "status_setup", fail)
  assert cli.main(status.argv) == 4
  shown = capsys.readouterr()
  assert shown.out == "" and "canary" not in shown.err
  assert status.dsh_calls == [] and status.streams.stdin.reads == 0


def test_status_help_is_static_and_explicit_about_omp_readonly(monkeypatch, capsys):
  def forbidden(*args, **kwargs): pytest.fail("static help must not inspect scope or backend")
  monkeypatch.setattr(cli, "_profile_tool", forbidden)
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  assert cli.main(["agent", "maintenance", "status", "--help"]) == 0
  text = capsys.readouterr().out
  assert "Linux OMP" in text and "显式 --profile" in text and "只读" in text
  assert "已保存批次" in text and "DSH cancel" in text
  assert "无写入" in text
  effects = cli.command_effects(("agent", "maintenance", "status"))
  assert "write:none" in effects and any("omp" in effect for effect in effects)
