"""新 Pi 真管理管线、假 npm/CLI：不执行任何第三方代码。"""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from agentcfg import commands, run_owners, runtime
from agentcfg.pi import PiAdapter
from agentcfg.process import DependencyError
from agentcfg.secrets import CredentialError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY
from test_pi_reboot_dependencies import fake_npm, recipe_repository


@pytest.fixture
def pipeline(fake_npm, tmp_path, monkeypatch):
  repository, backend, calls = fake_npm
  for directory in ("schemas", "templates"):
    shutil.copytree(REPOSITORY / "agents/pi" / directory, repository / "agents/pi" / directory, dirs_exist_ok=True)
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  workspace.repository = repository
  workspace.adapter = PiAdapter(repository)
  lock = backend.resolve_lock(repository)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 54321, "birth_id": "synthetic-boot:234"})
  monkeypatch.setattr(runtime, "checked", lambda *args, **kwargs: "v24.14.0")
  launched = []
  def fake_cli(argv, **kwargs):
    launched.append((tuple(argv), kwargs))
    assert argv[0] == "node" and argv[1].endswith(PiAdapter.__module__.split(".")[-1] + "-coding-agent/dist/bundle/cli.js")
    return SimpleNamespace(returncode=17)
  monkeypatch.setattr(runtime.subprocess, "run", fake_cli)
  return workspace, backend, lock, calls, launched


def prepare(workspace, backend, lock):
  backend.sync(workspace, lock)
  return commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))


def test_complete_pipeline_launches_only_prepared_official_entry_and_keeps_native_exit(pipeline, tmp_path):
  workspace, backend, lock, calls, launched = pipeline
  prepare(workspace, backend, lock)
  npm_calls = list(calls)
  assert runtime.run(workspace, cwd=tmp_path) == 17
  assert runtime.run(workspace, cwd=tmp_path) == 17
  assert len(launched) == 2 and calls == npm_calls
  argv, options = launched[0]
  assert "--approve" not in argv and "--no-approve" not in argv and "--no-mcp" in argv
  assert options["env"]["PI_CODING_AGENT_DIR"] == str(workspace.instance / "pi-home")
  assert options["env"]["PI_CODING_AGENT_SESSION_DIR"] == str(workspace.instance / "pi-home/sessions")
  records = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
  assert len(records) == 2 and all(record["state"] == "unknown" for record in records.values())
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))


def test_missing_runtime_refuses_before_credentials_or_cli(pipeline, tmp_path, monkeypatch):
  workspace, backend, lock, calls, launched = pipeline
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  monkeypatch.setattr(type(workspace.secret_store), "resolve", lambda *args, **kwargs: pytest.fail("secret read before dependencies"))
  with pytest.raises(DependencyError): runtime.run(workspace, cwd=tmp_path)
  assert not launched


def test_missing_credential_has_no_cli_or_run_record(pipeline, tmp_path, monkeypatch):
  workspace, backend, lock, calls, launched = pipeline
  prepare(workspace, backend, lock)
  def missing(*args, **kwargs): raise CredentialError()
  monkeypatch.setattr(type(workspace.secret_store), "resolve", missing)
  with pytest.raises(CredentialError): runtime.run(workspace, cwd=tmp_path)
  assert not launched and not (workspace.state_root / "run-owners").exists()


def test_loading_drift_is_not_repaired_or_installed_by_run(pipeline, tmp_path):
  workspace, backend, lock, calls, launched = pipeline
  prepare(workspace, backend, lock)
  settings = workspace.instance / "pi-home/settings.json"
  data = json.loads(settings.read_text())
  data["packages"] = ["npm:unapproved@1.0.0"]
  settings.write_text(json.dumps(data))
  before, npm_calls = settings.read_bytes(), list(calls)
  with pytest.raises(Conflict): runtime.run(workspace, cwd=tmp_path)
  assert settings.read_bytes() == before and calls == npm_calls and not launched


def doctor_report(workspace, monkeypatch, capsys, *, input=False):
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  args = SimpleNamespace(live=False, input=input, format="json")
  assert commands.cmd_doctor(args) == 0
  return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("input", [False, True])
