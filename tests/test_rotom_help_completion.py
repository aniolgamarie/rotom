"""静态帮助与允许来源补全；不启动宿主、不读取真实凭据。"""
import os
from pathlib import Path

import pytest

# 先绑定正常后端引用，避免惰性导入把临时workspace哨兵留给后续用例。
from agentcfg import commands


def test_profile_completion_validates_sources_without_loading_unrelated_catalog(monkeypatch, capsys):
  from agentcfg import workspace
  from rotom import cli
  def forbidden(*args, **kwargs):
    pytest.fail("profile IDs do not require provider/model/other-tool catalogs")
  monkeypatch.setattr(workspace, "load_public_catalog", forbidden)
  assert cli.main(["_complete", "--kind", "profile", "--tool", "dsh"]) == 0
  assert "dsh-default\0" in capsys.readouterr().out


def test_profile_completion_still_rejects_unknown_source_fields(tmp_path, monkeypatch, capsys):
  from rotom import cli, completion
  root = tmp_path / "public-catalog"
  (root / "profiles").mkdir(parents=True)
  (root / "schemas").mkdir()
  (root / "profiles/example.toml").write_text('schema_version=1\nid="example"\nagent="dsh"\nunknown=true\n')
  monkeypatch.setattr(completion, "ROOT", root)
  assert cli.main(["_complete", "--kind", "profile", "--tool", "dsh"]) == 2
  assert capsys.readouterr().out == ""


def test_profile_completion_checks_all_sources_and_fresh_options_on_each_request(tmp_path, monkeypatch, capsys):
  from rotom import cli, completion
  root = tmp_path / "public-profile-sources"
  (root / "profiles").mkdir(parents=True)
  (root / "schemas").mkdir()
  for number in range(100):
    identifier = f"public-{number:03}"
    (root / "profiles" / (identifier + ".toml")).write_text(
      f'schema_version=1\nid="{identifier}"\nagent="dsh"\n[agent_options]\nterminal_images=false\n')
  monkeypatch.setattr(completion, "ROOT", root)
  assert cli.main(["_complete", "--kind", "profile", "--tool", "dsh"]) == 0
  assert len([value for value in capsys.readouterr().out.split("\0") if value]) == 100
  # 不属于所选工具的坏公开来源也必须拒绝；前次请求不能缓存掉原文件变化。
  (root / "profiles/public-099.toml").write_text(
    'schema_version=1\nid="public-099"\nagent="dsh"\n[agent_options]\nterminal_images="wrong"\n')
  assert cli.main(["_complete", "--kind", "profile", "--tool", "pi"]) == 2
  assert capsys.readouterr().out == ""

from rotom import cli


def nodes(parser, path=()):
  yield path
  sub = cli._subparsers(parser)
  if sub is not None:
    for name, child in sub.choices.items():
      yield from nodes(child, (*path, name))


HELP_PATHS = [path for path in nodes(cli.build_parser()) if path != ("agent", "usage")]


def forbid(*args, **kwargs):
  pytest.fail("forbidden business, secret, native, or input access")


@pytest.mark.parametrize("path", HELP_PATHS)
def test_every_level_help_has_complete_static_contract(path, monkeypatch, capsys):
  from rotom import preferences
  from agentcfg import config, secrets, workspace
  from termcfg import work_config
  monkeypatch.setattr(preferences, "load_preferences", forbid)
  monkeypatch.setattr(config, "read_local_document", forbid)
  monkeypatch.setattr(workspace, "load_workspace", forbid)
  monkeypatch.setattr(work_config, "read_settings", forbid)
  monkeypatch.setattr(secrets.SecretStore, "resolve", forbid)
  assert cli.main([*path, "--help"]) == 0
  output = capsys.readouterr().out
  for label in ("用途", "参数位置", "默认优先级", "输入条件", "副作用", "最短示例", "显式范围示例"):
    assert label in output


NAMESPACE_PATHS = sorted({path[:length] for path in cli.COMMANDS for length in range(len(path))})


