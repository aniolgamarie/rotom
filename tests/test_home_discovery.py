"""环境 HOME 发现只使用合成路径；账户目录查询和配置/凭据 I/O 均有哨兵。"""

from contextlib import contextmanager
import os
from pathlib import Path

import pytest

from agentcfg import cli, config, paths, secret_files
from agentcfg.schema import ConfigError
from termcfg import cli as terminal_cli
from termcfg.config import read_machine


BAD_HOMES = [None, "", "relative-private-home-canary"]


def set_home(monkeypatch, home):
  if home is None:
    monkeypatch.delenv("HOME")
  else:
    monkeypatch.setenv("HOME", home)


@pytest.fixture(autouse=True)
def forbid_account_home(monkeypatch):
  monkeypatch.setattr(Path, "home", lambda: pytest.fail("account HOME discovery forbidden"))


@pytest.mark.parametrize("home", BAD_HOMES)
def test_cli_explicit_home_prefix_rejects_before_configuration_reads(home, monkeypatch, capsys):
  set_home(monkeypatch, home)
  monkeypatch.setattr(config, "read_local_document", lambda *args: pytest.fail("configuration read before HOME validation"))
  monkeypatch.setattr(cli, "dispatch", lambda *args: pytest.fail("invalid HOME dispatched"))
  assert cli.main(["--local", "~/selected.toml", "validate"]) == 2
  output = capsys.readouterr()
  assert "relative-private-home-canary" not in output.out + output.err


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("xdg", [None, "", "relative-private-config-canary"])
def test_cli_default_rejects_invalid_root_before_reads(home, xdg, monkeypatch, capsys):
  set_home(monkeypatch, home)
  if xdg is None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
  else:
    monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
  monkeypatch.setattr(config, "read_local_document", lambda *args: pytest.fail("configuration read before root validation"))
  assert cli.main(["validate"]) == 2
  output = capsys.readouterr()
  assert "relative-private-config-canary" not in output.out + output.err
  assert "relative-private-home-canary" not in output.out + output.err


@pytest.mark.parametrize("home", BAD_HOMES)
def test_cli_absolute_config_root_uses_explicit_selection_without_home(home, monkeypatch, isolated_environment):
  expected = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"
  set_home(monkeypatch, home)
  seen = []
  monkeypatch.setattr(config, "read_local_document", lambda path: seen.append(path) or {})
  monkeypatch.setattr(cli, "dispatch", lambda args: 17)
  assert cli.main(["validate"]) == 17
  assert seen == [expected]


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("xdg", [None, "", "relative-private-config-canary"])
def test_default_secrets_reject_invalid_root_before_secret_reads(home, xdg, monkeypatch, tmp_path):
  set_home(monkeypatch, home)
  if xdg is None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
  else:
    monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
  monkeypatch.setattr(secret_files, "read_secrets_document", lambda *args: pytest.fail("secret read before root validation"))
  with pytest.raises(ConfigError) as caught:
    secret_files.load_secrets({"schema_version": 1, "machine": {"id": "fixture"}}, tmp_path / "machine.toml")
  assert (caught.value.code, caught.value.exit_code) == ("secrets-file-path", 2)
  assert "canary" not in str(caught.value)


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("explicit", [False, True])
def test_absolute_secret_selection_remains_available_without_home(home, explicit, monkeypatch, tmp_path):
  expected = tmp_path / "explicit-secrets.toml" if explicit else Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/secrets.toml"
  document = {"schema_version": 1, "machine": {"id": "fixture"}}
  if explicit:
    document["secrets_file"] = str(expected)
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-private-config-canary")
  set_home(monkeypatch, home)
  seen = []
  monkeypatch.setattr(secret_files, "read_secrets_document", lambda path: seen.append(path) or {"schema_version": 1, "shared": {}})
  secret_files.load_secrets(document, tmp_path / "machine.toml")
  assert seen == [expected]


@pytest.mark.parametrize("home", BAD_HOMES)
def test_new_terminal_selection_rejects_home_before_lease_or_io(home, monkeypatch, capsys):
  set_home(monkeypatch, home)
  monkeypatch.setattr(terminal_cli, "operation_lease", lambda *args: pytest.fail("lease entered before HOME validation"))
  monkeypatch.setattr(terminal_cli, "read_machine", lambda *args: pytest.fail("machine read before HOME validation"))
  monkeypatch.setattr(terminal_cli, "_write_new_machine", lambda *args: pytest.fail("machine write before HOME validation"))
  assert terminal_cli.main(["init-local", "--component", "zsh", "--json"]) == 2
  output = capsys.readouterr().out
  assert '"reason": "invalid_home"' in output
  assert "relative-private-home-canary" not in output


