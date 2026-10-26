"""统一门面的隔离契约；业务执行用替身。"""
import pytest
from rotom import cli


@pytest.mark.parametrize("namespace,module,argv", [
  ("agent", "agentcfg.cli", ["profiles"]),
  ("term", "termcfg.cli", ["components"]),
  ("work", "termcfg.work", ["config", "check"]),
])
def test_routes_preserve_context_and_exit(namespace, module, argv, monkeypatch):
  import importlib
  backend = importlib.import_module(module)
  seen = []
  monkeypatch.setattr(backend, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 17)
  assert cli.main([namespace, *argv]) == 17
  assert seen[0][0] == (["--machine", "default", *argv] if namespace == "work" else argv)
  assert seen[0][1].command_path == (namespace, *argv)


def test_native_tails_are_opaque(monkeypatch):
  import agentcfg.cli
  seen = []
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 23)
  tail = ["--help", "--machine", "native", "", "a b"]
  assert cli.main(["run", "pi", "--", *tail]) == 23
  assert seen[-1][0][-len(tail):] == tail
  assert cli.main(["agent", "usage", *tail]) == 23
  assert seen[-1][0] == ["usage", *tail]


@pytest.mark.parametrize("argv", [
  ["run", "pi", "--machine", "a", "--machine", "b"],
  ["term", "--machine", "a", "components", "--machine", "b"],
  ["work", "--local", "a", "--machine", "b", "list"],
  ["run", "pi", "--unknown"], ["config", "unknown"],
])
def test_invalid_arguments(argv):
  assert cli.main(argv) == 2


@pytest.mark.parametrize("argv", [[], ["agent"], ["term"], ["work"], ["config"],
  ["agent", "model", "key"], ["work", "worktree", "create"]])
def test_static_help(argv):
  assert cli.main([*argv, "--help"]) == 0


def test_resume_capability_gate():
  assert cli.main(["--no-input", "resume"]) == 2
  assert cli.main(["resume", "pi", "--session", "synthetic-session", "--machine", "fixture"]) == 5


@pytest.mark.parametrize("location", [[], ["--here"]])
@pytest.mark.parametrize("tool", ["pi", "omp"])
def test_unsupported_tools_do_not_construct_a_resume_coordinator(monkeypatch, location, tool):
  import agentcfg.sessions
  def forbidden(*args, **kwargs):
    pytest.fail("未准入工具不得构造恢复协调器")
  monkeypatch.setattr(agentcfg.sessions, "ResumeCoordinator", forbidden, raising=False)
  assert cli.main(["--no-input", "resume", tool, "--session", "synthetic-session",
    "--machine", "fixture", *location]) == 5


def test_registry_covers_parser_both_directions():
  parser = cli.build_parser()
  assert set(cli.COMMANDS) == set(dict(cli.parser_leaves(parser)))
  for definition in cli.COMMANDS.values():
    assert definition.scope_rule and definition.noninteractive_approval
    assert definition.help and definition.examples and definition.effects
    assert all(parameter.category in "ETDAN" for parameter in definition.parameters)


def test_registry_can_derive_metadata_from_existing_strict_parser(monkeypatch):
  parser = cli.build_parser()
  def forbidden():
    pytest.fail("an existing parser must not trigger another parser build")
  monkeypatch.setattr(cli, "build_parser", forbidden)
  definitions = cli._registry(parser)
  assert set(definitions) == set(dict(cli.parser_leaves(parser)))


def test_command_mapping_is_lazy_readonly_and_retains_no_parser_or_actions(monkeypatch):
  import gc
  import weakref
  fresh = type(cli.COMMANDS)()
  original = cli.build_parser
  references = []
  builds = []
  def build():
    parser = original()
    builds.append(True)
    references.append(weakref.ref(parser))
    actions = {action for _, (_, actions) in cli.parser_leaves(parser) for action in actions}
    references.extend(weakref.ref(action) for action in actions)
    return parser
  monkeypatch.setattr(cli, "build_parser", build)
  assert builds == []
  assert ("run",) in fresh
  assert len(fresh) == len({tuple(line.split()) for line in cli._PATHS.splitlines() if line})
  assert set(fresh) == {definition.parser_leaf for definition in fresh.values()}
  assert fresh.get(("run",)) == fresh[("run",)]
  assert builds == [True]
  with pytest.raises(TypeError):
    fresh[("invented",)] = fresh[("run",)]
  gc.collect()
  assert all(reference() is None for reference in references)