@pytest.mark.parametrize("path", NAMESPACE_PATHS)
def test_namespace_examples_are_distinct_registered_operations(path, monkeypatch, capsys):
  import shlex
  from agentcfg import config, workspace
  monkeypatch.setattr(config, "read_local_document", forbid)
  monkeypatch.setattr(workspace, "load_workspace", forbid)
  assert cli.main([*path, "--help"]) == 0
  output = capsys.readouterr().out
  examples = [next(line.split("：", 1)[1] for line in output.splitlines() if line.startswith(label))
    for label in ("最短示例：", "显式范围示例：")]
  assert examples[0] != examples[1]
  for example in examples:
    tokens = shlex.split(example)
    assert tokens.pop(0) == "rotom"
    assert "--help" not in tokens and "-h" not in tokens
    management, _ = cli._opaque_tail(tokens)
    cli._duplicates(management)
    parsed = cli.build_parser().parse_args(management)
    assert parsed._command_path[:len(path)] == path
    assert parsed._command_path in cli.COMMANDS
    cli.validate_explicit_conditions(parsed)


@pytest.mark.parametrize("prefix", [
  ["resume", "pi", "--stopped", "--batch", "a" * 32, "--all", "--new-tab"],
  ["agent", "--profile", "pi-base", "maintenance", "restore", "--batch", "a" * 32,
    "--run", "b" * 32, "--original"],
])
@pytest.mark.parametrize("seconds", ["1", "30", "300"])
def test_location_wait_budget_has_declared_range(prefix, seconds):
  args = cli.build_parser().parse_args([*prefix, "--wait-seconds", seconds])
  cli.validate_explicit_conditions(args)
  assert args.wait_seconds == int(seconds)


@pytest.mark.parametrize("seconds", ["0", "301", "-1", "1.5", "unknown"])
def test_invalid_location_wait_budget_rejected_by_parser(seconds):
  with pytest.raises(SystemExit) as error:
    cli.build_parser().parse_args(["resume", "--stopped", "--new-tab", "--wait-seconds", seconds])
  assert error.value.code == 2


@pytest.mark.parametrize("tokens", [
  ["resume", "dsh", "--session", "example", "--here"],
  ["resume", "--stopped", "--list"],
  ["resume", "--stopped", "--here"],
  ["agent", "maintenance", "restore", "--batch", "a" * 32, "--here"],
])
def test_wait_budget_cannot_be_silently_ignored(tokens, monkeypatch):
  from agentcfg import workspace
  monkeypatch.setattr(workspace, "load_workspace", forbid)
  assert cli.main(["--no-input", *tokens, "--wait-seconds", "30"]) == 2


def test_effect_metadata_is_specific_to_actual_behavior():
  for definition in cli.COMMANDS.values():
    assert all("existing-backend-effects" not in effect for effect in definition.effects)
  assert any("cache" in effect for effect in cli.COMMANDS[("agent", "render")].effects)
  assert any("network" in effect for effect in cli.COMMANDS[("agent", "sync")].effects)
  assert any("native" in effect for effect in cli.COMMANDS[("run",)].effects)


def candidates(capsys):
  output = capsys.readouterr().out
  assert not output or output.endswith("\0")
  return output.split("\0")[:-1] if output else []


@pytest.mark.parametrize("kind,extra,expected", [
  ("tool", [], {"dsh", "pi", "omp"}),
  ("profile", ["--tool", "pi"], {"pi-base", "pi-pro"}),
  ("preset", [], {"kimi-code", "glm-code", "deepseek"}),
  ("component", [], {"zsh", "tmux", "herdr"}),
  ("preference-key", [], {"defaults.agent_machine", "defaults.term_machine", "defaults.work_machine", "run_profiles.dsh", "run_profiles.pi", "run_profiles.omp"}),
])
def test_public_candidates_are_nul_ids_without_preferences(kind, extra, expected, monkeypatch, capsys):
  from rotom import preferences
  monkeypatch.setattr(preferences, "load_preferences", forbid)
  assert cli.main(["_complete", "--kind", kind, *extra]) == 0
  assert set(candidates(capsys)) == expected


@pytest.mark.parametrize("query", [[], ["--kind", "unknown"], ["--kind", "provider"],
  ["--kind", "work-type"], ["--kind", "session"],
  ["--kind", "machine", "--namespace", "agent", "--kind", "tool"],
  ["--kind", "tool", "--command", "run; bad"],
  ["--kind", "tool", "--namespace", "term"],
])
def test_invalid_completion_queries_never_prompt_or_emit(query, monkeypatch, capsys):
  monkeypatch.setattr(cli.InputGateway, "text", forbid)
  assert cli.main(["_complete", *query]) == 2
  assert capsys.readouterr().out == ""


def private_machine(namespace, name, body):
  parent = Path(os.environ["XDG_CONFIG_HOME"]) / namespace / "machines"
  parent.mkdir(parents=True, mode=0o700, exist_ok=True)
  path = parent / (name + ".toml")
  path.write_text(body)
  path.chmod(0o600)
  return path


