"""CLI-01/CLI-08：只验证参数和选择元数据，不执行宿主或读取用户配置。"""

import os
from pathlib import Path
import pytest

from agentcfg import cli, commands


CANARY = "private-canary-$(touch forbidden)-`false`"
COMMANDS = [
  ["validate"], ["render"], ["plan"], ["sync"], ["apply"],
  ["doctor"], ["doctor", "--live"], ["capture"], ["rollback"],
  ["lock", "--agent", "dsh"], ["run", "dsh"],
  ["project", "init", "openspec", "--path", "业务 项目"],
]


@pytest.fixture
def isolated_cli(isolated_environment):
  return isolated_environment.home


def machine_file(name="default"):
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines" / f"{name}.toml"


def write_local(path=None, metadata='id = "fixture"\n'):
  path = path or machine_file()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    "schema_version = 1\n[machine]\n" + metadata
    + f'\n[secrets]\nkey = "{CANARY}"\n', encoding="utf-8",
  )
  return path


def snapshot(root):
  return {
    path.relative_to(root): (path.stat().st_mode, path.stat().st_mtime_ns,
                            path.read_bytes() if path.is_file() else None)
    for path in root.rglob("*")
  }


def observe(argv, monkeypatch, tmp_path, capsys):
  seen = []
  monkeypatch.setattr(cli, "dispatch", lambda args: seen.append(args) or 17)
  before = snapshot(tmp_path)
  assert cli.main(argv) == 17
  assert snapshot(tmp_path) == before
  assert len(seen) == 1
  assert CANARY not in repr(vars(seen[0]))
  output = capsys.readouterr()
  assert CANARY not in output.out + output.err
  return seen[0]


@pytest.mark.parametrize("command", COMMANDS)
def test_cli_commands_resolve_same_default(command, monkeypatch, tmp_path, capsys):
  path = write_local(metadata='id = "fixture"\ndefault_profile = "local-profile"\n')
  args = observe(command, monkeypatch, tmp_path, capsys)
  assert args.machine == "default"
  assert args.local == path
  assert args.profile == "local-profile"


@pytest.mark.parametrize("command", COMMANDS)
def test_cli_explicit_machine_profile(command, monkeypatch, tmp_path, capsys):
  path = write_local(machine_file("work"), 'default_profile = "local-profile"\n')
  args = observe(["--machine", "work", "--profile", "explicit", *command],
                 monkeypatch, tmp_path, capsys)
  assert args.machine == "work"
  assert args.local == path
  assert args.profile == "explicit"


def test_cli_profile_fallback(monkeypatch, tmp_path, capsys):
  write_local()
  args = observe(["plan"], monkeypatch, tmp_path, capsys)
  assert args.profile == "dsh-default"


@pytest.mark.parametrize("xdg", [None, ""])
def test_cli_xdg_fallback(xdg, isolated_cli, monkeypatch, tmp_path, capsys):
  if xdg is None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
  else:
    monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
  path = write_local(isolated_cli / ".config/agentcfg/machines/default.toml")
  args = observe(["validate"], monkeypatch, tmp_path, capsys)
  assert args.local == path


@pytest.mark.parametrize("local", ["absolute", "relative", "home", "literal"])
def test_cli_local_path_uses_caller_context(local, isolated_cli, monkeypatch, tmp_path, capsys):
  if local == "absolute":
    path = isolated_cli / "私有 空格.toml"
    value = str(path)
  elif local == "relative":
    path = tmp_path / "私有 空格.toml"
    value = "../私有 空格.toml"
  elif local == "home":
    path = isolated_cli / "私有 空格.toml"
    value = "~/私有 空格.toml"
  else:
    path = Path.cwd() / "$NOT_EXPANDED.toml"
    value = "$NOT_EXPANDED.toml"
  write_local(path)
  args = observe(["--local", value, "plan"], monkeypatch, tmp_path, capsys)
  assert args.local == path
  assert args.machine is None
  assert args.profile == "dsh-default"