def test_first_main_builds_once_and_caches_strict_metadata_before_relaxation(monkeypatch):
  fresh = type(cli.COMMANDS)()
  monkeypatch.setattr(cli, "COMMANDS", fresh)
  original = cli.build_parser
  parsers = []
  def build():
    parser = original()
    parsers.append(parser)
    return parser
  monkeypatch.setattr(cli, "build_parser", build)
  monkeypatch.setattr(cli, "dispatch", lambda *args: 17)
  assert cli.main(["--no-input", "config", "show"]) == 17
  assert len(parsers) == 1
  parameter = next(item for item in fresh[("agent", "instances", "stop")].parameters if item.name == "run")
  assert parameter.required


def test_consecutive_main_calls_build_distinct_parsers_without_relaxed_constraint_leak(monkeypatch):
  monkeypatch.setattr(cli, "COMMANDS", type(cli.COMMANDS)())
  original = cli.build_parser
  parsers = []
  def build():
    parser = original()
    parsers.append(parser)
    return parser
  monkeypatch.setattr(cli, "build_parser", build)
  assert cli.main(["--no-input", "config", "set"]) == 2
  assert cli.main(["config", "set", "--help"]) == 0
  assert len(parsers) == 2 and parsers[0] is not parsers[1]
  with pytest.raises(SystemExit) as caught:
    parsers[1].parse_args(["config", "set"])
  assert caught.value.code == 2


def test_context_rejects_unregistered_paths():
  from rotom.context import InvocationContext
  with pytest.raises(ValueError):
    InvocationContext(command_path=("unknown",))


def test_legacy_parsers_remain_available():
  from agentcfg.cli import build_parser as agent_parser
  from termcfg.cli import build_parser as term_parser
  from termcfg.work import build_parser as work_parser
  assert agent_parser().parse_args(["run", "pi", "--", "--help"]).passthrough == ["--help"]
  assert term_parser().parse_args(["components"]).machine == "default"
  assert work_parser().parse_args(["open"]).role is None


@pytest.mark.parametrize("argv", [["term", "missing"], ["work", "missing"],
  ["agent", "model", "missing"], ["resume", "dsh", "--session", "x", "--here", "--original"]])
def test_namespace_errors_are_exit_two(argv):
  assert cli.main(argv) == 2


def test_agent_compatibility_run_tail(monkeypatch):
  import agentcfg.cli
  seen = []
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append(tokens) or 19)
  assert cli.main(["agent", "run", "pi", "--", "--help", "--no-input"]) == 19
  assert seen == [["--machine", "default", "run", "pi", "--", "--help", "--no-input"]]


@pytest.mark.parametrize("change", ["added", "removed"])
def test_registry_rejects_added_or_removed_parser_leaf(monkeypatch, change):
  original = cli.build_parser
  def changed():
    parser = original()
    if change == "added":
      cli._subparsers(parser).add_parser("unregistered")
    else:
      del cli._subparsers(parser).choices["resume"]
    return parser
  monkeypatch.setattr(cli, "build_parser", changed)
  with pytest.raises(ValueError):
    cli._registry()


def test_static_help_never_reads_business_configuration(monkeypatch):
  import agentcfg.cli
  import termcfg.cli
  import termcfg.work_config
  def forbidden(*args, **kwargs):
    raise AssertionError("business config read during static help")
  monkeypatch.setattr(agentcfg.cli, "resolve_selection", forbidden)
  monkeypatch.setattr(termcfg.cli, "read_machine", forbidden)
  monkeypatch.setattr(termcfg.work_config, "read_settings", forbidden)
  for argv in (["agent", "model", "key"], ["term", "apply"], ["work", "worktree", "create"], ["resume"]):
    assert cli.main([*argv, "--help"]) == 0


