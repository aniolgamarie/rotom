"""OMP 输入诊断只输出结构化阻塞指标，不复制日志正文。"""

import json
import os
from pathlib import Path

import pytest
import termios

from agentcfg import cli
from agentcfg import omp_input_diagnostics
from agentcfg import interaction_diagnostics
from agentcfg.omp_input_diagnostics import _event, _tail, inspect
from agentcfg.omp_identity import native_identity
from agentcfg.storage import ensure_private
from agentcfg.workspace import load_workspace


def test_loop_event_allowlist_never_returns_log_text():
  secret = "private-prompt-canary"
  line = json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "level": "warn", "pid": 123,
    "message": "ui.loop-blocked", "blockedMs": 429, "cpuMs": 288, "phase": "render",
    "prompt": secret})
  result = _event(line)
  assert result == {"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 123,
    "blocked_ms": 429, "cpu_ms": 288, "phase": "render"}
  assert secret not in repr(result)
  malicious = json.loads(line)
  malicious["phase"] = "privateToken123"
  assert _event(json.dumps(malicious))["phase"] == "unknown"


def test_terminal_probe_failure_is_reported_as_unknown(monkeypatch):
  monkeypatch.setattr(interaction_diagnostics.os, "isatty", lambda fd: True)
  monkeypatch.setattr(termios, "tcgetattr", lambda fd: (_ for _ in ()).throw(termios.error("failed")))
  state = interaction_diagnostics.terminal_state()
  assert state["stdin_tty"] is True
  assert state["echo"] is None


def test_readiness_does_not_loop_on_sync_for_old_deployed_runtime():
  report = {"recovery_pending": False, "dependencies": "installed", "deployed": True,
    "deployed_dependencies": "missing", "deployed_runtime_matches_current": False,
    "conflicts": False, "drift": False, "changes_pending": 0}
  ready = interaction_diagnostics.readiness(report)
  assert "plan" in ready["next_commands"]
  assert "setup" in ready["next_commands"]
  assert "sync" not in ready["next_commands"]


def test_doctor_input_reports_only_managed_omp_events(capsys):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  local = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"
  workspace = load_workspace(local)
  logs = native_identity(workspace.profile, workspace.instance).agent_dir.parent / "logs"
  ensure_private(logs)
  logs.chmod(0o755)
  secret = "private-log-body-canary"
  path = logs / "omp.2026-09-27.123.log"
  path.write_text(json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 123,
    "message": "ui.loop-blocked", "blockedMs": 429, "cpuMs": 288, "phase": "unknown",
    "secret": secret}) + "\n" + json.dumps({"message": secret}), encoding="utf-8")
  path.chmod(0o644)
  report = inspect(workspace)
  assert report["logs_present"] is True
  assert report["logs_checked"] == 1
  assert report["loop_blocks"][0]["blocked_ms"] == 429
  assert secret not in repr(report)
  capsys.readouterr()
  assert cli.main(["doctor", "--input"]) == 0
  output = capsys.readouterr().out
  assert secret not in output
  assert json.loads(output)["input_diagnostics"]["host_events"]["loop_blocks"][0]["blocked_ms"] == 429


@pytest.mark.parametrize("profile,agent", [("dsh-default", "dsh"), ("pi-default", "pi")])
def test_doctor_input_reports_generic_state_for_other_agents(profile, agent, capsys):
  assert cli.main(["init-local", "--profile", profile]) == 0
  capsys.readouterr()
  assert cli.main(["doctor", "--input"]) in (0, 2, 5)
  report = json.loads(capsys.readouterr().out)
  assert report["agent"] == agent
  assert report["input_diagnostics"]["host_events"]["status"] in ("not-available", "not-checked")
  assert report["input_diagnostics"]["readiness"]["status"] == "action-required"
  assert report["input_diagnostics"]["readiness"]["next_commands"]


def test_input_diagnostics_allows_live_append_and_bounds_read(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  local = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"
  workspace = load_workspace(local)
  logs = native_identity(workspace.profile, workspace.instance).agent_dir.parent / "logs"
  ensure_private(logs)
  logs.chmod(0o755)
  path = logs / "omp.2026-09-27.123.log"
  path.write_text(json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 123,
    "message": "ui.loop-blocked", "blockedMs": 429, "cpuMs": 288, "phase": "render"}) + "\n",
    encoding="utf-8")
  path.chmod(0o644)
  real_pread = os.pread
  def grow(fd, size, offset):
    assert size <= 1024 * 1024
    with path.open("a", encoding="utf-8") as output:
      output.write(json.dumps({"message": "later"}) + "\n")
    return real_pread(fd, size, offset)
  monkeypatch.setattr(omp_input_diagnostics.os, "pread", grow)
  report = inspect(workspace)
  assert report["logs_checked"] == 1
  assert report["loop_blocks"][0]["blocked_ms"] == 429
  assert "logs_status" not in report


def test_input_diagnostics_selects_recent_logs_by_mtime():
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  local = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"
  workspace = load_workspace(local)
  logs = native_identity(workspace.profile, workspace.instance).agent_dir.parent / "logs"
  ensure_private(logs)
  logs.chmod(0o755)
  for pid in range(900, 905):
    path = logs / f"omp.2026-09-27.{pid}.log"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
  recent = logs / "omp.2026-09-27.100.log"
  recent.write_text(json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 100,
    "message": "ui.loop-blocked", "blockedMs": 429, "cpuMs": 288, "phase": "render"}) + "\n",
    encoding="utf-8")
  recent.chmod(0o644)
  report = inspect(workspace)
  assert report["logs_checked"] == 5
  assert report["loop_blocks"][0]["pid"] == 100


def test_tail_keeps_first_event_when_window_starts_at_line_boundary(tmp_path, monkeypatch):
  logs = tmp_path / "logs"
  logs.mkdir()
  event = json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 321,
    "message": "ui.loop-blocked", "blockedMs": 17, "cpuMs": 9, "phase": "paint"}).encode()
  path = logs / "omp.2026-09-27.321.log"
  path.write_bytes(b"discarded line\n" + event + b"\n")
  path.chmod(0o600)
  monkeypatch.setattr(omp_input_diagnostics, "_MAX_BYTES", len(event) + 1)
  from agentcfg.storage import Tree
  with Tree(logs, private=False) as tree:
    lines = _tail(tree, path.name)
  assert [_event(line) for line in lines] == [{"timestamp": "2026-09-27T12:00:00.000+08:00",
    "pid": 321, "blocked_ms": 17, "cpu_ms": 9, "phase": "paint"}]


def test_tail_discards_first_fragment_when_window_starts_inside_line(tmp_path, monkeypatch):
  logs = tmp_path / "logs"
  logs.mkdir()
  first = json.dumps({"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 111,
    "message": "ui.loop-blocked", "blockedMs": 31, "cpuMs": 7, "phase": "paint"}).encode()
  second = json.dumps({"timestamp": "2026-09-27T12:00:01.000+08:00", "pid": 222,
    "message": "ui.loop-blocked", "blockedMs": 41, "cpuMs": 8, "phase": "render"}).encode()
  path = logs / "omp.2026-09-27.222.log"
  path.write_bytes(first + b"\n" + second + b"\n")
  path.chmod(0o600)
  monkeypatch.setattr(omp_input_diagnostics, "_MAX_BYTES", len(second) + 4)
  from agentcfg.storage import Tree
  with Tree(logs, private=False) as tree:
    events = [event for event in (_event(line) for line in _tail(tree, path.name)) if event]
  assert [event["pid"] for event in events] == [222]