@pytest.mark.parametrize("value, selection", [
  ("./~/selected.toml", "relative-tilde"),
  ("./~name/selected.toml", "relative-name"),
  ("~/selected.toml", "home"),
])
def test_cli_local_tilde_prefix_is_literal(value, selection, isolated_cli, monkeypatch, tmp_path, capsys):
  paths = {
    "relative-tilde": Path.cwd() / "~/selected.toml",
    "relative-name": Path.cwd() / "~name/selected.toml",
    "home": isolated_cli / "selected.toml",
  }
  for profile, path in paths.items():
    write_local(path, f'default_profile = "{profile}"\n')
  args = observe(["--local", value, "plan"], monkeypatch, tmp_path, capsys)
  assert args.local == paths[selection]
  assert args.profile == selection
  assert args.machine is None


def test_cli_local_profile_precedence(monkeypatch, tmp_path, capsys):
  path = write_local(tmp_path / "selected.toml", 'default_profile = "local-profile"\n')
  args = observe(["--local", str(path), "--profile", "explicit", "validate"],
                 monkeypatch, tmp_path, capsys)
  assert args.local == path
  assert args.profile == "explicit"


@pytest.mark.parametrize("argv, hint", [
  (["--machine", "missing", "validate"], "init-local --machine NAME"),
  (["--local", "missing.toml", "validate"], "--local PATH"),
])
def test_cli_missing_selected_file_is_actionable(argv, hint, capsys):
  assert cli.main(argv) == 2
  assert hint in capsys.readouterr().err


def test_cli_read_failure_is_redacted(monkeypatch, capsys):
  write_local()
  def denied(*args, **kwargs):
    raise PermissionError(CANARY)
  monkeypatch.setattr("agentcfg.paths.read_private_file", denied)
  assert cli.main(["validate"]) == 4
  output = capsys.readouterr()
  assert "访问权限" in output.err
  assert CANARY not in output.out + output.err


def test_cli_missing_default_never_scans(monkeypatch, tmp_path, capsys):
  write_local(machine_file("other"))
  monkeypatch.setattr(cli, "dispatch", lambda args: pytest.fail("must not dispatch"))
  before = snapshot(tmp_path)
  assert cli.main(["validate"]) == 2
  assert snapshot(tmp_path) == before
  assert "init-local --machine default" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
  ["--machine", "one", "--local", "private", "validate"],
  ["--machine", "one", "--machine=one", "validate"],
  ["--local", "one", "--local=two", "validate"],
  ["--profile", "one", "--profile=one", "validate"],
  ["--machine", "one", "init-local", "--machine", "one"],
  ["--local", "one", "init-local", "--machine", "two"],
  ["--profile", "one", "init-local", "--machine", "two"],
  ["init-local", "--machine", "one", "--machine=two"],
  ["init-local"], ["--machine", "one", "init-local"],
  ["validate", "--machine", "one"], ["--mach", "one", "validate"],
  ["project"], ["project", "init", "openspec"],
  ["run", "dsh", "--unknown"], ["run", "dsh", "native-without-separator"],
])
def test_cli_invalid_syntax_before_read(argv, monkeypatch, capsys):
  monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not read"))
  with pytest.raises(SystemExit) as error:
    cli.main(argv)
  assert error.value.code == 2
  assert capsys.readouterr().err


@pytest.mark.parametrize("option", ["--machine", "--profile"])
@pytest.mark.parametrize("value", ["", ".", "..", "../escape", "/absolute", "a/b", "a\\b", "a\nline"])
def test_cli_selector_ids_cannot_escape(option, value, capsys):
  with pytest.raises(SystemExit) as error:
    cli.main([option, value, "validate"])
  assert error.value.code == 2