def test_work_recursive_dispatch_keeps_context(monkeypatch):
  from types import SimpleNamespace
  from rotom.context import InvocationContext
  from termcfg import work, work_ui
  context = InvocationContext(("work", "enter"))
  settings = SimpleNamespace(selectors=("--machine", "fixture"))
  seen = []
  selected_contexts = []
  def selector(settings, *, context=None):
    selected_contexts.append(context)
    return ["config", "check"]
  monkeypatch.setattr(work_ui, "selector", selector)
  monkeypatch.setattr(work, "main", lambda argv, *, context=None: seen.append((argv, context)) or 7)
  assert work.structured_command(SimpleNamespace(command=None), settings, context=context) == 7
  assert seen == [(["--machine", "fixture", "config", "check"], context)]
  assert selected_contexts == [context]


@pytest.mark.parametrize("code", [0, 2, 3, 4, 5, 6, 130, 27])
def test_native_exit_status_preserved(monkeypatch, code):
  import agentcfg.cli
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: code)
  assert cli.main(["agent", "usage", "--help"]) == code


@pytest.mark.parametrize("argv", [["--no-input", "agent"], ["--no-input", "work"],
  ["--no-input", "agent", "--local", "synthetic-private-canary.toml"]])
def test_missing_subcommand_returns_two(argv, monkeypatch, capsys):
  from types import SimpleNamespace
  from rotom import preferences
  def forbidden(*args, **kwargs):
    pytest.fail("missing input must not read stdin, configuration or dispatch")
  monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False, readline=forbidden))
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  monkeypatch.setattr(cli, "dispatch", forbidden)
  assert cli.main(argv) == 2
  captured = capsys.readouterr()
  assert captured.out == ""
  assert captured.err == "rotom: 参数或输入条件不满足；请查看当前命令 --help，补齐必要参数；交互选择需要在终端中运行。\n"
  assert "synthetic-private-canary" not in captured.err


def test_entry_disables_bytecode_before_business_import(tmp_path, monkeypatch):
  from pathlib import Path
  import runpy
  import sys
  entry = Path(__file__).resolve().parents[1] / "rotom"
  previous = sys.dont_write_bytecode
  try:
    namespace = runpy.run_path(str(entry))
    assert sys.dont_write_bytecode is True
    namespace["main"].__globals__["PYTHON"] = tmp_path / "missing"
    assert namespace["main"]() == 5
  finally:
    sys.dont_write_bytecode = previous


def test_entry_broken_venv_does_not_exec_itself(tmp_path, monkeypatch, capsys):
  from pathlib import Path
  import runpy
  import sys
  entry = Path(__file__).resolve().parents[1] / "rotom"
  previous = sys.dont_write_bytecode
  try:
    namespace = runpy.run_path(str(entry))
    root = tmp_path / "checkout"
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("fixture executable")
    python.chmod(0o700)
    namespace["main"].__globals__.update(ROOT=root, PYTHON=python)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "system-prefix"))
    monkeypatch.setattr(sys, "executable", str(python))
    calls = []
    def fake_exec(*args):
      calls.append(args)
      raise OSError("recursive exec forbidden")
    monkeypatch.setattr(namespace["os"], "execv", fake_exec)
    assert namespace["main"]() == 5
    assert calls == []
    assert "rotom_environment_invalid" in capsys.readouterr().err
  finally:
    sys.dont_write_bytecode = previous


@pytest.fixture
def facade_preferences(monkeypatch):
  """仅替代偏好存储，路由测试不打开真实配置。"""
  import sys
  from types import ModuleType, SimpleNamespace
  module = ModuleType("rotom.preferences")
  data = {"schema_version": 1}
  reads, validations, updates = [], [], []
  class PreferenceError(ValueError):
    exit_code = 2
  def get(key, default=None):
    value = data
    for segment in key.split("."):
      if not isinstance(value, dict) or segment not in value:
        return default
      value = value[segment]
    return value
  preferences = SimpleNamespace(data=data, get=get)
  def load_preferences():
    reads.append(True)
    return preferences
  module.load_preferences = load_preferences
  module.validate_reference = lambda key, value: validations.append((key, value))
  module.update_preference = lambda key, value: updates.append((key, value)) or preferences
  module.PreferenceError = PreferenceError
  monkeypatch.setitem(sys.modules, "rotom.preferences", module)
  return SimpleNamespace(data=data, reads=reads, validations=validations, updates=updates, module=module)


