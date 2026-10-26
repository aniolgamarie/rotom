"""逐叶输入策略与真实输入接缝；不打开 TTY 或运行原生宿主。"""
import io
import itertools
from types import SimpleNamespace

import pytest

from rotom import cli
from rotom.context import InputGateway, InputPolicy, InvocationContext


def test_reused_parser_restores_required_position_option_and_exclusive_group():
  parser = cli.Parser(prog="rotom")
  commands = parser.add_subparsers(dest="command", required=True)
  child = commands.add_parser("probe")
  child.add_argument("target")
  child.add_argument("--mode", required=True)
  group = child.add_mutually_exclusive_group(required=True)
  group.add_argument("--left", action="store_true")
  group.add_argument("--right", action="store_true")
  cli._relax_missing(parser)
  assert parser.parse_args([]).command is None
  assert parser.parse_args(["probe"]).target is None
  cli._restore_missing(parser)
  for arguments in ([], ["probe", "--mode", "example", "--left"],
      ["probe", "target", "--left"], ["probe", "target", "--mode", "example"]):
    with pytest.raises(SystemExit) as error:
      parser.parse_args(arguments)
    assert error.value.code == 2
  assert parser.parse_args(["probe", "target", "--mode", "example", "--left"]).target == "target"


class Stream(io.StringIO):
  def __init__(self, value="", *, tty=True):
    super().__init__(value)
    self.tty = tty
    self.reads = 0

  def isatty(self):
    return self.tty

  def fileno(self):
    return 71

  def readline(self, *args):
    self.reads += 1
    return super().readline(*args)


def gateway(tty=(True, True, True), answer=""):
  return InputGateway(Stream(answer, tty=tty[0]), Stream(tty=tty[1]), Stream(tty=tty[2]))


@pytest.mark.parametrize("path", list(cli.COMMANDS))
@pytest.mark.parametrize("tty", list(itertools.product((False, True), repeat=3)))
@pytest.mark.parametrize("policy", [InputPolicy.AUTO, InputPolicy.NO_INPUT, InputPolicy.INTERACTIVE])
def test_every_leaf_uses_same_three_stream_input_gate(path, tty, policy):
  current = gateway(tty)
  allowed = policy != InputPolicy.NO_INPUT and all(tty)
  if allowed:
    current.require_input(policy)
  else:
    with pytest.raises(Exception) as error:
      current.require_input(policy)
    assert error.value.exit_code == 2
  assert current.stdin.reads == 0
  assert cli.COMMANDS[path].parameters is not None


@pytest.mark.parametrize("answer", ["", "\n", "\x1b\n"])
def test_single_candidate_and_empty_input_never_approve(answer):
  current = gateway(answer=answer)
  with pytest.raises(Exception) as error:
    current.choose([("opaque", "Only target")], policy=InputPolicy.AUTO)
  assert error.value.exit_code == 130


def test_numbered_selection_keeps_opaque_id_and_uses_stderr():
  current = gateway(answer="2\n")
  assert current.choose([("first-id", "Same label"), ("second-id", "Same label")], policy=InputPolicy.AUTO) == "second-id"
  assert current.stdout.getvalue() == ""
  assert "Same label" in current.stderr.getvalue()


def test_hidden_input_uses_existing_stdin_and_restores_echo(monkeypatch):
  import termios
  current = gateway(answer="synthetic-secret\n")
  old = [1, 2, 3, termios.ECHO | termios.ICANON, 4, 5, []]
  changes = []
  monkeypatch.setattr(termios, "tcgetattr", lambda fd: list(old))
  monkeypatch.setattr(termios, "tcsetattr", lambda fd, mode, flags: changes.append((fd, list(flags))))
  monkeypatch.setattr("getpass.getpass", lambda *a: pytest.fail("getpass can open /dev/tty"))
  assert current.hidden("Hidden value", policy=InputPolicy.AUTO) == "synthetic-secret"
  assert len(changes) == 2 and changes[0][0] == 71
  assert not changes[0][1][3] & termios.ECHO and changes[-1][1] == old
  assert "synthetic-secret" not in current.stderr.getvalue() + current.stdout.getvalue()


