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
    shutil.copytree(REPOSITORY / "agents/pi" / directory, repository / "agents/pi" / directory)
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
  assert "--no-approve" in argv and "--no-mcp" in argv
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
