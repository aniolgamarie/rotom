"""静态导航、局部参数帮助及真实临时 HOME 上的建议范围。"""

import builtins
import json
from pathlib import Path
import shlex

import pytest

from termcfg import cli
from termcfg.cli_help import COMMANDS
from termcfg.config import read_machine
from termcfg.guidance import hint


def payload(capsys):
  return json.loads(capsys.readouterr().out)


def parse_hint(value):
  words = shlex.split(value)
  assert words.pop(0) == "./termcfg"
  return cli.build_parser().parse_args(words)


@pytest.fixture
def no_state(monkeypatch):
  def forbidden(*args, **kwargs):
    pytest.fail("help/parser must not inspect configuration, files or launch anything")
  with monkeypatch.context() as guarded:
    for name in ("read_machine", "load_catalog", "cmd_init", "build_preview"):
      guarded.setattr(cli, name, forbidden)
    guarded.setattr(Path, "stat", forbidden)
    guarded.setattr(Path, "open", forbidden)
    guarded.setattr(builtins, "open", forbidden)
    guarded.setattr(builtins, "input", forbidden)
    yield


def test_bare_navigation_keeps_failure_stdout_and_static_stderr(no_state, capsys):
  assert cli.main([]) == 2
  output = capsys.readouterr()
  assert output.out
  assert "首次配置" in output.err
  assert "不会自动执行" in output.err
  assert "--machine workstation" in output.err


@pytest.mark.parametrize("command", [None, *COMMANDS])
def test_all_help_is_static_and_descriptive(no_state, capsys, command):
  args = [command, "--help"] if command else ["--help"]
  with pytest.raises(SystemExit) as error:
    cli.main(args)
  assert error.value.code == 0
  output = capsys.readouterr()
  assert not output.err
  assert "示例" in output.out
  assert "--json" in output.out
  assert "--machine" in output.out
  if command:
    assert COMMANDS[command][0] in output.out


@pytest.mark.parametrize("args, local_help, required", [
  (["sync"], "sync", "--component"),
  (["lock", "--component", "zsh"], "lock", "--version"),
  (["migrate"], "migrate", "--drop-mihomo"),
  (["sync", "--component", "PRIVATE-CANARY"], "sync", "zsh"),
  (["sync", "--component", "zsh", "--timeout", "PRIVATE-CANARY"], "sync", "--timeout"),
  (["doctor", "--PRIVATE-CANARY"], "doctor", "参数"),
])
def test_argument_errors_are_local_redacted_and_single_json(no_state, capsys, args, local_help, required):
  assert cli.main([*args, "--json"]) == 2
  output = capsys.readouterr()
  result = json.loads(output.out)
  assert result == {"overall_ready": False, "ready": False, "reason": "invalid_arguments",
                    "next_command": f"./termcfg {local_help} --help"}
  assert required in output.err
  assert "PRIVATE-CANARY" not in output.out + output.err


def test_unknown_command_and_missing_command_have_top_level_json_help(no_state, capsys):
  for args in (["PRIVATE-CANARY", "--json"], ["--json"]):
    assert cli.main(args) == 2
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["next_command"] == "./termcfg --help"
    assert "PRIVATE-CANARY" not in output.out + output.err


def test_json_does_not_swallow_explicit_help(no_state, capsys):
  with pytest.raises(SystemExit) as error:
    cli.main(["--json", "doctor", "--help"])
  assert error.value.code == 0
  assert "--strict" in capsys.readouterr().out


def test_existing_selector_positions_and_duplicate_semantics_are_unchanged():
  parser = cli.build_parser()
  args = parser.parse_args(["--machine", "first", "--json", "status", "--machine", "last"])
  assert args.machine == "last"
  assert args.json is True
  assert parser.parse_args(["status", "--machine", "last", "--json"]).json is True


def test_all_static_examples_parse_without_dispatch():
  from termcfg.cli_help import ENTRY_GUIDE, ROOT_HELP
  examples = [ENTRY_GUIDE, ROOT_HELP, *(value[1] for value in COMMANDS.values())]
  count = 0
  for document in examples:
    for line in document.splitlines():
      if "./termcfg " not in line:
        continue
      # 只消费静态文档中的示例行；导航正文的占位说明不是可执行命令。
      if not line.strip().startswith("./termcfg") and not line.startswith("示例："):
        continue
      command = line[line.index("./termcfg "):]
      try:
        parse_hint(command)
      except SystemExit as error:
        assert error.code == 0
      count += 1
  assert count >= 15