@pytest.mark.parametrize("argv", [[], ["agent"], ["agent", "model"], ["term"], ["work"], ["work", "source"], ["config"]])
def test_each_group_navigates_without_business_reads(argv, monkeypatch, capsys):
  current = gateway(answer="\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main(argv) == 130
  assert current.stdin.reads == 1
  assert current.stdout.getvalue() == ""
  assert "参数或输入条件不满足" not in current.stderr.getvalue()
  captured = capsys.readouterr()
  assert captured.out == captured.err == ""


def test_missing_enumerated_parameter_is_filled_without_changing_explicit_scope(monkeypatch):
  import agentcfg.cli
  current = gateway(answer="2\n")
  seen = []
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 0)
  assert cli.main(["run", "--local", "explicit.toml"]) == 0
  assert "pi" in seen[0][0] and seen[0][1].scope.local == "explicit.toml"
  assert seen[0][1].scope.sources["local"] == "explicit"


@pytest.mark.parametrize("path", [("agent", "model", "add"), ("agent", "model", "key"), ("agent", "model", "url")])
@pytest.mark.parametrize("policy", [InputPolicy.NO_INPUT, InputPolicy.AUTO])
def test_hidden_model_inputs_refuse_before_workspace_or_credentials(path, policy, monkeypatch):
  from agentcfg import model_keys, model_urls, model_wizard
  modules = {"add": (model_wizard, "add_model"), "key": (model_keys, "set_model_key"), "url": (model_urls, "set_model_url")}
  module, handler = modules[path[-1]]
  monkeypatch.setattr(module, "load_workspace", lambda *a, **k: pytest.fail("secret input blocked before workspace"))
  current = gateway((True, True, False))
  context = InvocationContext(path, input_policy=policy, input_gateway=current)
  with pytest.raises(Exception) as error:
    getattr(module, handler)(SimpleNamespace(invocation_context=context))
  assert error.value.exit_code == 2
  assert current.stdin.reads == 0


def test_work_selector_without_input_fails_before_discovery(monkeypatch):
  from termcfg import work_ui, work_projects
  monkeypatch.setattr(work_projects, "discover", lambda *a: pytest.fail("no-input selector discovered projects"))
  context = InvocationContext(("work", "list"), input_policy=InputPolicy.NO_INPUT, input_gateway=gateway())
  with pytest.raises(Exception) as error:
    work_ui.selector(SimpleNamespace(), context=context)
  assert error.value.exit_code == 2


def test_work_fzf_unavailable_falls_back_to_same_numbered_ids(monkeypatch):
  from termcfg import work_ui
  from termcfg.errors import TermcfgError
  monkeypatch.setattr(work_ui, "resolve_executable", lambda *a: (_ for _ in ()).throw(TermcfgError(5, "unavailable")))
  current = gateway(answer="2\n")
  context = InvocationContext(("work", "list"), input_gateway=current)
  assert work_ui.select([("id-a", "A"), ("id-b", "B")], context=context) == "id-b"


def test_hidden_echo_is_restored_on_eof(monkeypatch):
  import termios
  current = gateway()
  old = [0, 0, 0, termios.ECHO, 0, 0, []]
  changes = []
  monkeypatch.setattr(termios, "tcgetattr", lambda fd: list(old))
  monkeypatch.setattr(termios, "tcsetattr", lambda fd, mode, flags: changes.append(list(flags)))
  with pytest.raises(Exception) as error:
    current.hidden("Hidden", policy=InputPolicy.AUTO)
  assert error.value.exit_code == 130 and changes[-1] == old


@pytest.mark.parametrize("path", [("agent", "model", "add"), ("agent", "model", "key"), ("agent", "model", "url"), ("agent", "model", "enable")])
def test_no_input_hidden_command_stops_before_selection_metadata(path, monkeypatch):
  from agentcfg import cli as legacy
  from rotom.context import InputPolicy
  monkeypatch.setattr(legacy, "resolve_selection", lambda *a: pytest.fail("hidden input read machine metadata"))
  current = gateway()
  context = InvocationContext(path, input_policy=InputPolicy.NO_INPUT, input_gateway=current)
  tail = {"add": [], "key": ["synthetic-provider"], "url": ["synthetic-provider"], "enable": ["kimi-code"]}[path[-1]]
  assert legacy.main([*path[1:], *tail], context=context) == 2
  assert current.stdin.reads == 0


