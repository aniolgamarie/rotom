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