@pytest.mark.parametrize("home", BAD_HOMES)
def test_terminal_edit_uses_saved_target_and_state_without_home(home, monkeypatch):
  assert terminal_cli.main(["init-local", "--component", "zsh"]) == 0
  original = read_machine("default")
  set_home(monkeypatch, home)
  assert terminal_cli.main(["init-local", "--edit", "--component", "tmux"]) == 0
  updated = read_machine("default")
  assert updated.target_home == original.target_home
  assert updated.private_state_root == original.private_state_root
  assert updated.components == ("tmux",)


def test_cli_home_parent_tail_keeps_private_directory_check(monkeypatch, isolated_environment):
  # 这里只验证选择层的委派顺序；真实 no-follow/属主验证由 filesystem suite 提供。
  home = isolated_environment.home
  seen = []
  @contextmanager
  def checked_directory(path):
    seen.append(("directory", path))
    yield 123
  monkeypatch.setattr(paths, "_absolute_directory", checked_directory)
  monkeypatch.setattr(paths, "_check_private", lambda fd: seen.append(("private", fd)))
  assert cli.local_path("~/child/../target.toml") == home / "target.toml"
  assert seen == [("directory", home / "child/.."), ("private", 123)]
  with pytest.raises(paths.PathError):
    paths.configured_path("~/child/../target.toml")


def test_cli_home_parent_tail_does_not_normalize_past_failed_guard(monkeypatch):
  @contextmanager
  def unsafe(path):
    raise paths.PathError("synthetic unsafe directory")
    yield
  monkeypatch.setattr(paths, "_absolute_directory", unsafe)
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict, match="不得穿透符号链接"):
    cli.local_path("~/child/../target.toml")


@pytest.mark.parametrize("command", ["validate", "init-local"])
def test_cli_rejects_tilde_xdg_environment_without_expanding_home(command, monkeypatch):
  monkeypatch.setenv("XDG_CONFIG_HOME", "~/.config")
  monkeypatch.setattr(config, "read_local_document", lambda *args: pytest.fail("tilde XDG entered configuration read"))
  assert cli.main([command]) == 2


def test_default_shared_secret_rejects_tilde_xdg_environment(monkeypatch, tmp_path):
  monkeypatch.setenv("XDG_CONFIG_HOME", "~/.config")
  monkeypatch.setattr(secret_files, "read_secrets_document", lambda *args: pytest.fail("tilde XDG entered secret read"))
  with pytest.raises(ConfigError, match="secrets-file-path"):
    secret_files.load_secrets({"schema_version": 1, "machine": {"id": "fixture"}}, tmp_path / "machine.toml")


@pytest.mark.parametrize("home", BAD_HOMES)
def test_absolute_xdg_dollar_is_a_literal_without_interpolation(home, monkeypatch, tmp_path):
  from termcfg.config import xdg_path
  root = tmp_path / "$literal-config"
  monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
  set_home(monkeypatch, home)
  assert paths.xdg_config_home() == root
  assert xdg_path("XDG_CONFIG_HOME") == root
  assert secret_files.secrets_path({}, tmp_path / "machine.toml") == root / "agentcfg/secrets.toml"
  seen = []
  monkeypatch.setattr(config, "read_local_document", lambda path: seen.append(path) or {})
  monkeypatch.setattr(cli, "dispatch", lambda args: 17)
  assert cli.main(["validate"]) == 17
  assert seen == [root / "agentcfg/machines/default.toml"]
  assert os.environ["XDG_CONFIG_HOME"] == str(root)


def test_explicit_toml_secret_path_retains_home_prefix_semantics(isolated_environment, tmp_path):
  assert secret_files.secrets_path({"secrets_file": "~/selected-private.toml"}, tmp_path / "machine.toml") == isolated_environment.home / "selected-private.toml"


def test_terminal_xdg_rejects_tilde_environment(monkeypatch):
  from termcfg.config import xdg_path
  from termcfg.errors import TermcfgError
  monkeypatch.setenv("XDG_CONFIG_HOME", "~/.config")
  with pytest.raises(TermcfgError) as caught:
    xdg_path("XDG_CONFIG_HOME")
  assert (caught.value.code, caught.value.reason) == (2, "invalid_xdg_config_home")
