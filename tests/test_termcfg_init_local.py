"""初始化交互的隔离契约。"""

from pathlib import Path
import io

import pytest

from termcfg.cli import main
from termcfg.config import read_machine


def test_non_tty_requires_explicit_selection(isolated_environment):
  assert main(["init-local"]) == 2
  assert not (isolated_environment.home / "config/termcfg/machines/default.toml").exists()


def test_default_explicit_selection_and_clear(isolated_environment):
  assert main(["init-local", "--component", "zsh", "--component", "tmux"]) == 0
  assert read_machine("default").components == ("zsh", "tmux")
  assert main(["init-local", "--edit"]) == 2
  assert read_machine("default").components == ("zsh", "tmux")
  assert main(["init-local", "--edit", "--none"]) == 0
  assert read_machine("default").components == ()


def test_edit_preserves_machine_home(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  original = read_machine("default")
  assert main(["init-local", "--edit", "--component", "mihomo"]) == 0
  updated = read_machine("default")
  assert updated.components == ("mihomo",)
  assert updated.target_home == original.target_home
  assert updated.private_state_root == original.private_state_root


def test_interactive_init_uses_one_multiselect_and_confirmation(isolated_environment, monkeypatch):
  class TtyInput(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", TtyInput())
  answers = iter(("zsh,tmux", "yes"))
  monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
  assert main(["init-local"]) == 0
  assert read_machine("default").components == ("zsh", "tmux")


def test_json_flag_after_subcommand(isolated_environment, capsys):
  assert main(["components", "--json"]) == 0
  import json
  payload = json.loads(capsys.readouterr().out)
  assert payload["components"]["zsh"]


def test_interactive_json_keeps_prompts_off_stdout(isolated_environment, monkeypatch, capsys):
  class TtyInput(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", TtyInput())
  answers = iter(("zsh", "yes"))
  monkeypatch.setattr("builtins.input", lambda: next(answers))
  assert main(["init-local", "--json"]) == 0
  import json
  output = capsys.readouterr()
  assert json.loads(output.out)["components"] == ["zsh"]
  assert "组件>" in output.err


def test_first_interactive_defaults_only_available_terminal_programs(isolated_environment,
                                                                      fake_terminal_commands, monkeypatch):
  class TtyInput(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", TtyInput())
  answers = iter(("", "yes"))
  monkeypatch.setattr("builtins.input", lambda: next(answers))
  assert main(["init-local"]) == 0
  assert read_machine("default").components == ("zsh", "tmux")
