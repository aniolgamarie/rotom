"""普通宿主环境覆盖的离线端到端回归；不执行真实宿主。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from agentcfg import execution_environment, runtime
from agentcfg.adapter import EnvironmentBinding, LaunchSpec
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_omp_execution_contract import REPO, contract_workspace, _apply, _legacy, _saved


def _forbid_secrets(monkeypatch, workspace):
  def forbidden(*args, **kwargs):
    pytest.fail("拒绝路径不得解析 SecretRef")
  monkeypatch.setattr(workspace, "secret_store", SimpleNamespace(resolve=forbidden))


@pytest.mark.parametrize("scope", ["machine", "one-shot"])
def test_omp_explicit_tool_unset_survives_adapter(contract_workspace, fake_subprocess, scope):
  fixture = contract_workspace
  if scope == "machine":
    fixture.workspace.resolved.data["machine"]["environment"]["unset"] = ["GIT_CONFIG_GLOBAL"]
  _apply(fixture)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd,
    unset_env=("GIT_CONFIG_GLOBAL",) if scope == "one-shot" else ()) == 0
  assert len(fake_subprocess.calls) == 1
  assert "GIT_CONFIG_GLOBAL" not in fake_subprocess.calls[0]["env"]


def test_one_shot_inherit_overrides_persistent_value_only_for_this_run(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  fixture.workspace.resolved.data["machine"]["environment"]["values"]["FIXTURE_MODE"] = "persistent"
  monkeypatch.setenv("FIXTURE_MODE", "caller")
  _apply(fixture)
  for inherit, expected in [(("FIXTURE_MODE",), "caller"), ((), "persistent")]:
    fake_subprocess.queue(returncode=0)
    assert runtime.run(fixture.workspace, cwd=fixture.cwd, inherit_env=inherit) == 0
    assert fake_subprocess.calls[-1]["env"]["FIXTURE_MODE"] == expected
  assert len(fake_subprocess.calls) == 2


def test_missing_one_shot_inherit_does_not_fall_back_to_machine_value(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  fixture.workspace.resolved.data["machine"]["environment"]["values"]["FIXTURE_MODE"] = "persistent"
  monkeypatch.delenv("FIXTURE_MODE", raising=False)
  _apply(fixture)
  _forbid_secrets(monkeypatch, fixture.workspace)
  with pytest.raises(ConfigError, match="environment-explicit-inherit-missing"):
    runtime.run(fixture.workspace, cwd=fixture.cwd, inherit_env=("FIXTURE_MODE",))
  assert not fake_subprocess.calls


@pytest.mark.parametrize("field,value", [("values", {"FIXTURE_MODE": "changed"}), ("unset", ["TERM"])])
def test_stale_environment_declaration_conflicts_before_secrets(contract_workspace, fake_subprocess, monkeypatch, field, value):
  fixture = contract_workspace
  _apply(fixture)
  fixture.workspace.resolved.data["machine"]["environment"][field] = value
  _forbid_secrets(monkeypatch, fixture.workspace)
  with pytest.raises(Conflict, match="环境声明已变化") as error:
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert error.value.exit_code == 4
  assert not fake_subprocess.calls


def test_one_shot_node_env_checks_effective_dotenv_before_secrets(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  _apply(fixture)
  monkeypatch.setenv("NODE_ENV", "fixture-mode")
  (fixture.cwd / ".env.fixture-mode.local").write_text("SYNTHETIC=must-not-load\n")
  _forbid_secrets(monkeypatch, fixture.workspace)
  with pytest.raises(Conflict, match="dotenv"):
    runtime.run(fixture.workspace, cwd=fixture.cwd, inherit_env=("NODE_ENV",))
  assert not fake_subprocess.calls


@pytest.mark.parametrize("name", ["HOME", "XDG_CONFIG_HOME"])
def test_caller_identity_drift_requires_apply_before_secrets(contract_workspace, fake_subprocess, monkeypatch, name):
  fixture = contract_workspace
  _apply(fixture)
  monkeypatch.setenv(name, str(fixture.cwd / "new-caller-path"))
  _forbid_secrets(monkeypatch, fixture.workspace)
  with pytest.raises(Conflict):
    runtime.run(fixture.workspace, cwd=fixture.cwd)
  assert not fake_subprocess.calls


def test_environment_contract_apply_and_configuration_rollback_preserve_native_state(contract_workspace):
  from agentcfg import deployment
  fixture = contract_workspace
  old = _legacy(fixture)
  _apply(fixture, contract=old)
  sentinel = fixture.workspace.instance / "user-home/synthetic-session.json"
  sentinel.parent.mkdir(parents=True, exist_ok=True)
  sentinel.write_bytes(b"synthetic-native-session-and-account-placeholder")
  _apply(fixture)
  current = json.loads(_saved(fixture.workspace))["current"]["launch"]
  assert current["environment_version"] == 1 and current["environment_policy"] == "caller"
  assert sentinel.read_bytes() == b"synthetic-native-session-and-account-placeholder"
  deployment.rollback(fixture.workspace.instance, fixture.workspace.state_root, fixture.workspace.binding)
  restored = json.loads(_saved(fixture.workspace))["current"]["launch"]
  assert "environment_version" not in restored
  assert sentinel.read_bytes() == b"synthetic-native-session-and-account-placeholder"


def _pi_environment():
  adapter = PiAdapter(REPO)
  workspace = SimpleNamespace(adapter=adapter, schemas=adapter.schemas(), resolved=SimpleNamespace(data={
    "profile": {"agent": "pi"},
    "adapter_documents": {"agent": {"defaults": {}}, "plugins": {"plugins": {}}}}))
  contract = {"machine": {"environment": {"inherit": [], "values": {}}}, "lock_identity": "d" * 64}
  return workspace, contract


@pytest.mark.parametrize("name", ["PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "CODEX_HOME", "BUN_OPTIONS", "BUN_RUNTIME_TRANSPILER_CACHE_PATH"])
@pytest.mark.parametrize("operation", ["inherit", "unset"])
def test_pi_one_shot_uses_adapter_reserved_policy(tmp_path, monkeypatch, name, operation):
  workspace, contract = _pi_environment()
  monkeypatch.setenv(name, "synthetic-reserved-value")
  spec = LaunchSpec(("/synthetic/node",), tmp_path, contract["lock_identity"], (), environment_policy="caller")
  with pytest.raises(ConfigError):
    runtime.prepare_environment(workspace, contract, spec, **{operation: (name,)})


def test_fixed_bun_options_clear_is_reported_without_value(tmp_path, monkeypatch, capsys):
  workspace, contract = _pi_environment()
  marker = "synthetic-private-bun-option-marker"
  monkeypatch.setenv("BUN_OPTIONS", marker)
  spec = LaunchSpec(("/synthetic/bun",), tmp_path, contract["lock_identity"],
    (EnvironmentBinding("BUN_OPTIONS", ""),), environment_policy="caller")
  env, report = runtime.prepare_environment(workspace, contract, spec)
  assert env["BUN_OPTIONS"] == ""
  assert {"name": "BUN_OPTIONS", "status": "overridden", "source": "adapter-policy"} in report["variables"]
  execution_environment.warn(report)
  output = capsys.readouterr().err
  assert "BUN_OPTIONS: overridden" in output
  for text in (output, repr(report)):
    assert marker not in text
    assert hashlib.sha256(marker.encode()).hexdigest() not in text


def test_caller_path_is_not_prefixed_with_runtime_bin(contract_workspace, fake_subprocess, monkeypatch):
  fixture = contract_workspace
  _apply(fixture)
  current_path = str(fixture.tool_home / "new-user-bin") + ":" + str(fixture.user_bin)
  monkeypatch.setenv("PATH", current_path)
  fake_subprocess.queue(returncode=0)
  assert runtime.run(fixture.workspace, cwd=fixture.cwd) == 0
  assert len(fake_subprocess.calls) == 1
  assert fake_subprocess.calls[0]["env"]["PATH"] == current_path
  assert str(fixture.workspace.cache / "runtimes") not in fake_subprocess.calls[0]["env"]["PATH"]