@pytest.mark.parametrize("tool,profile", [("dsh", "dsh-default"), ("pi", "pi-base"), ("omp", "omp-default")])
def test_short_run_uses_tool_profile_and_default_machine(monkeypatch, facade_preferences, tool, profile):
  import agentcfg.cli
  seen = []
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 29)
  assert cli.main(["run", tool, "--", "--help"]) == 29
  assert seen[0][0] == ["--machine", "default", "--profile", profile, "run", tool, "--", "--help"]
  assert seen[0][1].scope.profile == profile
  assert seen[0][1].scope.sources["profile"] == "default"


def test_short_run_profile_inference_and_environment_names(monkeypatch, facade_preferences, tmp_path):
  import agentcfg.cli
  seen = []
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 17)
  cwd = str(tmp_path / "space cwd")
  assert cli.main(["run", "--profile", "pi-pro", "--local", "chosen.toml", "--cwd", cwd,
    "--inherit-env", "LANG", "--unset-env", "TERM", "--", "--help", "a b"]) == 17
  assert seen[0][0] == ["--local", "chosen.toml", "--profile", "pi-pro", "run", "pi", "--cwd", cwd,
    "--inherit-env", "LANG", "--unset-env", "TERM", "--", "--help", "a b"]
  assert seen[0][1].scope.sources["agent"] == "profile"


def test_preferences_selected_scope_and_explicit_local_hard_constraint(monkeypatch, facade_preferences):
  import agentcfg.cli
  facade_preferences.data.update(defaults={"agent_machine": "saved-machine"}, run_profiles={"pi": "pi-pro"})
  seen = []
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 0)
  assert cli.main(["run", "pi"]) == 0
  assert seen[-1][0][:4] == ["--machine", "saved-machine", "--profile", "pi-pro"]
  assert cli.main(["run", "pi", "--local", "explicit.toml", "--profile", "pi-base"]) == 0
  assert seen[-1][0][:4] == ["--local", "explicit.toml", "--profile", "pi-base"]
  assert "--machine" not in seen[-1][0]


@pytest.mark.parametrize("argv", [["run", "pi", "--profile", "dsh-default"], ["run", "--profile", "missing-profile"]])
def test_explicit_profile_invalid_or_mismatched_fails_before_backend(monkeypatch, facade_preferences, argv):
  import agentcfg.cli
  monkeypatch.setattr(agentcfg.cli, "main", lambda *args, **kwargs: pytest.fail("invalid target reached backend"))
  assert cli.main(argv) == 2


@pytest.mark.parametrize("namespace,module,key", [("agent", "agentcfg.cli", "agent_machine"),
  ("term", "termcfg.cli", "term_machine"), ("work", "termcfg.work", "work_machine")])
def test_namespace_machine_defaults_remain_independent(monkeypatch, facade_preferences, namespace, module, key):
  import importlib
  facade_preferences.data["defaults"] = {"agent_machine": "agent-scope", "term_machine": "term-scope", "work_machine": "work-scope"}
  argv = {"agent": ["run", "pi"], "term": ["status"], "work": ["config", "check"]}[namespace]
  seen = []
  monkeypatch.setattr(importlib.import_module(module), "main", lambda tokens, *, context=None: seen.append((tokens, context)) or 0)
  assert cli.main([namespace, *argv]) == 0
  assert seen[0][0][:2] == ["--machine", facade_preferences.data["defaults"][key]]
  assert seen[0][1].scope.profile is None


@pytest.mark.parametrize("argv", [["agent", "profiles"], ["agent", "model", "presets"],
  ["agent", "usage", "--help"], ["agent", "lock", "--agent", "omp"]])
def test_scope_free_commands_do_not_load_preferences(monkeypatch, facade_preferences, argv):
  import agentcfg.cli
  seen = []
  def forbidden():
    pytest.fail("scope-free command loaded preferences")
  facade_preferences.module.load_preferences = forbidden
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: seen.append(tokens) or 0)
  assert cli.main(argv) == 0
  assert seen == [argv[1:]]


