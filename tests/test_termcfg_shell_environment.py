"""私人 hook 选择只检查合成文件元数据；默认不启动 shell。"""

import json
from pathlib import Path

import pytest

from termcfg.cli import main
from termcfg.environment import private_hook_status


@pytest.mark.parametrize("layout,expected", [
  ("absent", "absent"), ("xdg", "xdg"), ("legacy", "legacy"),
  ("conflict", "conflict"), ("shared", "shared"),
])
def test_private_hook_selection_without_opening_contents(tmp_path, monkeypatch, layout, expected):
  home, config = tmp_path / "home", tmp_path / "custom-config"
  selected = config / "termcfg/zshenv.local"
  legacy = home / ".config/termcfg/zshenv.local"
  selected.parent.mkdir(parents=True); legacy.parent.mkdir(parents=True)
  if layout in {"xdg", "conflict", "shared"}: selected.write_text("synthetic private hook\n")
  if layout in {"legacy", "conflict"}: legacy.write_text("other synthetic private hook\n")
  if layout == "shared": legacy.symlink_to(selected)
  monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("hook body must not be opened"))
  assert private_hook_status(home, str(config)) == {"zshenv": expected, "zshrc": "absent"}


@pytest.mark.parametrize("config_home", [None, ""])
def test_unset_or_empty_xdg_uses_legacy_once(tmp_path, config_home):
  hook = tmp_path / ".config/termcfg/zshrc.local"
  hook.parent.mkdir(parents=True); hook.write_text("synthetic\n")
  assert private_hook_status(tmp_path, config_home) == {"zshenv": "absent", "zshrc": "shared"}


def test_relative_xdg_refuses_fallback(tmp_path):
  hook = tmp_path / ".config/termcfg/zshrc.local"
  hook.parent.mkdir(parents=True); hook.write_text("synthetic\n")
  assert private_hook_status(tmp_path, "relative-config") == {
    "zshenv": "invalid_config_home", "zshrc": "invalid_config_home"}


