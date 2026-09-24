from pathlib import Path
import json
import os

import pytest

from agentcfg import deployment, runtime
from agentcfg.omp import OmpAdapter, classify_operation, validate_managed_argv
from agentcfg.omp_identity import native_identity
from agentcfg.schema import ConfigError

from test_omp_adapter import REPO
from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery, runtime_workspace


def test_only_explicit_openai_codex_login_is_allowed():
  validate_managed_argv(("login", "openai-codex"))
  for argv in (("login",), ("login", "other"), ("login", "openai-codex", "extra")):
    with pytest.raises(ConfigError):
      validate_managed_argv(argv)


def test_login_uses_neutral_identity_and_does_not_add_session_argument(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "project"
  cwd.mkdir()
  foreign = tmp_path / "foreign-auth"
  foreign.write_text("OLD_AUTH_SENTINEL")
  state_path = workspace.state_root / "deployment.json"
  state = json.loads(state_path.read_bytes())
  state["current"]["launch"]["environment"].extend((
    {"name": "PROVIDER_MISSING_KEY", "required": True, "secret_ref": "secret:provider-missing"},
    {"name": "MCP_MISSING_ENV", "required": True, "secret_ref": "secret:mcp-missing"}))
  state_path.write_bytes(deployment.json_bytes(state))
  os.chmod(state_path, 0o600)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=cwd, arguments=("login", "openai-codex")) == 0
  call = fake_subprocess.calls[0]
  identity = native_identity(workspace.profile, workspace.instance)
  assert tuple(call["argv"][-2:]) == ("login", "openai-codex")
  assert "--no-title" not in call["argv"] and call["cwd"] == identity.home
  assert call["env"]["HOME"] == str(identity.home)
  assert foreign.read_text() == "OLD_AUTH_SENTINEL"


def test_information_operation_does_not_resolve_deployed_session_secrets(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  state_path = workspace.state_root / "deployment.json"
  state = json.loads(state_path.read_bytes())
  state["current"]["launch"]["environment"].append(
    {"name": "PROVIDER_MISSING_KEY", "required": True, "secret_ref": "secret:provider-missing"})
  state_path.write_bytes(deployment.json_bytes(state))
  os.chmod(state_path, 0o600)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=tmp_path, arguments=("--help",)) == 0
  assert "PROVIDER_MISSING_KEY" not in fake_subprocess.calls[0]["env"]


@pytest.mark.parametrize("arguments", [("--print", "usage"), ("--model", "gateway/large-v1", "usage")])
def test_usage_text_after_options_remains_a_session(arguments):
  assert classify_operation(arguments) == "session"


def test_bootstrap_without_models_can_classify_login_without_secret_resolution():
  assert classify_operation(("login", "openai-codex")) == "login"
  data = {"machine": {"paths": {}}, "profile": {"id": "bootstrap", "agent": "omp", "providers": [],
    "models": [], "rules": [], "skills": [], "plugins": [], "mcp": [], "roles": {},
    "agent_options": {"discovery": {"project_resources": False, "project_roots": []},
      "resources": {"prompts": [], "themes": []}}}, "providers": {}, "models": {}, "mcp": {}}
  OmpAdapter(REPO).validate_arguments(("login", "openai-codex"))
