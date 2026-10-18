"""严格环境发现与首批交互的交叉契约；临时机器、离线且不启动宿主。"""

import builtins
from copy import deepcopy
import json
import os
from pathlib import Path
import shlex

import pytest

from agentcfg import cli as agent_cli, paths
from termcfg import cli as terminal_cli, environment
from termcfg.config import read_machine
from termcfg.diagnostics import emit
from termcfg.presentation import render_result


MACHINE = "workstation"
CANARY = "synthetic-private-environment-canary"
BAD_HOMES = [None, "", "relative-" + CANARY]
XDG_NAMES = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")


def forbidden(*args, **kwargs):
  pytest.fail("unexpected discovery, private I/O or interaction")


@pytest.fixture(autouse=True)
def no_account_home(monkeypatch):
  monkeypatch.setattr(Path, "home", forbidden)


def set_home(monkeypatch, value):
  if value is None:
    monkeypatch.delenv("HOME")
  else:
    monkeypatch.setenv("HOME", value)


def initialize(capsys):
  assert terminal_cli.main(["--machine", MACHINE, "init-local", "--component", "zsh", "--json"]) == 0
  capsys.readouterr()
  return read_machine(MACHINE)


def environment_guidance(text, name):
  assert "环境 " + name + " 无效" in text
  assert "字面绝对路径" in text
  assert "未提供进一步解释" not in text
  assert text.index("前置：先修正") < text.index("下一步")
  assert "--home 仅改变诊断目标，不能修复环境发现" in text


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("tool", [agent_cli, terminal_cli], ids=["agentcfg", "termcfg"])
@pytest.mark.parametrize("argv", [[], ["--help"], ["init-local", "--help"], ["doctor", "--help"]])
def test_invalid_home_does_not_turn_static_help_into_discovery(home, tool, argv, monkeypatch, capsys):
  set_home(monkeypatch, home)
  for name in XDG_NAMES:
    monkeypatch.setenv(name, "relative-" + CANARY)
  before = dict(os.environ)
  with monkeypatch.context() as guarded:
    for name in ("stat", "lstat", "open", "read_text", "read_bytes"):
      guarded.setattr(Path, name, forbidden)
    guarded.setattr(builtins, "open", forbidden)
    guarded.setattr(builtins, "input", forbidden)
    guarded.setattr(agent_cli, "resolve_selection", forbidden)
    guarded.setattr(agent_cli, "dispatch", forbidden)
    for name in ("read_machine", "load_catalog", "operation_lease"):
      guarded.setattr(terminal_cli, name, forbidden)
    if argv:
      with pytest.raises(SystemExit) as caught:
        tool.main(argv)
      assert caught.value.code == 0
    else:
      assert tool.main(argv) == 2
  output = capsys.readouterr()
  assert output.out
  assert CANARY not in output.out + output.err
  assert os.environ == before


@pytest.mark.parametrize("home", [*BAD_HOMES, "/synthetic/../" + CANARY,
                                 "/synthetic\\" + CANARY, "/synthetic/\x1b" + CANARY])