def test_config_routes_do_not_launch_backend(monkeypatch, facade_preferences, capsys):
  import json
  import agentcfg.cli
  monkeypatch.setattr(agentcfg.cli, "main", lambda *args, **kwargs: pytest.fail("config launched backend"))
  assert cli.main(["config", "show"]) == 0
  assert json.loads(capsys.readouterr().out) == {"schema_version": 1}
  assert cli.main(["config", "set", "run_profiles.pi", "pi-pro"]) == 0
  assert cli.main(["config", "unset", "run_profiles.pi"]) == 0
  assert facade_preferences.updates == [("run_profiles.pi", "pi-pro"), ("run_profiles.pi", None)]


@pytest.mark.parametrize("state,exit_code,reason", [
  ("not-deployed", 4, "实例尚未部署"),
  ("binding-mismatch", 4, "部署绑定与当前选择不兼容"),
  ("package-missing", 5, "当前部署的运行包缺失或损坏"),
  ("pending-update", 17, "运行包声明有待更新"),
])
def test_short_run_preserves_deployed_contract_states(tmp_path, monkeypatch, fake_subprocess,
    prepared_runtime, facade_preferences, capsys, state, exit_code, reason):
  from types import SimpleNamespace
  from agentcfg import commands, deployment, runtime
  from agentcfg.dependencies import read_lock
  from agentcfg.workspace import load_workspace
  from test_runtime import local_file
  local = tmp_path / "fixture.toml"
  local_file(local)
  workspace = load_workspace(local)
  lock = read_lock(workspace.repository)
  from agentcfg.lifecycle import guard
  with guard(workspace):
    pass
  if state != "not-deployed":
    binding = dict(workspace.binding)
    if state == "binding-mismatch":
      binding["profile"] = "other-profile"
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity),
      binding, runtime.record(workspace, lock))
    prepared_runtime(workspace, lock)
  if state == "package-missing":
    monkeypatch.setattr(type(workspace.backend), "status", lambda *args: "missing")
  if state == "pending-update":
    backend = workspace.backend
    monkeypatch.setattr(type(backend), "read_lock", lambda *args, **kwargs: SimpleNamespace(identity="updated-runtime"))
    fake_subprocess.queue(returncode=0, stdout="v24.2.0")
    fake_subprocess.queue(returncode=17)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  assert cli.main(["--no-input", "run", "dsh", "--local", str(local)]) == exit_code
  error = capsys.readouterr().err
  assert reason in error
  assert "--local" in error and "--profile dsh-default" in error
  assert len(fake_subprocess.calls) == (2 if state == "pending-update" else 0)


def test_stale_unselected_preferences_are_not_resolved(monkeypatch, facade_preferences):
  import agentcfg.cli
  facade_preferences.data.update(defaults={"term_machine": "missing-term"}, run_profiles={"dsh": "missing-dsh"})
  monkeypatch.setattr(agentcfg.cli, "main", lambda tokens, *, context=None: 0)
  assert cli.main(["run", "pi"]) == 0
  assert facade_preferences.validations == []


def test_invalid_selected_preference_fails_without_fallback(monkeypatch, facade_preferences):
  import agentcfg.cli
  facade_preferences.data["defaults"] = {"agent_machine": "missing-machine"}
  def invalid(key, value):
    raise facade_preferences.module.PreferenceError()
  facade_preferences.module.validate_reference = invalid
  monkeypatch.setattr(agentcfg.cli, "main", lambda *args, **kwargs: pytest.fail("invalid preference reached backend"))
  assert cli.main(["run", "pi"]) == 2


def test_resume_and_instance_scope_never_use_run_profile_defaults(monkeypatch, facade_preferences):
  facade_preferences.data.update(defaults={"agent_machine": "selected-machine"}, run_profiles={"dsh": "dsh-default"})
  seen = []
  monkeypatch.setattr(cli, "dispatch", lambda invocation, args: seen.append(invocation) or 5)
  from rotom import resume
  provider = resume.CandidateResume(lambda scope: None, lambda target: None)
  provider.dispatch = lambda invocation, args: seen.append(invocation) or 5
  monkeypatch.setattr(resume, "dsh_candidate", lambda: provider)
  assert cli.main(["resume", "dsh", "--session", "session-example"]) == 5
  assert cli.main(["agent", "instances", "list", "--agent", "dsh"]) == 5
  assert all(invocation.context.scope.profile is None for invocation in seen)
  assert all(invocation.context.scope.machine == "selected-machine" for invocation in seen)