def test_machine_candidates_only_stat_names_and_use_namespace(monkeypatch, capsys):
  private_machine("agentcfg", "agent-one", "not valid TOML")
  private_machine("termcfg", "term-one", "private body must not open")
  from agentcfg import paths
  monkeypatch.setattr(paths, "read_private_file", forbid)
  assert cli.main(["_complete", "--kind", "machine", "--namespace", "term"]) == 0
  assert candidates(capsys) == ["term-one"]
  assert cli.main(["_complete", "--kind", "machine", "--namespace", "work"]) == 0
  assert candidates(capsys) == ["agent-one"]


@pytest.mark.parametrize("damage", ["link", "permission", "hardlink"])
def test_unsafe_machine_candidates_fail_atomically(damage, tmp_path, capsys):
  first = private_machine("agentcfg", "a-valid", "")
  last = private_machine("agentcfg", "z-unsafe", "")
  if damage == "link":
    last.unlink()
    last.symlink_to(first)
  elif damage == "permission":
    last.chmod(0o644)
  else:
    last.unlink()
    last.hardlink_to(first)
  assert cli.main(["_complete", "--kind", "machine", "--namespace", "agent"]) != 0
  assert capsys.readouterr().out == ""


def test_provider_projection_never_resolves_secrets_or_missing_urls(monkeypatch, capsys):
  from agentcfg import cli as legacy, secrets, workspace
  assert legacy.main(["init-local", "--profile", "omp-kernel"]) == 0
  capsys.readouterr()
  monkeypatch.setattr(secrets.SecretStore, "resolve", forbid)
  monkeypatch.setattr(workspace, "load_workspace", forbid)
  assert cli.main(["_complete", "--kind", "provider", "--machine", "default", "--profile", "omp-kernel",
    "--command", "agent model url"]) == 0
  result = candidates(capsys)
  assert "kimi_tf" in result and "cursor" not in result
  assert all("secret:" not in value and "https:" not in value and "/" not in value for value in result)


def test_work_projection_does_not_visit_project_paths_or_live_state(tmp_path, monkeypatch, capsys):
  from termcfg import work_config, work_projects
  path = private_machine("agentcfg", "workstation", 'schema_version=1\n[machine]\nid="workstation"\n'
    '[machine.work]\nmodel="structured-v1"\nherdr_binary="missing-herdr"\nsession="trial"\ninclude_rotom=false\n'
    '[[machine.work.sources]]\nid="projects"\npath="/unreadable-source"\nmode="git"\ntemplate="dev"\n'
    '[[machine.work.workspaces]]\nkind="named"\nid="case-a"\ntitle="Case"\ntemplate="dev"\nstart_path="/unreadable-start"\n'
    '[machine.work.templates.dev]\norder=["shell","agent"]\ninitial="shell"\n'
    '[machine.work.templates.dev.tab_types.shell]\nlabel="Shell"\nlauncher="shell"\n'
    '[machine.work.templates.dev.tab_types.agent]\nlabel="Pi"\nlauncher="pi"\n')
  monkeypatch.setattr(work_config, "read_settings", forbid)
  monkeypatch.setattr(work_projects, "discover", forbid)
  for kind, expected in (("work-type", {"shell", "agent"}), ("work-template", {"dev"}),
      ("work-source", {"projects"}), ("work-named", {"case-a"})):
    assert cli.main(["_complete", "--kind", kind, "--local", str(path)]) == 0
    assert set(candidates(capsys)) == expected


@pytest.mark.parametrize("body", ['schema_version=1\nschema_version=1\n', 'schema_version=1\nunknown=true\n[machine]\nid="fixture"\n'])
def test_bad_selected_document_is_nonzero_without_partial_candidates(body, capsys):
  private_machine("agentcfg", "fixture", body)
  assert cli.main(["_complete", "--kind", "provider", "--machine", "fixture", "--profile", "pi-base"]) != 0
  assert capsys.readouterr().out == ""


def test_missing_session_machines_are_empty_without_creation(tmp_path, sentinel_factory, capsys):
  before = sentinel_factory(tmp_path)
  assert cli.main(["_complete", "--kind", "session", "--machine", "missing", "--tool", "dsh"]) == 0
  assert capsys.readouterr().out == ""
  assert cli.main(["_complete", "--kind", "provider", "--machine", "missing", "--profile", "pi-base"]) == 0
  assert capsys.readouterr().out == ""
  before.assert_unchanged()


def test_completion_after_separator_is_empty_and_no_query(capsys):
  assert cli.main(["_complete", "--kind", "tool", "--", "--help"]) == 0
  assert capsys.readouterr().out == ""


