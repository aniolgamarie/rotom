"""首次部署短路径：保留原命令的安全门禁与脱敏输出。"""

import os
from pathlib import Path
import time
import tomllib
from types import SimpleNamespace

import pytest

from agentcfg import cli, commands
from agentcfg.backends import DshBackend
from agentcfg.omp_dependencies import OmpBackend
from agentcfg.process import DependencyError
from agentcfg.progress import Progress
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace


def local_file(machine="work"):
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines" / f"{machine}.toml"


def test_profiles_and_selected_initialization_do_not_need_local(capsys):
  assert cli.main(["profiles"]) == 0
  listed = capsys.readouterr().out
  assert "omp-kernel\tomp" in listed
  assert "dsh-default\tdsh" in listed
  assert cli.main(["init-local", "--machine", "work", "--profile", "omp-kernel"]) == 0
  document = tomllib.loads(local_file().read_text(encoding="utf-8"))
  assert document["machine"]["default_profile"] == "omp-kernel"


def test_default_machine_short_path():
  assert cli.main(["init-local"]) == 0
  path = local_file("default")
  assert path.exists()
  assert tomllib.loads(path.read_text(encoding="utf-8"))["machine"]["id"] == "default"


def test_unknown_initial_profile_has_no_writes(capsys):
  assert cli.main(["init-local", "--machine", "work", "--profile", "missing-recipe"]) == 2
  assert not local_file().parent.exists()
  assert "missing-recipe" not in capsys.readouterr().err


def test_missing_default_recipe_has_no_writes(monkeypatch):
  original = Path.is_file
  monkeypatch.setattr(Path, "is_file", lambda path: False if path.name == "dsh-default.toml" else original(path))
  assert cli.main(["init-local", "--machine", "work"]) == 2
  assert not local_file().parent.exists()


