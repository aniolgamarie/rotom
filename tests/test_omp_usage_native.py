import os
from pathlib import Path

import pytest

from agentcfg import usage
from agentcfg import cli, commands
from agentcfg.process import DependencyError


@pytest.mark.parametrize("tail,expected", [
  (["--json"], ["--json"]),
  (["--", "--provider", "zai", "--json"], ["--provider", "zai", "--json"]),
  (["--", "--", "--profile=x"], ["--", "--profile=x"]),
  (["clients", "--days", "30"], ["clients", "--days", "30"]),
  (["invalidate", "-p", "kimi-code"], ["invalidate", "-p", "kimi-code"]),
])
def test_native_preserves_context_tail_and_has_no_manager_output(monkeypatch, fake_subprocess, capsys, tail, expected):
  monkeypatch.setattr("shutil.which", lambda name: "/synthetic/bin/omp" if name == "omp" else None)
  monkeypatch.setenv("OMP_PROFILE", "caller-native")
  monkeypatch.setenv("CALLER_UNFILTERED", "synthetic")
  before = dict(os.environ)
  fake_subprocess.queue(returncode=73)
  assert usage.run_native(tail) == 73
  assert fake_subprocess.calls == [{"argv": ["/synthetic/bin/omp", "usage", *expected],
    "cwd": Path.cwd(), "env": before}]
  assert dict(os.environ) == before
  assert capsys.readouterr() == ("", "")


def test_native_missing_binary_is_dependency_error(monkeypatch, fake_subprocess):
  monkeypatch.setattr("shutil.which", lambda name: None)
  with pytest.raises(DependencyError) as error:
    usage.run_native(["--json"])
  assert error.value.exit_code == 5
  assert not fake_subprocess.calls


def test_native_signal_exit_and_spawn_error(monkeypatch, fake_subprocess):
  monkeypatch.setattr("shutil.which", lambda name: "/synthetic/bin/omp")
  fake_subprocess.queue(returncode=-15)
  assert usage.run_native() == 143
  def failed(*args, **kwargs):
    raise OSError("SENTINEL_PRIVATE_OS_ERROR")
  monkeypatch.setattr("subprocess.run", failed)
  with pytest.raises(DependencyError) as error:
    usage.run_native()
  assert "SENTINEL" not in str(error.value)


@pytest.mark.parametrize("tail", [[], ["--json"], ["--", "--json"], ["--help"], ["--profile", "native-value"]])
def test_cli_native_usage_dispatches_before_configuration(monkeypatch, tail):
  calls = []
  monkeypatch.setattr(usage, "run_native", lambda arguments: calls.append(tuple(arguments)) or 29)
  monkeypatch.setattr(cli, "resolve_selection", lambda _: pytest.fail("native usage must not read local metadata"))
  monkeypatch.setattr(commands, "workspace", lambda _: pytest.fail("native usage must not load workspace"))
  assert cli.main(["usage", *tail]) == 29
  assert calls == [tuple(tail)]


@pytest.mark.parametrize("selectors", [["--local", "/private/not-read.toml"], ["--machine", "missing"]])
def test_cli_usage_machine_selector_requires_explicit_profile(monkeypatch, selectors):
  monkeypatch.setattr(cli, "resolve_selection", lambda _: pytest.fail("must reject before file access"))
  assert cli.main([*selectors, "usage", "--json"]) == 2