@pytest.mark.parametrize("answer", ["", "\n", "3\n", "1\n", "2\n"])
def test_run_failure_followup_keeps_original_result_and_scope(monkeypatch, answer, capsys):
  from pathlib import Path
  from agentcfg import commands
  from agentcfg import cli as legacy
  from rotom.context import Scope
  current = gateway(answer=answer)
  context = InvocationContext(("run",), scope=Scope(machine="fixture", profile="pi-pro"), input_gateway=current)
  seen = []
  monkeypatch.setattr(legacy, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 0)
  args = SimpleNamespace(profile="pi-pro", local=Path("fixture.toml"))
  assert commands._run_followup(args, context, 4) is None
  assert len(seen) == (1 if answer in ("1\n", "2\n") else 0)
  if seen:
    assert seen[0][0][:4] == ["--machine", "fixture", "--profile", "pi-pro"]
    assert seen[0][0][-1] in ("plan", "setup")
    assert "command" not in seen[0][1].explicit_fields
  result = capsys.readouterr()
  assert result.out == "" and "原启动结果" in result.err


def test_run_failure_no_input_only_static_advice(monkeypatch, capsys):
  from agentcfg import commands
  from agentcfg import cli as legacy
  from rotom.context import Scope
  current = gateway(answer="2\n")
  context = InvocationContext(("run",), scope=Scope(local="chosen.toml", profile="pi-pro"),
    input_policy=InputPolicy.NO_INPUT, input_gateway=current)
  monkeypatch.setattr(legacy, "main", lambda *a, **k: pytest.fail("no-input started failure followup"))
  commands._run_followup(SimpleNamespace(profile="pi-pro"), context, 4)
  assert current.stdin.reads == 0
  assert "--local chosen.toml --profile pi-pro setup" in capsys.readouterr().err


@pytest.mark.parametrize("path", list(cli.COMMANDS))
@pytest.mark.parametrize("tty", list(itertools.product((False, True), repeat=3)))
@pytest.mark.parametrize("policy", [InputPolicy.AUTO, InputPolicy.NO_INPUT, InputPolicy.INTERACTIVE])
def test_actual_parser_leaf_missing_input_and_complete_defaults(path, tty, policy, monkeypatch):
  import agentcfg.cli
  import termcfg.cli
  import termcfg.work
  current = gateway(tty)
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  for module in (agentcfg.cli, termcfg.cli, termcfg.work):
    monkeypatch.setattr(module, "main", lambda tokens, *, context=None: 0)
  # 列表已接通真实只读执行器；输入矩阵同其它业务路径一样使用 fake，行为另有实例套件。
  monkeypatch.setattr(cli, "dispatch_instances", lambda *args: 0)
  if path in (("agent", "maintenance", "plan"), ("agent", "maintenance", "stop")):
    # 运行缺失是条件输入；矩阵只验证输入门槛，受管实例查询另有集成测试。
    from rotom import maintenance
    monkeypatch.setattr(maintenance, "_choose_runs", lambda scope, context:
      [context.input_gateway.text("明确运行", policy=context.input_policy)])
  if path == ("resume",):
    # 默认恢复已接真实查询；输入矩阵只模拟空候选，实际接线另有集成套件。
    from rotom import resume
    provider = resume.CandidateResume(lambda scope: ("synthetic-scope", ()),
      lambda target: pytest.fail("取消输入不能构造后端"),
      lookup_explicit=lambda *args: pytest.fail("取消输入不能查询元数据"))
    monkeypatch.setattr(resume, "dsh_candidate", lambda: provider)
  from rotom.context import Scope
  original_candidates = cli._candidate_rows
  def candidates(current_path, action, args):
    if action.dest in ("provider", "template"):
      return ([("synthetic-id", "Synthetic candidate")], Scope(machine="fixture", profile="pi-base" if action.dest == "provider" else None))
    return original_candidates(current_path, action, args)
  monkeypatch.setattr(cli, "_candidate_rows", candidates)
  parser, actions = dict(cli.parser_leaves(cli.build_parser()))[path]
  missing = any(action.required for action in actions) or any(group.required for group in parser._mutually_exclusive_groups)
  missing = missing or path in (("run",), ("resume",), ("agent", "maintenance", "plan"), ("agent", "maintenance", "stop"))
  hidden = path in (("agent", "model", "add"), ("agent", "model", "key"), ("agent", "model", "url"), ("agent", "model", "enable"))
  flags = ["--no-input"] if policy == InputPolicy.NO_INPUT else ["--interactive"] if policy == InputPolicy.INTERACTIVE else []
  code = cli.main([*flags, *path])
  allowed = policy != InputPolicy.NO_INPUT and all(tty)
  if path == ("_complete",):
    assert code == 2
    assert current.stdin.reads == 0
  elif policy == InputPolicy.INTERACTIVE and not all(tty) or (missing or hidden) and not allowed:
    assert code == 2
  elif missing:
    assert code == 130
  elif path == ("agent", "instances", "list"):
    assert code == 0
  elif path[:2] in (("agent", "instances"), ("agent", "maintenance")):
    assert code == 5
  else:
    assert code == 0
  if not allowed:
    assert current.stdin.reads == 0


