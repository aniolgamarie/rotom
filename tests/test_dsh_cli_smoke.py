"""CLI smoke 组织路径的离线验收；不启动宿主、不联网。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dsh_cli_smoke", REPO / "scripts/smoke-dsh-ui.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_cli_uses_file_selector_and_preserves_cwd(tmp_path):
  machine = tmp_path / "机器 配置.toml"
  project = tmp_path / "项目 中文"
  assert smoke.agentcfg_cli_argv(REPO, machine, "run", project) == [
    str(REPO / "agentcfg"), "--local", str(machine), "--profile", "dsh-default", "run", "--cwd", str(project)]


def test_projection_preserves_original_receipt_and_links(tmp_path):
  source = tmp_path / "source"
  source.mkdir(mode=0o700)
  marker = source / ".agentcfg-ready"
  marker.write_text("existing-seal\n")
  marker.chmod(0o600)
  (source / "package.json").write_text("{}")
  (source / "package-link").symlink_to("package.json")
  destination = tmp_path / "instance/runtimes/identity"
  seen = []
  backend = SimpleNamespace(root=lambda *_: destination,
    status=lambda *_: seen.append(destination.joinpath(".agentcfg-ready").read_bytes()) or "installed")
  workspace = SimpleNamespace(backend=backend)
  assert smoke.project_sealed_runtime(workspace, source, "identity") == destination
  assert seen == [b"existing-seal\n"]
  assert (destination / ".agentcfg-ready").stat().st_mode & 0o777 == 0o600
  assert (destination / "package-link").is_symlink()
  assert marker.read_bytes() == b"existing-seal\n"


def test_invalid_projection_prevents_any_cli_process(tmp_path):
  source = tmp_path / "source"
  source.mkdir(mode=0o700)
  destination = tmp_path / "instance/runtimes/identity"
  workspace = SimpleNamespace(backend=SimpleNamespace(root=lambda *_: destination, status=lambda *_: "damaged"))
  with pytest.raises(RuntimeError, match="RUNTIME_PROJECTION_INVALID"):
    smoke.prepare_agentcfg_cli(REPO, workspace, tmp_path / "machine", source, "identity",
      tmp_path, {}, {}, tmp_path)


def test_cli_preparation_records_exits_and_stops_before_sync(tmp_path, monkeypatch):
  source = tmp_path / "source"
  source.mkdir(mode=0o700)
  destination = tmp_path / "instance/runtimes/identity"
  workspace = SimpleNamespace(backend=SimpleNamespace(root=lambda *_: destination, status=lambda *_: "installed"))
  calls = []
  def fake_run(argv, **kwargs):
    calls.append(argv)
    return SimpleNamespace(returncode=4, stdout=b"apply conflict\n", stderr=b"")
  monkeypatch.setattr(smoke.subprocess, "run", fake_run)
  result = {"checks": {}}
  with pytest.raises(RuntimeError, match="CLI_PREPARATION_FAILED"):
    smoke.prepare_agentcfg_cli(REPO, workspace, tmp_path / "machine", source, "identity",
      tmp_path, {}, result, tmp_path)
  assert len(calls) == 1 and calls[0][-1] == "apply"
  assert result["cli_preparation"] == [{"argv": calls[0], "exit": 4}]
  assert (tmp_path / "cli-apply.log").read_bytes() == b"apply conflict\n"


def test_cli_preparation_success_runs_apply_then_sync(tmp_path, monkeypatch):
  source = tmp_path / "source"
  source.mkdir(mode=0o700)
  destination = tmp_path / "instance/runtimes/identity"
  workspace = SimpleNamespace(backend=SimpleNamespace(root=lambda *_: destination, status=lambda *_: "installed"))
  calls = []
  def fake_run(argv, **kwargs):
    calls.append(argv)
    return SimpleNamespace(returncode=0, stdout=b"installed\n", stderr=b"")
  monkeypatch.setattr(smoke.subprocess, "run", fake_run)
  result = {"checks": {}}
  argv = smoke.prepare_agentcfg_cli(REPO, workspace, tmp_path / "machine", source, "identity",
    tmp_path, {}, result, tmp_path)
  assert [item[-1] for item in calls] == ["apply", "sync"]
  assert argv[-3:] == ["run", "--cwd", str(tmp_path)]
  assert [item["exit"] for item in result["cli_preparation"]] == [0, 0]
  assert result["checks"]["sealed_runtime_installed_before_sync"] == "PASS"


def test_teams_fixture_is_explicit_and_preserves_default_plugins():
  import tomllib
  assert smoke.fixture_plugin_override(REPO) == ""
  plugins = tomllib.loads(smoke.fixture_plugin_override(REPO, True))["plugins"]
  defaults = tomllib.loads((REPO / "agents/dsh/agent.toml").read_text())["defaults"]["plugins"]
  assert plugins == defaults + ["agent-teams"]
  assert "auto-review" in plugins