@pytest.mark.parametrize("tool,profile", [("dsh", "dsh-default"), ("pi", "pi-base"), ("omp", "omp-default")])
def test_short_run_uses_shared_runtime_executor(monkeypatch, facade_preferences, tmp_path, tool, profile):
  from types import SimpleNamespace
  from pathlib import Path
  from agentcfg import cli as legacy, commands
  seen = []
  def selection(args):
    args.cwd = Path(args.cwd or tmp_path)
  def workspace(args):
    assert args.profile == profile and args.agent == tool
    return SimpleNamespace(profile=args.profile, agent=args.agent)
  def run(workspace, **options):
    seen.append((workspace, options))
    options["runtime_notice"]("current")
    return 31
  monkeypatch.setattr(legacy, "resolve_selection", selection)
  monkeypatch.setattr(commands, "workspace", workspace)
  monkeypatch.setattr(commands.runtime, "run", run)
  assert cli.main(["run", tool, "--cwd", str(tmp_path), "--inherit-env", "LANG", "--", "--help"]) == 31
  assert seen[0][1]["cwd"] == tmp_path
  assert seen[0][1]["arguments"] == ["--help"]
  assert seen[0][1]["inherit_env"] == ["LANG"]


def test_bad_current_lock_does_not_block_saved_deployment(tmp_path, monkeypatch,
    fake_subprocess, prepared_runtime, facade_preferences, capsys):
  from agentcfg import commands, deployment, runtime
  from agentcfg.dependencies import read_lock
  from agentcfg.workspace import load_workspace
  from test_runtime import local_file
  local = tmp_path / "fixture.toml"
  local_file(local)
  workspace = load_workspace(local)
  lock = read_lock(workspace.repository)
  deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity),
    workspace.binding, runtime.record(workspace, lock))
  prepared_runtime(workspace, lock)
  def invalid_lock(*args):
    raise ValueError("synthetic private detail")
  monkeypatch.setattr(type(workspace.backend), "read_lock", invalid_lock)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=21)
  assert cli.main(["run", "dsh", "--local", str(local)]) == 21
  error = capsys.readouterr().err
  assert "更新状态无法核实" in error and "synthetic private detail" not in error
  assert "rotom agent --local" in error and "--profile dsh-default plan" in error
  assert len(fake_subprocess.calls) == 2


def test_static_advice_uses_typed_scope_without_native_tail():
  import shlex
  from rotom.context import InvocationContext, Scope, TypedInvocation
  invocation = TypedInvocation(InvocationContext(("run",), scope=Scope(local="literal path.toml", profile="pi-pro")),
    ("run", "pi"), ("--help", "$(untrusted)"))
  assert shlex.split(shlex.join(invocation.advice_tokens(("agent", "plan")))) == [
    "rotom", "agent", "--local", "literal path.toml", "--profile", "pi-pro", "plan"]


