import pytest
import yaml

from agentcfg import runtime
from agentcfg.omp import OmpAdapter
from agentcfg.omp_identity import native_identity
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict

from test_omp_adapter import REPO, omp_data
from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery, runtime_workspace


@pytest.mark.parametrize("mutate", [
  lambda identity: _merge_yaml(identity.agent_dir / "config.yml", {"extensions": ["/outside/unsafe.ts"]}),
  lambda identity: _merge_yaml(identity.agent_dir / "config.yml", {"skills": {"customDirectories": ["/outside/skills"]}}),
  lambda identity: _write(identity.agent_dir / "SYSTEM.md", "unsafe system"),
  lambda identity: _write(identity.agent_dir / "SYSTEM_TEMPLATE.md", "unsafe template"),
  lambda identity: _write(identity.agent_dir / "APPEND_SYSTEM.md", "unsafe append"),
  lambda identity: _write(identity.agent_dir / "PERSONALITY.md", "unsafe personality"),
  lambda identity: _write(identity.home / ".omp/agent/SYSTEM.md", "unsafe default system"),
  lambda identity: _write(identity.home / ".omp/agent/PERSONALITY.md", "unsafe default personality"),
  lambda identity: _write(identity.home / ".omp/agent/config.yml", "extensions: [/outside/default.ts]\n"),
  lambda identity: _write(identity.home / ".omp/agent/models.yml", "providers: {outside: {apiKey: '!command'}}\n"),
])
def test_runtime_rejects_unmanaged_native_executable_and_system_sources_before_spawn(
    tmp_path, monkeypatch, fake_subprocess, mutate):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  mutate(native_identity(workspace.profile, workspace.instance))
  with pytest.raises(Conflict):
    runtime.run(workspace, cwd=tmp_path)
  assert not fake_subprocess.calls


@pytest.mark.parametrize("channel,value", [
  ("inherit", ["PI_CONFIG_DIR"]),
  ("values", {"PI_CONFIG_DIR": ".foreign"}),
])
def test_adapter_rejects_machine_config_root_redirection(channel, value):
  data = omp_data()
  data["machine"]["environment"][channel] = value
  with pytest.raises(ConfigError, match="identity-environment-override"):
    OmpAdapter(REPO).validate(data)


def test_adapter_keeps_unrelated_machine_environment_legal():
  data = omp_data()
  data["machine"]["environment"] = {"inherit": ["TERM_PROGRAM"], "values": {"OMP_FIXTURE_LABEL": "public"}}
  OmpAdapter(REPO).validate(data)


def test_runtime_rejects_caller_config_root_redirection_before_spawn(
    tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  monkeypatch.setenv("PI_CONFIG_DIR", ".foreign")
  with pytest.raises(ConfigError, match="caller-identity-environment"):
    runtime.run(workspace, cwd=tmp_path)
  assert not fake_subprocess.calls


def test_runtime_rejects_config_root_injected_into_final_environment(
    tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  original = runtime.launch_environment

  def redirected(spec, machine, store):
    env = original(spec, machine, store)
    env["PI_CONFIG_DIR"] = ".foreign"
    return env

  monkeypatch.setattr(runtime, "launch_environment", redirected)
  with pytest.raises(ConfigError, match="operation-environment-mismatch"):
    runtime.run(workspace, cwd=tmp_path)
  assert not fake_subprocess.calls


def test_runtime_rejects_unknown_models_provider_and_command_api_key_before_spawn(
    tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  identity = native_identity(workspace.profile, workspace.instance)
  _write(identity.agent_dir / "models.yml", yaml.safe_dump({"providers": {"outside": {
    "baseUrl": "https://outside.invalid/v1", "api": "openai-completions", "apiKey": "!command",
    "headers": {"Authorization": "secret"}, "models": []}}}, sort_keys=True))
  with pytest.raises(Conflict):
    runtime.run(workspace, cwd=tmp_path)
  assert not fake_subprocess.calls


def _write(path, content):
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content)


def _merge_yaml(path, patch):
  value = yaml.safe_load(path.read_bytes()) or {}
  for key, item in patch.items():
    if isinstance(item, dict) and isinstance(value.get(key), dict):
      value[key].update(item)
    else:
      value[key] = item
  path.write_text(yaml.safe_dump(value, sort_keys=True))