@pytest.mark.parametrize("path", list(cli.COMMANDS))
def test_every_leaf_unknown_arguments_rejected_without_correction(path, monkeypatch):
  current = gateway(answer="1\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  tokens = ["agent", "--unregistered-option", "usage"] if path == ("agent", "usage") else [*path, "--unregistered-option"]
  assert cli.main(tokens) == 2
  assert current.stdin.reads == 0


def test_actual_leaf_registry_coverage_is_bidirectional():
  assert set(dict(cli.parser_leaves(cli.build_parser()))) == set(cli.COMMANDS)


def test_hidden_echo_restore_is_attempted_when_disable_fails(monkeypatch):
  import termios
  current = gateway(answer="never-read\n")
  old = [0, 0, 0, termios.ECHO, 0, 0, []]
  changes = []
  monkeypatch.setattr(termios, "tcgetattr", lambda fd: list(old))
  def apply(fd, mode, flags):
    changes.append(list(flags))
    if len(changes) == 1:
      raise termios.error("synthetic failure")
  monkeypatch.setattr(termios, "tcsetattr", apply)
  with pytest.raises(Exception) as error:
    current.hidden("Hidden", policy=InputPolicy.AUTO)
  assert error.value.exit_code == 2 and changes[-1] == old
  assert current.stdin.reads == 0


def test_complete_structured_command_preserves_json_and_never_navigates(monkeypatch, capsys):
  import json
  from pathlib import Path
  from agentcfg import cli as legacy, commands
  current = gateway((False, False, False), "forbidden\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  def selection(args):
    args.local = Path(args.local)
  def validate(args):
    print(json.dumps({"command": "validate", "profile": args.profile, "valid": True}))
    return 0
  monkeypatch.setattr(legacy, "resolve_selection", selection)
  monkeypatch.setattr(commands, "cmd_validate", validate)
  assert cli.main(["--no-input", "agent", "--local", "selected.toml", "--profile", "pi-base", "validate", "--format", "json"]) == 0
  assert json.loads(capsys.readouterr().out) == {"command": "validate", "profile": "pi-base", "valid": True}
  assert current.stdin.reads == 0


def test_navigation_setup_requires_separate_confirmation_after_preview(monkeypatch):
  from agentcfg import commands
  from types import SimpleNamespace
  current = gateway(answer="no\n")
  context = InvocationContext(("agent", "setup"), input_gateway=current)
  from pathlib import Path
  from agentcfg.deployment import Plan
  workspace = SimpleNamespace(agent="pi", profile="pi-base", adapter=SimpleNamespace(),
    binding={"machine": "fixture", "local": "/synthetic/local.toml", "profile": "pi-base"},
    instance=Path("/synthetic/instance"), state_root=Path("/synthetic/state"), cache=Path("/synthetic/cache"))
  lock = SimpleNamespace(identity="fixture")
  candidate = SimpleNamespace(generation="candidate")
  preview = Plan(current={}, changes=[], conflicts=[], drift=[])
  monkeypatch.setattr(commands, "prepared", lambda args: (workspace, lock, candidate))
  monkeypatch.setattr(commands, "current_plan", lambda *args: preview)
  monkeypatch.setattr(commands, "sync_backend", lambda *a: pytest.fail("selection approved setup implicitly"))
  args = SimpleNamespace(invocation_context=context)
  with pytest.raises(Exception) as error:
    commands.cmd_setup(args)
  assert error.value.exit_code == 130


def test_navigation_init_local_cancel_never_creates_configuration(monkeypatch):
  from agentcfg import commands
  current = gateway(answer="\n")
  context = InvocationContext(("agent", "init-local"), input_gateway=current)
  monkeypatch.setattr(commands, "initialize_local", lambda *a, **k: pytest.fail("cancelled initialization wrote files"))
  with pytest.raises(Exception) as error:
    commands.cmd_init_local(SimpleNamespace(invocation_context=context))
  assert error.value.exit_code == 130


def test_navigation_describes_tool_handoffs_and_independent_maintenance(monkeypatch):
  current = gateway(answer="\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main([]) == 130
  assert "DSH/Pi/OMP" in current.stderr.getvalue()
  assert "加载待确认" in current.stderr.getvalue()
  assert current.stdout.getvalue() == ""

  pending = gateway(answer="\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: pending)
  assert cli.main(["agent", "maintenance"]) == 130
  assert "独立批准" in pending.stderr.getvalue()
  assert "加载待确认" in pending.stderr.getvalue()
  assert pending.stdout.getvalue() == ""


def test_static_help_precedes_interactive_policy_and_missing_required_input(monkeypatch):
  current = gateway((False, False, False))
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main(["--interactive", "agent", "model", "key", "--help"]) == 0
  assert current.stdin.reads == 0


@pytest.mark.parametrize("tokens", [
  ["resume", "dsh", "--profile", "pi-base"],
  ["work", "worktree", "create", "--existing-branch", "feature", "--base", "HEAD"],
])
def test_explicit_semantic_conflicts_precede_missing_field_prompts(tokens, monkeypatch):
  current = gateway(answer="forbidden\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  assert cli.main(tokens) == 2
  assert current.stdin.reads == 0


def test_new_worktree_branch_prompts_only_for_missing_local_base(monkeypatch):
  from termcfg import work
  current = gateway(answer="refs/heads/main\n")
  seen = []
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  monkeypatch.setattr(work, "main", lambda tokens, *, context=None: seen.append(tokens) or 17)
  assert cli.main(["work", "--local", "chosen.toml", "worktree", "create", "--repo", "repo",
    "--path", "destination", "--template", "dev", "--new-branch", "feature"]) == 17
  assert seen[0][-1] == "--base=refs/heads/main"
  assert current.stdin.reads == 1


@pytest.mark.parametrize("tokens,module", [
  (["term", "status", "--mach", "fixture"], "termcfg.cli"),
  (["work", "named", "add", "--id", "synthetic", "--title", "Title", "--tem", "dev"], "termcfg.work"),
])
def test_facade_nested_abbreviations_fail_before_input_or_dispatch(tokens, module, monkeypatch):
  import importlib
  current = gateway(answer="forbidden\n")
  monkeypatch.setattr(cli, "InputGateway", lambda: current)
  monkeypatch.setattr(importlib.import_module(module), "main", lambda *a, **k: 0)
  assert cli.main(tokens) == 2
  assert current.stdin.reads == 0


def test_hidden_url_whitespace_is_cancelled_without_private_write(monkeypatch):
  from agentcfg import cli as legacy
  from test_model_urls import machine
  assert legacy.main(["init-local", "--profile", "omp-kernel"]) == 0
  original = machine().read_bytes()
  current = gateway()
  context = InvocationContext(("agent", "model", "url"), input_gateway=current)
  monkeypatch.setattr(InputGateway, "hidden", lambda *a, **k: "   ")
  assert legacy.main(["model", "url", "kimi_tf"], context=context) == 130
  assert machine().read_bytes() == original
