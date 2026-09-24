import json

import pytest

from agentcfg import deployment, usage
from agentcfg import cli, commands
from agentcfg.omp_identity import lifecycle_guard, native_identity
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_omp_runtime_foundation import runtime_workspace, clear_omp_identity_environment, isolate_runtime_discovery


@pytest.mark.parametrize("tail", [
  ["--profile=x"], ["--profile", "x"], ["--alias=x"], ["--config=x"],
  ["--cwd=x"], ["-C", "x"], ["--extension=x"], ["-e", "x"],
  ["--api-key=x"], ["--auth-broker=x"], ["--session-dir=x"],
])
def test_managed_usage_rejects_identity_source_and_secret_options(tail):
  with pytest.raises(ConfigError):
    usage.validate_managed_tail(tail)


@pytest.mark.parametrize("tail", [
  ["--json", "--provider", "openai-codex"], ["-j", "-p", "zai", "-r"],
  ["clients", "--days=30"], ["invalidate", "--provider=kimi-code"],
  ["--history", "-d", "7"], ["--future-native-option", "value"],
  ["--", "--profile=literal"],
])
def test_managed_usage_preserves_native_query_grammar(tail):
  usage.validate_managed_tail(tail)


def test_managed_usage_uses_deployed_identity_without_unrelated_secrets(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  state_path = workspace.state_root / "deployment.json"
  state = json.loads(state_path.read_bytes())
  state["current"]["launch"]["environment"].append({"name": "AGENTCFG_OMP_UNUSED", "required": True, "secret_ref": "secret:absent"})
  state_path.write_bytes(deployment.json_bytes(state))
  fake_subprocess.queue(returncode=17)
  assert usage.run_managed(workspace, ["--", "--json", "--provider", "openai-codex"]) == 17
  call = fake_subprocess.calls[0]
  identity = native_identity(workspace.profile, workspace.instance)
  assert call["argv"][1:] == ["--profile", identity.native_name, "usage", "--json", "--provider", "openai-codex"]
  assert call["cwd"] == identity.home
  assert call["env"]["HOME"] == str(identity.home)
  assert "AGENTCFG_OMP_UNUSED" not in call["env"]
  assert len(call["pass_fds"]) == 3


def test_managed_usage_shares_activity_pending_and_package_gates(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  with lifecycle_guard(workspace):
    with pytest.raises(Conflict):
      usage.run_managed(workspace)
  pending = workspace.state_root / "pending.json"
  pending.write_bytes(b"{}")
  pending.chmod(0o600)
  with pytest.raises(Conflict):
    usage.run_managed(workspace)
  pending.unlink()
  workspace.backend.result = "missing"
  with pytest.raises(DependencyError) as missing:
    usage.run_managed(workspace)
  assert missing.value.exit_code == 5
  assert not fake_subprocess.calls


def test_managed_usage_rejects_foreign_adapter_and_caller_identity(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  workspace.resolved.data["profile"]["agent"] = "pi"
  with pytest.raises(ConfigError):
    usage.run_managed(workspace)
  workspace.resolved.data["profile"]["agent"] = "omp"
  monkeypatch.setenv("OMP_PROFILE", "foreign")
  with pytest.raises(ConfigError):
    usage.run_managed(workspace)
  assert not fake_subprocess.calls


def test_cli_explicit_profile_selects_managed_usage(monkeypatch):
  calls = []
  fake_workspace = object()
  def selection(args):
    assert args.profile == "omp-selected"
    assert args.local == "/private/local.toml"
    calls.append("selection")
  monkeypatch.setattr(cli, "resolve_selection", selection)
  monkeypatch.setattr(commands, "workspace", lambda args: fake_workspace)
  monkeypatch.setattr(usage, "run_managed", lambda workspace, arguments: calls.append((workspace, tuple(arguments))) or 31)
  assert cli.main(["--local", "/private/local.toml", "--profile", "omp-selected", "usage", "--", "--json"]) == 31
  assert calls == ["selection", (fake_workspace, ("--", "--json"))]