@pytest.mark.parametrize("json_mode", [False, True])
def test_new_terminal_init_rejects_home_before_lease_and_input(home, json_mode, isolated_environment,
                                                              sentinel_factory, monkeypatch, capsys):
  set_home(monkeypatch, home)
  before = sentinel_factory(isolated_environment.root)
  env_before = dict(os.environ)
  monkeypatch.setattr(terminal_cli.sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(builtins, "input", forbidden)
  for name in ("machine_path", "operation_lease", "read_machine", "_write_new_machine"):
    monkeypatch.setattr(terminal_cli, name, forbidden)
  assert terminal_cli.main(["--machine", MACHINE, "init-local", *(["--json"] if json_mode else [])]) == 2
  output = capsys.readouterr()
  assert CANARY not in output.out + output.err
  if json_mode:
    assert json.loads(output.out) == {
      "command": "init-local", "machine_id": MACHINE, "overall_ready": False, "ready": False,
      "reason": "invalid_home", "next_command": "./termcfg --machine workstation doctor",
    }
  else:
    environment_guidance(output.out, "HOME")
  before.assert_unchanged()
  assert os.environ == env_before


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("json_mode", [False, True])
def test_interactive_edit_keeps_saved_target_with_explicit_xdg_and_bad_home(home, json_mode,
                                                                          isolated_environment,
                                                                          monkeypatch, capsys,
                                                                          sentinel_factory):
  original = initialize(capsys)
  state_before = sentinel_factory(original.private_state_root)
  lease_root = isolated_environment.root / "alternate-state"
  lease_root.mkdir(mode=0o700)
  monkeypatch.setenv("XDG_STATE_HOME", str(lease_root))
  target = original.target_home / ".zshrc"
  target.write_text("synthetic untouched target\n")
  target_before = sentinel_factory(target)
  set_home(monkeypatch, home)
  env_before = dict(os.environ)
  answers = []
  def confirm():
    answers.append("yes")
    return "yes"
  monkeypatch.setattr(terminal_cli.sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(builtins, "input", confirm)
  assert terminal_cli.main(["--machine", MACHINE, "init-local", "--edit", "--component", "tmux",
                            *(["--json"] if json_mode else [])]) == 0
  output = capsys.readouterr()
  updated = read_machine(MACHINE)
  assert updated.target_home == original.target_home
  assert updated.private_state_root == original.private_state_root
  assert updated.components == ("tmux",)
  assert (lease_root / "termcfg/leases/machines/workstation.lock").is_file()
  assert answers == ["yes"]
  assert "保存私人机器选择" in output.err
  assert CANARY not in output.out + output.err
  if json_mode:
    result = json.loads(output.out)
    assert result["ready"] is True
    assert result["next_command"] == "./termcfg --machine workstation doctor --component tmux"
  else:
    assert "选择已保存" in output.out
    assert "先修正" not in output.out
  state_before.assert_unchanged()
  target_before.assert_unchanged()
  assert os.environ == env_before


@pytest.mark.parametrize("home", BAD_HOMES)
@pytest.mark.parametrize("command", ["doctor", "status", "plan"])
def test_saved_and_diagnostic_targets_do_not_replace_environment_home(home, command,
                                                                     isolated_environment,
                                                                     fake_terminal_commands,
                                                                     sentinel_factory,
                                                                     monkeypatch, capsys):
  original = initialize(capsys)
  alternate = isolated_environment.root / "中文 diagnostic target"
  alternate.mkdir(mode=0o700)
  current_state = isolated_environment.root / "current-state-environment"
  current_state.mkdir(mode=0o700)
  monkeypatch.setenv("XDG_STATE_HOME", str(current_state))
  set_home(monkeypatch, home)
  before = sentinel_factory(isolated_environment.root)
  env_before = dict(os.environ)
  seen = []
  inspect = environment.inspect_environment
  def observe(machine, components):
    seen.append(machine)
    return inspect(machine, components)
  monkeypatch.setattr(environment, "inspect_environment", observe)
  monkeypatch.setattr(terminal_cli, "inspect_environment", observe)
  for target in (None, alternate):
    seen.clear()
    args = ["--machine", MACHINE, command, "--json"]
    if target is not None:
      args.extend(("--home", str(target)))
    assert terminal_cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    values = result.get("environment", result.get("components"))
    assert "invalid_home" not in values["zsh"]["required_blockers"]
    assert all(value == "absolute" for value in values["zsh"]["xdg_paths"].values())
    assert seen and {machine.target_home for machine in seen} == {target or original.target_home}
    assert all(machine.private_state_root == original.private_state_root for machine in seen)
    assert read_machine(MACHINE) == original
    assert os.environ == env_before
    before.assert_unchanged()


@pytest.mark.parametrize("control", ["\t", "\n", "\r", "\x1b", "\x7f", "\u202e"])
@pytest.mark.parametrize("command", ["doctor", "status", "plan"])
def test_control_character_home_does_not_change_copyable_human_guidance(
    control, command, isolated_environment, sentinel_factory, monkeypatch, capsys):
  original = initialize(capsys)
  alternate = isolated_environment.root / ("diagnostic-A" + control + "B")
  alternate.mkdir(mode=0o700)
  monkeypatch.setattr(environment.shutil, "which", lambda name: None)
  before = sentinel_factory(isolated_environment.root)
  args = ["--machine", MACHINE, command, "--home", str(alternate)]
  assert terminal_cli.main([*args, "--json"]) == 0
  payload = json.loads(capsys.readouterr().out)
  values = payload.get("environment", payload.get("components"))
  suggestion = shlex.split(values["zsh"]["next_command"])
  assert suggestion[suggestion.index("--home") + 1] == str(alternate)
  assert terminal_cli.main(args) == 0
  text = capsys.readouterr().out
  assert "不能原样复制" in text
  commands = [shlex.split(line.strip()) for line in text.splitlines() if line.startswith("  ./termcfg")]
  assert commands
  for words in commands:
    assert "--home" not in words
    if "--help" in words:
      assert words == ["./termcfg", command, "--help"]
  assert read_machine(MACHINE) == original
  before.assert_unchanged()


@pytest.mark.parametrize("json_mode", [False, True])
def test_diagnostic_home_does_not_repair_invalid_config_discovery(json_mode, isolated_environment,
                                                                monkeypatch, sentinel_factory, capsys):
  initialize(capsys)
  alternate = isolated_environment.root / "diagnostic-target"
  alternate.mkdir(mode=0o700)
  before = sentinel_factory(isolated_environment.root)
  set_home(monkeypatch, "relative-" + CANARY)
  monkeypatch.setenv("XDG_CONFIG_HOME", "relative-config-" + CANARY)
  monkeypatch.setattr(terminal_cli, "_diagnostic_home", forbidden)
  env_before = dict(os.environ)
  assert terminal_cli.main(["--machine", MACHINE, "doctor", "--home", str(alternate),
                            *(["--json"] if json_mode else [])]) == 2
  output = capsys.readouterr()
  assert CANARY not in output.out + output.err
  if json_mode:
    assert json.loads(output.out) == {
      "command": "doctor", "machine_id": MACHINE, "overall_ready": False, "ready": False,
      "reason": "invalid_xdg_config_home", "next_command": "./termcfg doctor --help",
    }
  else:
    environment_guidance(output.out, "XDG_CONFIG_HOME")
  before.assert_unchanged()
  assert os.environ == env_before


@pytest.mark.parametrize("name, home_fallback", [(name, fallback)
  for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME") for fallback in (False, True)])
@pytest.mark.parametrize("command", ["doctor", "status", "plan"])
def test_nested_environment_blockers_precede_guidance_without_changing_exit_contract(
    name, home_fallback, command, isolated_environment, fake_terminal_commands,
    sentinel_factory, monkeypatch, capsys):
  original = initialize(capsys)
  alternate = isolated_environment.root / "diagnostic-target"
  alternate.mkdir(mode=0o700)
  args = ["--machine", MACHINE, command, "--home", str(alternate)]
  assert terminal_cli.main([*args, "--json"]) == 0
  baseline = json.loads(capsys.readouterr().out)
  if home_fallback:
    monkeypatch.delenv(name)
    set_home(monkeypatch, "relative-" + CANARY)
  else:
    monkeypatch.setenv(name, "relative-" + CANARY)
  reason = "invalid_home" if home_fallback else "invalid_" + name.lower()
  before = sentinel_factory(isolated_environment.root)
  env_before = dict(os.environ)
  for strict in ([False, True] if command == "doctor" else [False]):
    words = [*args, *(["--strict"] if strict else [])]
    expected_code = 5 if strict else 0
    assert terminal_cli.main([*words, "--json"]) == expected_code
    output = capsys.readouterr()
    assert CANARY not in output.out + output.err
    result = json.loads(output.out)
    assert result.keys() == baseline.keys()
    assert result["ready"] is result["overall_ready"] is False
    field = "environment" if command == "plan" else "components"
    component = result[field]["zsh"]
    assert component.keys() == baseline[field]["zsh"].keys()
    assert component["ready"] is False and component["status"] == "blocked"
    assert reason in component["required_blockers"]
    assert component["xdg_paths"][name] == ("invalid_home" if home_fallback else "invalid_relative")
    assert terminal_cli.main(words) == expected_code
    output = capsys.readouterr()
    environment_guidance(output.out, "HOME" if home_fallback else name)
    assert CANARY not in output.out + output.err
  assert read_machine(MACHINE) == original
  before.assert_unchanged()
  assert os.environ == env_before


@pytest.mark.parametrize("reason", ["invalid_home", *("invalid_" + name.lower() for name in XDG_NAMES)])
def test_environment_explanation_is_a_pure_human_projection(reason, capsys):
  payload = {"command": "doctor", "ready": False, "overall_ready": False,
             "reason": reason, "next_command": "./termcfg --machine workstation doctor"}
  before = deepcopy(payload)
  text = render_result(payload)
  environment_guidance(text, "HOME" if reason == "invalid_home" else reason.removeprefix("invalid_").upper())
  assert payload == before
  emit(payload, json_mode=True)
  output = capsys.readouterr()
  assert json.loads(output.out) == before
  assert len(output.out.splitlines()) == 1 and not output.err
  suggestion = shlex.split(before["next_command"])
  assert "--home" not in suggestion


@pytest.mark.parametrize("argv", [
  ["validate", "--format", "human"], ["validate", "--format", "json"],
  ["--local", "../" + CANARY + ".toml", "validate", "--format", "human"],
  ["--local", "../" + CANARY + ".toml", "validate", "--format", "json"],
  ["init-local"],
])
@pytest.mark.parametrize("tty", [False, True])
def test_synthetic_root_owner_error_keeps_marker_exit_and_redaction(argv, tty, monkeypatch,
                                                                   isolated_environment,
                                                                   sentinel_factory, capsys):
  # 仅验证异常传播/展示；合成抛错不能证明真实根祖先上的私人路径正向基线可用。
  calls = []
  def unsupported(fd, **kwargs):
    calls.append(kwargs)
    raise paths.UnsupportedRootOwner()
  monkeypatch.setattr(paths, "_check_ancestor", unsupported)
  monkeypatch.setattr(agent_cli.sys.stdout, "isatty", lambda: tty)
  before = sentinel_factory(isolated_environment.root)
  assert agent_cli.main(argv) == 4
  output = capsys.readouterr()
  assert calls == [{"root": True}]
  assert "unsupported-root-owner" in output.err
  assert CANARY not in output.out + output.err
  assert not output.out
  before.assert_unchanged()