def test_run_can_infer_agent_and_preserves_native_tail(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work", "--profile", "omp-default"]) == 0
  observed = []
  monkeypatch.setattr(cli, "dispatch", lambda args: observed.append(args) or 0)
  assert cli.main(["--machine", "work", "run", "--cwd", ".", "--", "--model", "literal"]) == 0
  assert observed[0].agent is None
  assert observed[0].profile == "omp-default"
  assert observed[0].passthrough == ["--model", "literal"]
  assert cli.main(["--machine", "work", "run", "omp", "--", "--model", "literal"]) == 0
  assert observed[1].agent == "omp"


def test_run_inferred_agent_reaches_matching_workspace():
  assert cli.main(["init-local", "--machine", "work", "--profile", "omp-default"]) == 0
  args = cli.build_parser().parse_args(["--machine", "work", "run"])
  cli.resolve_selection(args)
  assert commands.workspace(args).agent == "omp"


def test_setup_real_dsh_roundtrip_and_repeat_preserves_backup(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  calls = []
  monkeypatch.setattr(DshBackend, "sync", lambda self, workspace, lock, **kwargs: calls.append(lock.identity) or {"installed": True})
  argv = ["--machine", "work", "setup"]
  assert cli.main(argv) == 0
  w = load_workspace(local_file())
  from agentcfg.deployment import read_state
  from agentcfg.storage import Tree
  with Tree(w.state_root) as state:
    first = read_state(state)
  assert first["current"] is not None
  assert cli.main(argv) == 0
  with Tree(w.state_root) as state:
    second = read_state(state)
  assert second["previous"] == first["previous"]
  assert len(calls) == 2
  output = capsys.readouterr().out
  assert "预览 dsh/dsh-default" in output
  assert "部署完成 dsh/dsh-default" in output


@pytest.mark.parametrize("condition", ["conflict", "drift", "pending"])
def test_setup_stops_before_sync_on_unsafe_preview(condition, monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  monkeypatch.setattr(DshBackend, "sync", lambda *args, **kwargs: pytest.fail("must not sync"))
  if condition == "pending":
    monkeypatch.setattr(commands, "current_plan", lambda *args: (_ for _ in ()).throw(Conflict("pending")))
  else:
    class UnsafePlan:
      conflicts = ["redacted"] if condition == "conflict" else []
      drift = ["redacted"] if condition == "drift" else []

      def public(self):
        return {"changes": 1, "drift": len(self.drift), "conflicts": len(self.conflicts)}

    monkeypatch.setattr(commands, "current_plan", lambda *args: UnsafePlan())
  assert cli.main(["--machine", "work", "setup"]) == 4
  assert "redacted" not in capsys.readouterr().out


@pytest.mark.parametrize("error,exit_code", [
  (Conflict("synthetic sync failure"), 4),
  (DependencyError("synthetic dependency failure"), 5),
  (OSError("private path canary"), 6),
  (KeyboardInterrupt(), 130),
])
def test_setup_sync_failure_never_applies(error, exit_code, monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  def fail(self, workspace, lock, *, progress=None):
    progress("安装锁定依赖")
    raise error
  monkeypatch.setattr(DshBackend, "sync", fail)
  monkeypatch.setattr(commands, "apply_candidate", lambda *args, **kwargs: pytest.fail("must not apply"))
  assert cli.main(["--machine", "work", "setup"]) == exit_code
  output = capsys.readouterr()
  assert f"同步依赖 / 安装锁定依赖" in output.err
  assert f"退出码 {exit_code}" in output.err
  assert "./agentcfg doctor" in output.err
  assert "private path canary" not in output.out + output.err


def test_setup_rechecks_target_after_sync_and_redacts_secrets(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  canary = "private-setup-canary"
  with local_file().open("a", encoding="utf-8") as output:
    output.write(f'canary = "{canary}"\n')

  def mutate(self, workspace, lock, **kwargs):
    target = workspace.instance / "dsh-home/AGENTS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("outside change", encoding="utf-8")
    return {"installed": True}

  monkeypatch.setattr(DshBackend, "sync", mutate)
  monkeypatch.setattr(commands, "apply_candidate", lambda *args: pytest.fail("must not apply"))
  assert cli.main(["--machine", "work", "setup"]) == 4
  output = capsys.readouterr()
  assert canary not in output.out + output.err
  assert "发生变化" in output.err


def test_setup_rechecks_under_apply_lock(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  monkeypatch.setattr(DshBackend, "sync", lambda *args, **kwargs: {"installed": True})
  original = commands.apply_candidate

  def late_change(workspace, lock, candidate, *, expected_plan=None):
    target = workspace.instance / "dsh-home/AGENTS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("outside change", encoding="utf-8")
    return original(workspace, lock, candidate, expected_plan=expected_plan)

  monkeypatch.setattr(commands, "apply_candidate", late_change)
  assert cli.main(["--machine", "work", "setup"]) == 4
  assert not (load_workspace(local_file()).state_root / "deployment.json").exists()
  assert "预览后部署状态已变化" in capsys.readouterr().err


def test_omp_setup_rejects_unowned_instance_before_sync(monkeypatch):
  assert cli.main(["init-local", "--profile", "omp-default"]) == 0
  workspace = load_workspace(local_file("default"))
  workspace.instance.mkdir(parents=True, mode=0o700)
  (workspace.instance / "foreign.txt").write_text("foreign", encoding="utf-8")
  monkeypatch.setattr(OmpBackend, "sync", lambda *args, **kwargs: pytest.fail("must not sync"))
  assert cli.main(["setup"]) == 4
  assert (workspace.instance / "foreign.txt").read_text(encoding="utf-8") == "foreign"


def test_progress_heartbeat_reports_wait_without_private_data(capsys):
  args = SimpleNamespace(command="setup")
  progress = Progress("setup", args, interval=0.01)
  progress.stage("同步依赖", hint="sync")
  with progress.heartbeat():
    time.sleep(0.04)
  output = capsys.readouterr().err
  assert "仍在进行" in output
  assert "已等待" in output


def test_sync_keeps_json_stdout_and_reports_progress_stderr(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  capsys.readouterr()
  def installed(self, workspace, lock, *, progress=None):
    progress("检查运行包")
    return {"installed": True, "changed": False}
  monkeypatch.setattr(DshBackend, "sync", installed)
  assert cli.main(["--machine", "work", "sync"]) == 0
  output = capsys.readouterr()
  import json
  assert json.loads(output.out)["command"] == "sync"
  assert "sync: 同步依赖 / 检查运行包" in output.err


def test_setup_accepts_existing_backend_without_progress_parameter(monkeypatch, capsys):
  assert cli.main(["init-local", "--machine", "work"]) == 0
  monkeypatch.setattr(DshBackend, "sync", lambda self, workspace, lock: {"installed": True})
  assert cli.main(["--machine", "work", "setup"]) == 0
  assert "setup: 同步依赖 / 检查运行包" in capsys.readouterr().err