def test_doctor_reports_conflict_without_private_paths_or_bodies(isolated_environment, fake_terminal_commands, capsys):
  assert main(["init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  config = Path(isolated_environment.env["XDG_CONFIG_HOME"])
  legacy = isolated_environment.home / ".config"
  assert config != legacy
  for directory in [config, legacy]:
    hook = directory / "termcfg/zshenv.local"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("PRIVATE_HOOK_CANARY\n")
  assert main(["doctor", "--component", "zsh", "--json"]) == 0
  output = capsys.readouterr().out
  result = json.loads(output)["components"]["zsh"]
  assert result["private_hooks"]["selection"]["zshenv"] == "conflict"
  assert result["private_hooks"]["scope"] == "current_environment_preview"
  assert "private_hook_conflict" in result["optional_degradations"]
  assert "PRIVATE_HOOK_CANARY" not in output
  assert str(config / "termcfg/zshenv.local") not in output


@pytest.mark.parametrize("name", ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"])
@pytest.mark.parametrize("value", [None, "", "/synthetic/absolute", "relative-private-canary"])
def test_xdg_paths_preserve_values_and_reject_relative(isolated_environment, monkeypatch, name, value):
  import os
  from termcfg.config import xdg_path
  from termcfg.errors import TermcfgError
  if value is None:
    monkeypatch.delenv(name)
  else:
    monkeypatch.setenv(name, value)
  defaults = {"XDG_CONFIG_HOME": ".config", "XDG_DATA_HOME": ".local/share",
              "XDG_STATE_HOME": ".local/state", "XDG_CACHE_HOME": ".cache"}
  for _ in range(2):
    if value == "relative-private-canary":
      with pytest.raises(TermcfgError) as caught:
        xdg_path(name)
      assert caught.value.code == 2
      assert caught.value.reason == "invalid_" + name.lower()
      assert value not in str(caught.value)
    else:
      assert xdg_path(name) == (Path(value) if value else isolated_environment.home / defaults[name])
    assert os.environ.get(name) == value


@pytest.mark.parametrize("name", ["XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"])
def test_doctor_reports_invalid_xdg_without_value(isolated_environment, fake_terminal_commands, monkeypatch, capsys, name):
  assert main(["init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  monkeypatch.setenv(name, "relative-private-canary")
  assert main(["doctor", "--component", "zsh", "--json"]) == 0
  output = capsys.readouterr().out
  component = json.loads(output)["components"]["zsh"]
  assert component["xdg_paths"][name] == "invalid_relative"
  assert "invalid_" + name.lower() in component["required_blockers"]
  assert component["ready"] is False
  assert "relative-private-canary" not in output


def test_doctor_rejects_relative_config_before_machine_selection(monkeypatch, capsys):
  monkeypatch.setenv("XDG_CONFIG_HOME", "relative-private-config-canary")
  assert main(["doctor", "--component", "zsh", "--json"]) == 2
  output = capsys.readouterr().out
  assert json.loads(output)["reason"] == "invalid_xdg_config_home"
  assert "relative-private-config-canary" not in output


@pytest.mark.parametrize("name", ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"])
@pytest.mark.parametrize("home", [None, "", "relative-private-home"])
@pytest.mark.parametrize("xdg", [None, "", "/synthetic/absolute"])
def test_xdg_fallback_requires_absolute_home(monkeypatch, home, xdg, name):
  from termcfg.config import xdg_path
  from termcfg.errors import TermcfgError
  if home is None:
    monkeypatch.delenv("HOME")
  else:
    monkeypatch.setenv("HOME", home)
  if xdg is None:
    monkeypatch.delenv(name)
  else:
    monkeypatch.setenv(name, xdg)
  monkeypatch.setattr(Path, "home", lambda: pytest.fail("must not discover passwd HOME"))
  if xdg:
    assert xdg_path(name) == Path(xdg)
  else:
    with pytest.raises(TermcfgError) as caught:
      xdg_path(name)
    assert (caught.value.code, caught.value.reason) == (2, "invalid_home")


@pytest.mark.parametrize("config", [None, "", "relative-config", "absolute-present", "absolute-absent"])
def test_private_hook_invalid_home_never_checks_relative_legacy(tmp_path, monkeypatch, config):
  selected = tmp_path / "config/termcfg/zshenv.local"
  selected.parent.mkdir(parents=True)
  selected.write_text("synthetic hook body\n")
  real_is_file = Path.is_file
  def absolute_only(path):
    assert path.is_absolute(), "must not inspect relative hook metadata"
    return real_is_file(path)
  monkeypatch.setattr(Path, "is_file", absolute_only)
  raw_config = str(tmp_path / ("config" if config == "absolute-present" else "absent")) if config and config.startswith("absolute-") else config
  result = private_hook_status(Path("relative-home"), raw_config)
  expected = "xdg" if config == "absolute-present" else "invalid_config_home" if config == "relative-config" else "invalid_home"
  assert result["zshenv"] == expected
  assert result["zshrc"] == ("invalid_config_home" if config == "relative-config" else "invalid_home")


@pytest.fixture
def terminal_smoke_module():
  import importlib.util
  script = Path(__file__).resolve().parents[1] / "scripts/smoke-termcfg-environment.py"
  spec = importlib.util.spec_from_file_location("termcfg_environment_smoke", script)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_terminal_smoke_requires_explicit_opt_in(terminal_smoke_module, tmp_path, capsys):
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as caught:
    terminal_smoke_module.main(["--evidence", str(evidence)])
  assert caught.value.code == 2
  assert "--allow-terminal is required" in capsys.readouterr().err
  assert not evidence.exists()


def test_terminal_smoke_redacts_failures_and_keeps_private_report(terminal_smoke_module, tmp_path, monkeypatch, capsys):
  import stat
  zsh = tmp_path / "synthetic-terminal"
  zsh.write_text("synthetic executable; never launched\n")
  zsh.chmod(0o700)
  def failure(*args):
    raise OSError("PRIVATE_TERMINAL_ERROR_CANARY")
  monkeypatch.setattr(terminal_smoke_module, "run_matrix", failure)
  evidence = tmp_path / "evidence"
  assert terminal_smoke_module.main(["--allow-terminal", "--zsh", str(zsh), "--evidence", str(evidence)]) == 1
  output = capsys.readouterr()
  report = (evidence / "result.json").read_text()
  assert json.loads(report)["reason"] == "terminal_check_failed"
  assert "PRIVATE_TERMINAL_ERROR_CANARY" not in output.out + output.err + report
  assert str(tmp_path) not in output.out + output.err + report
  assert stat.S_IMODE(evidence.stat().st_mode) == 0o700
  assert stat.S_IMODE((evidence / "result.json").stat().st_mode) == 0o600


def test_doctor_reports_invalid_home_fallback_without_value(isolated_environment, fake_terminal_commands, monkeypatch, capsys):
  assert main(["init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  monkeypatch.setenv("HOME", "relative-private-home-canary")
  monkeypatch.delenv("XDG_DATA_HOME")
  assert main(["doctor", "--component", "zsh", "--json"]) == 0
  output = capsys.readouterr().out
  component = json.loads(output)["components"]["zsh"]
  assert component["xdg_paths"]["XDG_DATA_HOME"] == "invalid_home"
  assert "invalid_home" in component["required_blockers"]
  assert "relative-private-home-canary" not in output


def test_terminal_plugin_smoke_rejects_download_attempt_even_when_shell_exits_zero(terminal_smoke_module, tmp_path, monkeypatch):
  import subprocess
  root = tmp_path / "plugin-case"
  def simulated_terminal(argv, **kwargs):
    (root / "network-attempts").write_bytes(b"synthetic attempted download\n")
    return subprocess.CompletedProcess(argv, 0, "2 2 2 2 2 2 false\n", "")
  monkeypatch.setattr(terminal_smoke_module.subprocess, "run", simulated_terminal)
  with pytest.raises(terminal_smoke_module.CheckFailure, match="plugin_download_attempted"):
    terminal_smoke_module.plugin_case(root, tmp_path / "synthetic-terminal")