def test_work_focus_keeps_binding_cwd_and_never_prepares_or_injects(tmp_path, monkeypatch, facade_preferences):
  import os
  from copy import deepcopy
  from termcfg import work, work_config
  from termcfg.work_state import WorkState
  from test_work_cli import native_cli, invoke
  settings, client, starts = native_cli(tmp_path, monkeypatch)
  assert invoke(settings, "named", "add", "--id", "case-a", "--title", "Case", "--template", "dev") == 0
  bootstrap = client.request("workspace.create", {"cwd": os.environ["HOME"], "label": "Native", "focus": False, "env": {}})
  monkeypatch.setenv("HERDR_PANE_ID", bootstrap["root_pane"]["pane_id"])
  monkeypatch.setenv("HERDR_SOCKET_PATH", client.socket_path)
  assert invoke(settings, "named", "enter", "case-a") == 0
  pane = next(item for item in client.panes.values() if item.get("tokens", {}).get("rw2_type") == "shell")
  monkeypatch.setenv("HERDR_PANE_ID", pane["pane_id"])
  with WorkState(client.socket_path, client.identity) as state:
    before = deepcopy(work.current_binding_v2(client, state, pane["pane_id"]))
  calls = dict(client.call_counts)
  offset = len(client.requests)
  later = tmp_path / "later-cwd"
  later.mkdir()
  monkeypatch.chdir(later)
  facade_preferences.data.update(defaults={"work_machine": "unselected-machine"}, run_profiles={"pi": "pi-pro"})
  monkeypatch.setattr(work_config, "prepare_launch", lambda *a, **k: pytest.fail("focus prepared a launcher"))
  assert cli.main(["work", "--local", str(settings.local_path), "open", "shell"]) == 0
  with WorkState(client.socket_path, client.identity) as state:
    assert work.current_binding_v2(client, state, pane["pane_id"]) == before
  for method in ("workspace.create", "tab.create", "pane.create"):
    assert client.call_counts[method] == calls.get(method, 0)
  assert not any("send" in method or "input" in method for method, _ in client.requests[offset:])
  assert not any(starts)


def test_current_lock_observation_releases_lease_before_runtime_entry(monkeypatch, facade_preferences, tmp_path):
  from contextlib import contextmanager
  from pathlib import Path
  from types import SimpleNamespace
  from agentcfg import cli as legacy, commands
  events = []
  active = []
  @contextmanager
  def publication_reader():
    events.append("reader-enter")
    active.append(True)
    try:
      yield
    finally:
      active.pop()
      events.append("reader-exit")
  class Backend:
    def read_lock(self, repository):
      with publication_reader():
        return SimpleNamespace(identity="synthetic-snapshot")
  workspace = SimpleNamespace(profile="pi-base", agent="pi", repository=tmp_path, backend=Backend())
  def selection(args):
    args.cwd = Path(tmp_path)
  def run(workspace, **options):
    assert active == []
    assert options["observed_identity"] == "synthetic-snapshot"
    events.append("runtime-entry")
    options["runtime_notice"]("current")
    assert events == ["reader-enter", "reader-exit", "runtime-entry"]
    return 0
  monkeypatch.setattr(legacy, "resolve_selection", selection)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  monkeypatch.setattr(commands.runtime, "run", run)
  assert cli.main(["run", "pi"]) == 0


def test_management_run_keeps_machine_profile_while_short_run_uses_tool_preference(tmp_path, monkeypatch, facade_preferences):
  from agentcfg import cli as legacy
  local = tmp_path / "fixture.toml"
  local.write_text('schema_version = 1\n[machine]\nid = "fixture"\ndefault_profile = "pi-base"\n')
  local.chmod(0o600)
  facade_preferences.data["run_profiles"] = {"pi": "pi-pro"}
  seen = []
  monkeypatch.setattr(legacy, "dispatch", lambda args: seen.append(args) or 17)
  assert cli.main(["agent", "--local", str(local), "run", "pi", "--", "--help"]) == 17
  assert seen[-1].profile == "pi-base" and seen[-1].passthrough == ["--help"]
  assert cli.main(["run", "pi", "--local", str(local), "--", "--help"]) == 17
  assert seen[-1].profile == "pi-pro" and seen[-1].passthrough == ["--help"]


def test_legacy_run_without_context_never_reads_current_lock(monkeypatch, tmp_path):
  from types import SimpleNamespace
  from agentcfg import commands
  seen = []
  monkeypatch.setattr(commands, "workspace", lambda args: SimpleNamespace())
  monkeypatch.setattr(commands.runtime, "current_identity_snapshot", lambda *a: pytest.fail("legacy run read current lock"))
  def run(workspace, **options):
    seen.append(options)
    return 0
  monkeypatch.setattr(commands.runtime, "run", run)
  assert commands.cmd_run(SimpleNamespace(cwd=tmp_path, passthrough=[])) == 0
  assert "runtime_notice" not in seen[0] and "observed_identity" not in seen[0]