def test_named_machine_hints_include_saved_multiple_components(isolated_environment, fake_terminal_commands, capsys):
  assert cli.main(["--machine", "workstation", "init-local", "--component", "zsh", "--component", "tmux", "--json"]) == 0
  initialized = payload(capsys)
  assert parse_hint(initialized["next_command"]).machine == "workstation"
  for command in ("doctor", "status", "plan"):
    assert cli.main(["--machine", "workstation", command, "--json"]) == 0
    result = payload(capsys)
    next_args = parse_hint(result["next_command"])
    assert next_args.machine == "workstation"
    assert set(next_args.component) == {"zsh", "tmux"}
    environment = result.get("environment", result.get("components", {}))
    for component, item in environment.items():
      if "next_command" in item:
        child = parse_hint(item["next_command"])
        assert child.machine == "workstation"
        assert child.component == (component if child.command == "sync" else [component])


def test_missing_named_machine_keeps_requested_component(isolated_environment, capsys):
  assert cli.main(["--machine", "workstation", "doctor", "--component", "tmux", "--json"]) == 2
  result = payload(capsys)
  next_args = parse_hint(result["next_command"])
  assert next_args.command == "init-local"
  assert next_args.machine == "workstation"
  assert next_args.component == ["tmux"]


def test_invalid_machine_value_is_not_exposed(isolated_environment, capsys):
  assert cli.main(["--machine", "/PRIVATE-CANARY", "status", "--json"]) == 2
  output = capsys.readouterr()
  assert "PRIVATE-CANARY" not in output.out + output.err
  assert json.loads(output.out)["next_command"] == "./termcfg --help"


