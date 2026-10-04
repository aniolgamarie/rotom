"""本地执行路线只能由受管启动提供；不用真实账号、宿主或模型。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.omp import (CALLER_IDENTITY_ENV, NATIVE_EXECUTION_ROUTE_ENV,
  NATIVE_EXECUTION_ROUTE, OmpAdapter, validate_managed_argv)
from agentcfg.process import launch_environment
from agentcfg.schema import ConfigError
from test_omp_adapter import omp_data
from test_omp_permission_control import configured


REPO = Path(__file__).resolve().parents[1]


def route_workspace(tmp_path, native):
  data = configured()
  data["profile"]["id"] = "shell-route-test"
  data["machine"] = {"environment": {"inherit": [], "values": {}}}
  data["providers"]["fictional"]["credential_ref"] = "secret:placeholder"
  if native is not None:
    data["profile"]["agent_options"]["permission_control"]["native_bash"] = native
  workspace = SimpleNamespace(profile=data["profile"]["id"], instance=tmp_path / "instance",
    resolved=SimpleNamespace(data=data))
  adapter = OmpAdapter(REPO)
  spec = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=workspace.instance, lock_identity="a" * 64)
  return adapter, workspace, spec


@pytest.fixture(autouse=True)
def clear_route_environment(monkeypatch):
  for name in CALLER_IDENTITY_ENV | {NATIVE_EXECUTION_ROUTE_ENV}:
    monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("native", [None, False, True])
def test_route_binding_preserves_selected_shell_and_only_enables_native(tmp_path, monkeypatch, native):
  monkeypatch.setenv("SHELL", "/bin/zsh")
  adapter, workspace, spec = route_workspace(tmp_path, native)
  env = launch_environment(spec, workspace.resolved.data["machine"], SimpleNamespace(resolve=lambda *a, **kw: None))
  assert env["SHELL"] == "/bin/zsh"
  assert "SHELL" not in {binding.name for binding in spec.environment}
  assert env.get(NATIVE_EXECUTION_ROUTE_ENV) == (NATIVE_EXECUTION_ROUTE if native else None)
  adapter.validate_operation_environment(workspace, spec=spec, env=env)


def test_machine_shell_preference_is_preserved_without_claiming_route(tmp_path, monkeypatch):
  monkeypatch.setenv("SHELL", "/bin/bash")
  adapter, workspace, spec = route_workspace(tmp_path, True)
  workspace.resolved.data["machine"]["environment"]["values"]["SHELL"] = "/bin/zsh"
  env = launch_environment(spec, workspace.resolved.data["machine"], SimpleNamespace(resolve=lambda *a, **kw: None))
  assert env["SHELL"] == "/bin/zsh"
  assert env[NATIVE_EXECUTION_ROUTE_ENV] == NATIVE_EXECUTION_ROUTE
  adapter.validate_operation_environment(workspace, env=env)


@pytest.mark.parametrize("location", ["inherit", "values"])
def test_machine_cannot_claim_local_execution_route(location):
  data = omp_data()
  data["machine"]["environment"][location] = ([NATIVE_EXECUTION_ROUTE_ENV] if location == "inherit"
    else {NATIVE_EXECUTION_ROUTE_ENV: NATIVE_EXECUTION_ROUTE})
  with pytest.raises(ConfigError, match="omp-identity-environment-override"):
    OmpAdapter(REPO).validate(data)


@pytest.mark.parametrize("value", [NATIVE_EXECUTION_ROUTE, "unknown", ""])
def test_caller_cannot_supply_route(tmp_path, monkeypatch, value):
  adapter, workspace, _ = route_workspace(tmp_path, True)
  monkeypatch.setenv(NATIVE_EXECUTION_ROUTE_ENV, value)
  with pytest.raises(ConfigError, match="omp-caller-identity-environment"):
    adapter.validate_operation_environment(workspace)


@pytest.mark.parametrize("native,value", [(True, None), (True, "unknown"), (False, NATIVE_EXECUTION_ROUTE), (False, "")])
def test_final_environment_must_match_route_contract(tmp_path, native, value):
  adapter, workspace, spec = route_workspace(tmp_path, native)
  env = launch_environment(spec, workspace.resolved.data["machine"], SimpleNamespace(resolve=lambda *a, **kw: None))
  if value is None:
    env.pop(NATIVE_EXECUTION_ROUTE_ENV, None)
  else:
    env[NATIVE_EXECUTION_ROUTE_ENV] = value
  with pytest.raises(ConfigError, match="omp-operation-environment-mismatch"):
    adapter.validate_operation_environment(workspace, spec=spec, env=env)


@pytest.mark.parametrize("arguments", [("acp",), ("--mode", "acp"), ("--mode=rpc-ui",), ("--unknown",)])
def test_managed_launch_cannot_select_client_terminal(arguments):
  with pytest.raises(ConfigError):
    validate_managed_argv(arguments)


def test_route_keywords_in_model_or_prompt_are_not_execution_modes():
  validate_managed_argv(["--model", "acp", "--", "acp", "--mode=rpc-ui"])
