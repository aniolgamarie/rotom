"""新 main 命名代理与统一入口的组合；不调用宿主或读取真实配置。"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import cli as legacy, commands
from rotom import cli
from test_omp_execution_contract import contract_workspace


@pytest.mark.parametrize("tool", ["dsh", "pi", "omp"])
def test_short_run_forwards_named_proxy_without_changing_native_tail(monkeypatch, tmp_path, tool):
  seen = []
  def selection(args):
    args.cwd = Path(args.cwd or tmp_path)
  monkeypatch.setattr(legacy, "resolve_selection", selection)
  monkeypatch.setattr(commands, "workspace", lambda args: SimpleNamespace(profile=args.profile, agent=tool))
  monkeypatch.setattr(commands.runtime, "run", lambda workspace, **options: seen.append(options) or 17)
  native = ["--proxy", "native-only", "--help"]
  assert cli.main(["--no-input", "run", tool, "--proxy", "fixture", "--", *native]) == 17
  assert seen[0]["proxy"] == "fixture" and seen[0]["arguments"] == native
  assert seen[0]["cwd"] == tmp_path


def test_proxy_help_is_static_and_completion_metadata_keeps_the_option(monkeypatch, capsys):
  from agentcfg import config
  monkeypatch.setattr(config, "load_local", lambda *a, **k: pytest.fail("help read machine config"))
  assert cli.main(["run", "--help"]) == 0
  output = capsys.readouterr().out
  assert "--proxy" in output and "仅本次" in output
  _, actions = dict(cli.parser_leaves(cli.build_parser()))[("run",)]
  assert any(action.dest == "proxy" and "--proxy" in action.option_strings for action in actions)


def test_work_settings_accept_named_proxy_without_resolving_secrets(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  from termcfg.work_config import read_settings
  from test_work_config import local_file
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret read"))
  path = local_file(tmp_path, '\n[machine.environment]\nproxy="fixture"\n'
    '[machine.proxies.fixture]\nurl="http://proxy.example.invalid:8080"\n')
  assert read_settings(local=path).session == "main"


@pytest.mark.parametrize("operation", ["launch_operation", "resume_operation", "select_environment"])
def test_named_proxy_cannot_bypass_special_runtime_operation_gate(contract_workspace, fake_subprocess, monkeypatch, operation):
  from agentcfg import runtime
  from agentcfg.schema import ConfigError
  from test_execution_environment_runtime import _apply, _forbid_secrets
  fixture = contract_workspace
  _apply(fixture)
  _forbid_secrets(monkeypatch, fixture.workspace)
  def forbidden(*args, **kwargs):
    pytest.fail("special operation invoked")
  with pytest.raises(ConfigError, match="environment-overrides-operation"):
    runtime.run(fixture.workspace, cwd=fixture.cwd, proxy="fixture", **{operation: forbidden})
  assert not fake_subprocess.calls