def test_provider_credentials_are_neither_loaded_nor_resolved(monkeypatch, capsys):
  from agentcfg import adapter, cli as legacy, config, paths, secret_files, secrets
  assert legacy.main(["init-local", "--profile", "pi-base"]) == 0
  capsys.readouterr()
  selected = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines/default.toml"
  original = paths.read_private_file
  reads = []
  def selected_only(path, *args, **kwargs):
    assert Path(path) == selected
    reads.append(path)
    return original(path, *args, **kwargs)
  monkeypatch.setattr(paths, "read_private_file", selected_only)
  monkeypatch.setattr(config, "load_secrets", forbid)
  monkeypatch.setattr(config, "resolve_config", forbid)
  monkeypatch.setattr(adapter.SecretRef, "__post_init__", forbid)
  monkeypatch.setattr(secret_files, "read_private_file", forbid)
  monkeypatch.setattr(secrets.SecretStore, "resolve", forbid)
  assert cli.main(["_complete", "--kind", "provider", "--machine", "default", "--profile", "pi-base"]) == 0
  assert candidates(capsys) and reads


@pytest.mark.parametrize("damage", ["link", "permission", "hardlink", "parent-link"])
def test_selected_machine_unsafe_sources_fail_without_output(damage, tmp_path, capsys):
  path = private_machine("agentcfg", "fixture", 'schema_version=1\n[machine]\nid="fixture"\n')
  if damage == "permission":
    path.chmod(0o644)
  elif damage == "parent-link":
    original = path.parent
    target = original.with_name("moved")
    original.rename(target)
    original.symlink_to(target, target_is_directory=True)
  else:
    target = path.with_name("other.toml")
    path.rename(target)
    if damage == "link":
      path.symlink_to(target)
    else:
      path.hardlink_to(target)
  assert cli.main(["_complete", "--kind", "provider", "--local", str(path), "--profile", "pi-base"]) == 4
  assert capsys.readouterr().out == ""


def test_public_source_link_rejected_before_public_parser(tmp_path, monkeypatch, capsys):
  from rotom import completion
  from agentcfg import workspace
  directory = tmp_path / "catalog" / "profiles"
  directory.mkdir(parents=True)
  target = tmp_path / "not-public.toml"
  target.write_text("private sentinel")
  (directory / "bad.toml").symlink_to(target)
  monkeypatch.setattr(completion, "ROOT", directory.parent)
  monkeypatch.setattr(workspace, "load_public_catalog", forbid)
  assert cli.main(["_complete", "--kind", "profile"]) == 4
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("command,expected", [("term lock", {"zsh", "tmux"}), ("term apply", {"zsh", "tmux", "herdr"})])
def test_component_candidates_follow_registered_command(command, expected, capsys):
  assert cli.main(["_complete", "--kind", "component", "--command", command]) == 0
  assert set(candidates(capsys)) == expected


def test_valid_query_read_failure_has_static_error_and_empty_stdout(monkeypatch, capsys):
  from rotom import completion
  def denied(*args):
    raise PermissionError("sensitive fixture exception")
  monkeypatch.setattr(completion, "_machine_ids", denied)
  assert cli.main(["_complete", "--kind", "machine", "--namespace", "agent"]) != 0
  captured = capsys.readouterr()
  assert captured.out == "" and captured.err == "rotom: 补全查询不可用\n"


def test_completion_queries_do_not_write_cache_or_invoke_processes(tmp_path, monkeypatch, sentinel_factory, capsys):
  from agentcfg import paths, workspace
  import subprocess
  snapshot = sentinel_factory(tmp_path)
  monkeypatch.setattr(subprocess, "run", forbid)
  monkeypatch.setattr(subprocess, "Popen", forbid)
  monkeypatch.setattr(workspace, "load_workspace", forbid)
  read_private_file = paths.read_private_file
  monkeypatch.setattr(paths, "read_private_file", forbid)
  assert cli.main(["_complete", "--kind", "tool"]) == 0
  assert candidates(capsys) == ["dsh", "omp", "pi"]
  monkeypatch.setattr(paths, "read_private_file", read_private_file)
  assert cli.main(["_complete", "--kind", "session", "--machine", "fixture", "--tool", "pi"]) == 0
  assert capsys.readouterr().out == ""
  snapshot.assert_unchanged()