def test_diagnostic_home_plan_requires_fresh_saved_target_preview(isolated_environment, fake_terminal_commands, capsys):
  assert cli.main(["--machine", "workstation", "init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  other = isolated_environment.root / "中文 diagnostic $(literal)"
  other.mkdir(mode=0o700)
  assert cli.main(["--machine", "workstation", "plan", "--home", str(other), "--json"]) == 0
  result = payload(capsys)
  next_args = parse_hint(result["next_command"])
  assert next_args.command == "plan"
  assert next_args.machine == "workstation"
  assert next_args.home is None
  child = parse_hint(result["environment"]["zsh"]["next_command"])
  # 可选插件 sync 也是写操作；诊断 HOME 不能授权下载到另一个保存目标。
  assert child.command == "plan"
  assert child.home is None
  assert cli.main(["--machine", "workstation", "plan", "--json"]) == 0
  saved = payload(capsys)
  assert saved["plan_id"] != result["plan_id"]
  assert cli.main(["--machine", "workstation", "apply", "--plan-id", result["plan_id"], "--json"]) == 2
  assert payload(capsys)["reason"] == "plan_id_mismatch"
  assert not (isolated_environment.home / ".zshrc").exists()


def test_legacy_status_guidance_prioritizes_recovery_without_new_reads(monkeypatch, capsys):
  from termcfg.config import MachineSelection
  from termcfg import state
  machine = MachineSelection("workstation", Path("/synthetic/home"), Path("/synthetic/state"), ("zsh", "mihomo"))
  monkeypatch.setattr(cli, "read_machine", lambda *a, **k: machine)
  monkeypatch.setattr(state, "read_state", lambda *a, **k: {"version": 1})
  for journal, expected in ((None, "migrate"), ({"synthetic": True}, "recover")):
    monkeypatch.setattr(cli, "read_journal", lambda *a: journal)
    assert cli.main(["--machine", "workstation", "status", "--json"]) == 0
    next_args = parse_hint(payload(capsys)["next_command"])
    assert next_args.command == expected
    assert next_args.machine == "workstation"
    assert not hasattr(next_args, "component")


def test_mid_apply_failure_retains_named_recovery_scope(isolated_environment, fake_terminal_commands, monkeypatch, capsys):
  from termcfg import transaction
  assert cli.main(["--machine", "workstation", "init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  assert cli.main(["--machine", "workstation", "plan", "--json"]) == 0
  plan = payload(capsys)
  original = transaction.atomic_target_bytes
  def fail_after_write(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("PRIVATE-CANARY")
  monkeypatch.setattr(transaction, "atomic_target_bytes", fail_after_write)
  assert cli.main(["--machine", "workstation", "apply", "--plan-id", plan["plan_id"], "--json"]) == 6
  result = payload(capsys)
  assert result["side_effect"] == "recovery_pending"
  assert result["transaction_id"]
  next_args = parse_hint(result["next_command"])
  assert next_args.command == "recover"
  assert next_args.machine == "workstation"
  assert not hasattr(next_args, "component")
  assert cli.main(["--machine", "workstation", "doctor", "--json"]) == 0
  diagnostic = payload(capsys)
  assert parse_hint(diagnostic["next_command"]).command == "recover"
  assert parse_hint(diagnostic["components"]["zsh"]["next_command"]).command == "recover"


def test_unchanged_preview_suggests_observation_not_repeated_apply(isolated_environment, fake_terminal_commands, capsys):
  assert cli.main(["--machine", "workstation", "init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  assert cli.main(["--machine", "workstation", "plan", "--json"]) == 0
  plan = payload(capsys)
  assert cli.main(["--machine", "workstation", "apply", "--plan-id", plan["plan_id"], "--json"]) == 0
  payload(capsys)
  assert cli.main(["--machine", "workstation", "plan", "--json"]) == 0
  unchanged = payload(capsys)
  assert all(target["action"] == "unchanged" for target in unchanged["targets"])
  assert parse_hint(unchanged["next_command"]).command == "status"
  assert parse_hint(unchanged["next_command"]).machine == "workstation"


def test_legacy_status_does_not_guess_unverified_home_scope(monkeypatch, capsys):
  from termcfg.config import MachineSelection
  from termcfg import state
  machine = MachineSelection("workstation", Path("/synthetic/home"), Path("/synthetic/state"), ("mihomo",))
  monkeypatch.setattr(cli, "read_machine", lambda *a, **k: machine)
  monkeypatch.setattr(state, "read_state", lambda *a, **k: {"version": 1})
  monkeypatch.setattr(cli, "read_journal", lambda *a: None)
  assert cli.main(["--machine", "workstation", "status", "--home", "/PRIVATE-CANARY", "--json"]) == 0
  output = capsys.readouterr().out
  assert "PRIVATE-CANARY" not in output
  assert json.loads(output)["next_command"] == "./termcfg plan --help"
def _rotom_context(path, *, policy="auto", answer="", ttys=(True, True, True)):
  import io
  from rotom.context import InputGateway, InvocationContext, InputPolicy
  class Stream(io.StringIO):
    def __init__(self, content, tty):
      super().__init__(content)
      self.tty = tty
    def isatty(self):
      return self.tty
  streams = [Stream(answer if i == 0 else "", tty) for i, tty in enumerate(ttys)]
  return InvocationContext(tuple(path), input_policy=InputPolicy(policy), input_gateway=InputGateway(*streams))


def test_rotom_no_input_init_explicit_components_never_reads_input(isolated_environment, monkeypatch):
  import io
  from termcfg.cli import main
  class Tty(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", Tty())
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  context = _rotom_context(("term", "init-local"), policy="no_input")
  assert main(["init-local", "--component", "zsh"], context=context) == 0


@pytest.mark.parametrize("ttys", [(True, False, True), (True, True, False), (False, True, True)])
def test_rotom_init_missing_selection_requires_all_three_ttys(isolated_environment, monkeypatch, sentinel_factory, ttys):
  from termcfg.cli import main
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  before = sentinel_factory(isolated_environment.home)
  context = _rotom_context(("term", "init-local"), answer="zsh\nyes\n", ttys=ttys)
  assert main(["init-local"], context=context) == 2
  before.assert_unchanged()
  assert context.input_gateway.stdin.tell() == 0


def test_rotom_init_cancel_before_acceptance_creates_no_files(isolated_environment, monkeypatch, sentinel_factory):
  from termcfg.cli import main
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  before = sentinel_factory(isolated_environment.home)
  context = _rotom_context(("term", "init-local"), answer="\n")
  assert main(["init-local"], context=context) == 130
  before.assert_unchanged()


def test_rotom_apply_no_input_complete_approval_ignores_stdin_tty(isolated_environment, monkeypatch, fake_terminal_commands):
  import io
  from termcfg.cli import main
  from termcfg.config import read_machine
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  plan = build_preview(read_machine("default"), ("zsh",))
  class Tty(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", Tty())
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  context = _rotom_context(("term", "apply"), policy="no_input")
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id], context=context) == 0


def test_rotom_apply_missing_approval_reports_two_before_input_or_write(isolated_environment, monkeypatch, sentinel_factory, fake_terminal_commands):
  from termcfg.cli import main
  assert main(["init-local", "--component", "zsh"]) == 0
  before = sentinel_factory(isolated_environment.home)
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  context = _rotom_context(("term", "apply"), policy="no_input")
  assert main(["apply", "--component", "zsh"], context=context) == 2
  before.assert_unchanged()


def test_rotom_apply_cancel_keeps_current_action_unaccepted(isolated_environment, monkeypatch, sentinel_factory, fake_terminal_commands):
  from termcfg.cli import main
  assert main(["init-local", "--component", "zsh"]) == 0
  before = sentinel_factory(isolated_environment.home)
  monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("legacy input called"))
  context = _rotom_context(("term", "apply"), answer="no\n")
  assert main(["apply", "--component", "zsh"], context=context) == 130
  before.assert_unchanged()
def test_rotom_term_hints_keep_selected_machine_and_components(isolated_environment, capsys):
  from termcfg.cli import main
  context = _rotom_context(("term", "init-local"), policy="no_input")
  assert main(["--machine", "workstation", "init-local", "--component", "zsh", "--json"], context=context) == 0
  result = json.loads(capsys.readouterr().out)
  assert shlex.split(result["next_command"]) == ["rotom", "term", "--machine", "workstation", "doctor", "--component", "zsh"]


@pytest.mark.parametrize("adopt", [False, True])
def test_rotom_apply_missing_distinct_approval_keeps_private_and_home_files(isolated_environment, fake_terminal_commands, sentinel_factory, adopt):
  from termcfg.cli import main
  from termcfg.config import read_machine
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  target = isolated_environment.home / ".zshenv"
  target.write_text("export EDITOR=vi\n")
  plan = build_preview(read_machine("default"), ("zsh",))
  before = sentinel_factory(isolated_environment.home)
  context = _rotom_context(("term", "apply"), policy="no_input")
  args = ["apply", "--component", "zsh", "--plan-id", plan.plan_id]
  if adopt:
    args += ["--adopt-target", "zshenv"]
  assert main(args, context=context) == 2
  before.assert_unchanged()


def test_rotom_rollback_cancel_before_acceptance_preserves_all_files(isolated_environment, fake_terminal_commands, sentinel_factory):
  from termcfg.cli import main
  from termcfg.config import read_machine
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  plan = build_preview(read_machine("default"), ("zsh",))
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 0
  before = sentinel_factory(isolated_environment.home)
  context = _rotom_context(("term", "rollback"), answer="no\n")
  assert main(["rollback", "--component", "zsh"], context=context) == 130
  before.assert_unchanged()


def test_rotom_init_rejects_file_change_during_read_before_prompt(isolated_environment, monkeypatch):
  from termcfg import cli
  from termcfg.config import machine_path
  assert cli.main(["init-local", "--component", "zsh"]) == 0
  read = cli.read_machine
  path = machine_path("default")
  def changed(*a, **k):
    result = read(*a, **k)
    path.write_bytes(path.read_bytes() + b"\n# external edit\n")
    return result
  monkeypatch.setattr(cli, "read_machine", changed)
  context = _rotom_context(("term", "init-local"), answer="yes\n")
  assert cli.main(["init-local", "--edit", "--component", "tmux"], context=context) == 4
  assert context.input_gateway.stdin.tell() == 0
  assert path.read_bytes().endswith(b"# external edit\n")