@pytest.mark.parametrize("argv", [["lock", "--agent", "codex"], ["run", "unsupported"]])
def test_cli_unsupported_tools_are_actionable(argv, capsys):
  with pytest.raises(SystemExit) as error:
    cli.main(argv)
  assert error.value.code == 2
  assert "dsh" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["--help"], ["run", "--help"], ["init-local", "--help"]])
def test_cli_help_needs_no_local(argv, monkeypatch, capsys):
  monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not read"))
  if not argv:
    assert cli.main(argv) == 2
  else:
    with pytest.raises(SystemExit) as error:
      cli.main(argv)
    assert error.value.code == 0
  assert "usage:" in capsys.readouterr().out


def test_cli_init_local_never_reads_credentials(monkeypatch, capsys, tmp_path):
  path = write_local(machine_file("work"))
  before = snapshot(tmp_path)
  with monkeypatch.context() as patch:
    patch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not read"))
    assert cli.main(["init-local", "--machine", "work"]) == 4
  assert snapshot(tmp_path) == before
  assert path.exists()
  assert "初始化冲突" in capsys.readouterr().err


@pytest.mark.parametrize("cwd", [None, "相对 工作", "/虚构 绝对目录"])
def test_cli_run_remainder_is_literal(cwd, monkeypatch, tmp_path, capsys):
  write_local()
  native = ["--leading", "--cwd", "not-manager-cwd", "--machine", "not-selector",
            "", "中文 空格", 'quote"value', "a;b", "$(touch forbidden)",
            "`touch forbidden`", "line\nbreak", "--", "--help"]
  argv = ["run", "dsh"] + (["--cwd", cwd] if cwd is not None else [])
  args = observe([*argv, "--", *native], monkeypatch, tmp_path, capsys)
  assert args.passthrough == native
  assert args.cwd == (Path(cwd) if cwd is not None else Path.cwd())


@pytest.mark.parametrize("body", [
  f'"{CANARY}" = [', f'["{CANARY}"]\na=1\na=2',
  'machine = "wrong-type"', '[machine]\ndefault_profile = false',
  '[machine]\ndefault_profile = ""', '[machine]\ndefault_profile = "../escape"',
])
def test_cli_invalid_local_is_redacted(body, monkeypatch, capsys):
  path = write_local()
  path.write_text(body, encoding="utf-8")
  monkeypatch.setattr(cli, "dispatch", lambda args: pytest.fail("must not dispatch"))
  assert cli.main(["validate"]) == 2
  output = capsys.readouterr()
  assert CANARY not in output.out + output.err
  assert "TOML" in output.err or "machine" in output.err


def test_cli_invalid_utf8_is_redacted(capsys):
  path = write_local()
  path.write_bytes(CANARY.encode() + b"\xff")
  assert cli.main(["validate"]) == 2
  assert CANARY not in capsys.readouterr().err


@pytest.mark.parametrize("error", [PermissionError(CANARY), RuntimeError(CANARY)])
def test_cli_failures_do_not_echo_exception(error, monkeypatch, capsys):
  write_local()
  def fail(*args, **kwargs):
    raise error
  monkeypatch.setattr(commands, "cmd_validate", fail)
  assert cli.main(["validate"]) == 6
  assert CANARY not in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--unknown", CANARY], ["run", CANARY], ["lock", "--agent", CANARY]])
def test_cli_parser_errors_do_not_echo_private_arguments(argv, capsys):
  with pytest.raises(SystemExit) as error:
    cli.main(argv)
  assert error.value.code == 2
  assert CANARY not in capsys.readouterr().err


@pytest.mark.parametrize("command", COMMANDS)
def test_cli_invalid_configuration_fails_before_side_effects(command, tmp_path, capsys):
  write_local(metadata='id = "fixture"\ndefault_profile = "missing-profile"\n')
  before = snapshot(tmp_path)
  assert cli.main(command) == 2
  assert snapshot(tmp_path) == before
  assert "校验" in capsys.readouterr().err