def test_legacy_help_contract_remains_static(monkeypatch):
  from agentcfg import cli as agent, config, secrets
  from termcfg import cli as term
  monkeypatch.setattr(config, "read_local_document", forbid)
  monkeypatch.setattr(secrets.SecretStore, "resolve", forbid)
  for parser in (agent.build_parser(), term.build_parser()):
    output = parser.format_help()
    assert "默认优先级" in output and "输入条件" in output


@pytest.mark.parametrize("query", [
  ["--kind", "profile", "--command", "config show"],
  ["--kind", "preset", "--command", "agent run"],
  ["--kind", "component", "--command", "work open"],
  ["--kind", "provider", "--machine", "fixture", "--profile", "pi-base", "--tool", "omp"],
  ["--kind", "provider", "--machine", "fixture", "--local", "other", "--profile", "pi-base"],
])
def test_completion_rejects_inapplicable_scope_and_command_combinations(query, capsys):
  assert cli.main(["_complete", *query]) == 2
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("values", [["a-valid", "https://example.invalid"], ["valid", "secret:fixture"], ["valid", "line\nbreak"]])
def test_all_candidates_validated_before_first_nul(values, monkeypatch, capsys):
  from rotom import completion
  monkeypatch.setattr(completion, "collect", lambda args: values)
  assert cli.main(["_complete", "--kind", "tool"]) == 2
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("argv,tail", [
  (["agent", "usage", "--help"], ["usage", "--help"]),
  (["run", "pi", "--", "--help"], ["run", "pi", "--", "--help"]),
])
def test_native_help_is_forwarded_without_management_help(argv, tail, monkeypatch, capsys):
  from agentcfg import cli as agent
  seen = []
  monkeypatch.setattr(agent, "main", lambda tokens, *, context=None: seen.append(tokens) or 27)
  assert cli.main(argv) == 27
  assert seen[0][-len(tail):] == tail
  assert capsys.readouterr().out == ""


def test_static_help_disables_bytecode_and_does_not_create_cache(monkeypatch, sentinel_factory, capsys):
  import sys
  from rotom import preferences
  from agentcfg import paths
  snapshot = sentinel_factory(Path(os.environ["HOME"]))
  before = sorted(Path(cli.__file__).parent.rglob("*.pyc"))
  monkeypatch.setattr(preferences, "load_preferences", forbid)
  monkeypatch.setattr(paths, "read_private_file", forbid)
  assert sys.dont_write_bytecode
  assert cli.main(["_complete", "--help"]) == 0
  assert capsys.readouterr().out
  assert sorted(Path(cli.__file__).parent.rglob("*.pyc")) == before
  snapshot.assert_unchanged()


@pytest.mark.parametrize("flags", [[], ["--no-input"], ["--interactive"]])
@pytest.mark.parametrize("tty_bits", range(8))
def test_completion_is_strict_and_independent_of_input_policy(flags, tty_bits, monkeypatch, capsys):
  import io
  import sys
  class Stream(io.StringIO):
    def __init__(self, tty):
      super().__init__()
      self.tty = tty
    def isatty(self):
      return self.tty
    def readline(self, *args):
      pytest.fail("completion must never read input")
  monkeypatch.setattr(cli, "InputGateway", forbid)
  monkeypatch.setattr(sys, "stdin", Stream(bool(tty_bits & 1)))
  # 输出仍由capsys收集，只改变TTY属性以覆盖三流组合。
  monkeypatch.setattr(sys.stdout, "isatty", lambda: bool(tty_bits & 2))
  monkeypatch.setattr(sys.stderr, "isatty", lambda: bool(tty_bits & 4))
  assert cli.main([*flags, "_complete", "--kind", "tool"]) == 0
  assert candidates(capsys) == ["dsh", "omp", "pi"]
  assert cli.main([*flags, "_complete"]) == 2
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("path", list(cli.COMMANDS))
def test_documented_leaf_examples_match_real_registered_syntax(path):
  import shlex
  definition = cli.COMMANDS[path]
  for example in definition.examples:
    tokens = shlex.split(example)
    assert tokens.pop(0) == "rotom"
    management, _ = cli._opaque_tail(tokens)
    cli._duplicates(management)
    parsed = cli.build_parser().parse_args(management)
    assert parsed._command_path == path
    cli.validate_explicit_conditions(parsed)


def test_completion_help_describes_admitted_readonly_sessions(capsys):
  assert cli.main(["_complete", "--help"]) == 0
  output = capsys.readouterr().out
  assert "当前仅空结果" not in output
  assert "session" in output and "tool" in output
  assert "machine/local" in output and ("索引" in output or "元数据" in output)