def test_doctor_blocks_changed_selection_without_projection_or_dependency_changes(
    pipeline, monkeypatch, capsys, input):
  workspace, backend, lock, calls, launched = pipeline
  prepare(workspace, backend, lock)
  candidate = workspace.candidate(lock.identity)
  runtime_identity = runtime.runtime_identity(workspace, lock)
  native_files = {path: path.read_bytes() for path in workspace.instance.rglob("*") if path.is_file()}
  npm_calls = list(calls)
  monkeypatch.setattr(type(workspace.secret_store), "resolve", lambda *args, **kwargs: pytest.fail("doctor resolved secret"))
  before = doctor_report(workspace, monkeypatch, capsys, input=input)
  assert before["deployed_binding_matches_current"] is True
  assert before["verification"]["deployment"] == "passed"

  # 来源元数据参与运行选择，但不投影到原生文件，也不改变依赖身份。
  workspace.resolved.data["models"]["example-main"]["source"] = "synthetic selection metadata"
  assert workspace.candidate(lock.identity).artifacts == candidate.artifacts
  assert runtime.runtime_identity(workspace, lock) == runtime_identity
  report = doctor_report(workspace, monkeypatch, capsys, input=input)
  readiness = report["input_diagnostics"]["readiness"] if input else report["readiness"]
  assert report["deployed_binding_matches_current"] is False
  assert report["deployed_runtime_matches_current"] is True
  assert report["dependencies"] == report["deployed_dependencies"] == "installed"
  assert not report["drift"] and not report["conflicts"] and report["changes_pending"] == 0
  assert readiness["status"] == "action-required"
  assert readiness["blockers"] == ["deployed-binding-mismatch"]
  assert readiness["next_commands"] == ["plan", "apply"]
  assert report["verification"]["deployment"] == "blocked"
  assert "selection_digest" not in json.dumps(report)
  assert "synthetic selection metadata" not in json.dumps(report)
  assert {path: path.read_bytes() for path in native_files} == native_files
  assert calls == npm_calls and not launched

  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  restored = doctor_report(workspace, monkeypatch, capsys, input=input)
  readiness = restored["input_diagnostics"]["readiness"] if input else restored["readiness"]
  assert restored["deployed_binding_matches_current"] is True
  assert readiness["status"] == "offline-ready"
  assert restored["verification"]["deployment"] == "passed"
  assert calls == npm_calls and not launched


@pytest.mark.parametrize("input", [False, True])
def test_doctor_requires_apply_for_new_runtime_without_native_or_binding_changes(
    pipeline, monkeypatch, capsys, input):
  workspace, backend, lock, calls, launched = pipeline
  prepare(workspace, backend, lock)
  candidate = workspace.candidate(lock.identity)
  binding = workspace.adapter.runtime_binding(workspace.resolved.data, workspace.instance)
  native_files = {path: path.read_bytes() for path in (workspace.instance / "pi-home").rglob("*") if path.is_file()}
  before = doctor_report(workspace, monkeypatch, capsys, input=input)
  assert before["verification"]["deployment"] == "passed"

  # 自有支持资源变化只更换密封运行包；原生配置和选择契约保持一致。
  source = workspace.repository / "agents/pi/support/status-observer.mjs"
  source.write_bytes(source.read_bytes() + b"\n// synthetic support revision\n")
  current = backend.resolve_lock_for(workspace)
  backend.sync(workspace, current)
  assert workspace.candidate(current.identity).artifacts == candidate.artifacts
  assert workspace.adapter.runtime_binding(workspace.resolved.data, workspace.instance) == binding
  npm_calls = list(calls)
  monkeypatch.setattr(type(workspace.secret_store), "resolve", lambda *args, **kwargs: pytest.fail("doctor resolved secret"))
  report = doctor_report(workspace, monkeypatch, capsys, input=input)
  readiness = report["input_diagnostics"]["readiness"] if input else report["readiness"]
  assert report["deployed_binding_matches_current"] is True
  assert report["deployed_runtime_matches_current"] is False
  assert report["dependencies"] == report["deployed_dependencies"] == "installed"
  assert not report["drift"] and not report["conflicts"] and report["changes_pending"] == 0
  assert readiness["status"] == "action-required"
  assert readiness["blockers"] == ["deployed-runtime-mismatch"]
  assert readiness["next_commands"] == ["plan", "apply"]
  assert report["verification"]["deployment"] == "blocked"
  assert {path: path.read_bytes() for path in native_files} == native_files
  assert calls == npm_calls and not launched

  commands.apply_candidate(workspace, current, workspace.candidate(current.identity))
  restored = doctor_report(workspace, monkeypatch, capsys, input=input)
  readiness = restored["input_diagnostics"]["readiness"] if input else restored["readiness"]
  assert restored["deployed_runtime_matches_current"] is True
  assert readiness["status"] == "offline-ready"
  assert restored["deployed_binding_matches_current"] is True
  assert restored["verification"]["deployment"] == "passed"
  assert calls == npm_calls and not launched


def test_doctor_does_not_claim_binding_validation_without_deployment_or_validator(pipeline, monkeypatch, capsys):
  workspace, backend, lock, _, launched = pipeline
  report = doctor_report(workspace, monkeypatch, capsys)
  assert "deployed_binding_matches_current" not in report
  assert report["verification"]["deployment"] == "not_run"
  prepare(workspace, backend, lock)
  monkeypatch.delattr(PiAdapter, "validate_runtime_binding")
  report = doctor_report(workspace, monkeypatch, capsys)
  assert "deployed_binding_matches_current" not in report
  assert not launched


def test_doctor_does_not_swallow_unexpected_binding_validation_errors(pipeline, monkeypatch):
  workspace, backend, lock, _, launched = pipeline
  prepare(workspace, backend, lock)
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  def broken(*args):
    raise RuntimeError("synthetic validator failure")
  monkeypatch.setattr(PiAdapter, "validate_runtime_binding", broken)
  with pytest.raises(RuntimeError, match="synthetic validator failure"):
    commands.cmd_doctor(SimpleNamespace(live=False, format="json"))
  assert not launched
