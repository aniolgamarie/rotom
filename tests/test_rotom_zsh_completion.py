"""只审查静态zsh来源；不启动shell、launcher或第三方宿主。"""
import re
import shlex
from pathlib import Path

from rotom import cli


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "terminals/zsh/_rotom"
ZSHRC = ROOT / "terminals/zsh/zshrc.zsh"


def frontend():
  assert FRONTEND.is_file(), "需要受管的静态_rotom来源"
  return FRONTEND.read_text()


def table(source, name):
  matched = re.search(r"(?ms)^local -A " + name + r"=\(\n(.*?)^\)", source)
  assert matched, "需要明确可审计的静态命令/选项表"
  values = shlex.split(matched.group(1), comments=True)
  assert len(values) % 2 == 0
  return dict(zip(values[::2], values[1::2]))


def parser_nodes(parser, path=()):
  yield path, parser
  sub = cli._subparsers(parser)
  if sub:
    for name, child in sub.choices.items():
      if name != "_complete":
        yield from parser_nodes(child, (*path, name))


def test_static_command_and_option_tables_match_registered_parser():
  source = frontend()
  commands = table(source, "_rotom_commands")
  options = table(source, "_rotom_options")
  enums = table(source, "_rotom_enums")
  expected_enums = {}
  expected_flags = set()
  expected_value_options = set()
  for path, parser in parser_nodes(cli.build_parser()):
    key = " ".join(path) or "_root"
    sub = cli._subparsers(parser)
    expected = set(sub.choices) - {"_complete"} if sub else set()
    assert set(commands.get(key, "").split()) == expected
    expected_options = {flag for action in parser._actions for flag in action.option_strings}
    assert set(options[key].split()) == expected_options
    expected_flags.update(expected_options)
    for action in parser._actions:
      if action.nargs != 0:
        expected_value_options.update(action.option_strings)
      if action.choices is not None:
        for flag in action.option_strings:
          expected_enums[key + "|" + flag] = " ".join(str(value) for value in action.choices)
  assert enums == expected_enums
  for name, expected in (("_rotom_flags", expected_flags), ("_rotom_value_options", expected_value_options)):
    array = re.search(r"(?m)^local -a " + name + r"=\(([^\n]*)\)$", source)
    assert array and set(shlex.split(array.group(1))) == expected
  leaves = re.search(r"(?ms)^local -a _rotom_leaves=\(\n(.*?)^\)", source)
  assert leaves
  assert set(shlex.split(leaves.group(1))) == {" ".join(path) for path in cli.COMMANDS if path != ("_complete",)}


def test_frontend_only_passes_literal_argv_and_consumes_nul_values():
  source = frontend()
  assert source.startswith("#compdef rotom\n")
  assert 'command rotom _complete "$@" 2>/dev/null' in source
  assert 'ids=("${(@0)raw}")' in source
  assert 'compadd -a ids' in source
  assert "$'\\0'" in source
  assert re.search(r"(?m)^\s*(?:eval|source|exec)\b", source) is None
  assert "${(e)" not in source and "${(z)" not in source
  assert "load_preferences" not in source and "default_profile" not in source
  assert "read -" not in source and "_files" not in source
  # path/options/commands/status是zsh特殊参数，不得作一般临时变量覆盖。
  assert re.search(r"(?m)^local(?: -[a-zA-Z]+)? (?:path|options|commands|status)(?:[ =]|$)", source) is None


def test_native_boundaries_are_checked_before_dynamic_query():
  source = frontend()
  boundary = source.index('[[ "$token" == -- ]] && return 1')
  opaque = source.index('[[ "$_rotom_path" == "agent usage" ]] && return 1')
  query = source.index('_rotom_ids "${query[@]}"')
  assert boundary < query and opaque < query
  assert 'for (( index=2; index<CURRENT; index++ )); do' in source


def test_private_queries_require_explicit_scope_without_defaults():
  source = frontend()
  assert '[[ -n "$machine" || -n "$local_path" ]] || return 1' in source
  assert '[[ -n "$profile" ]] || return 1' in source
  assert '[[ -n "$tool" ]] || return 1' in source
  assert 'query+=(--machine "$machine")' in source
  assert 'query+=(--local "$local_path")' in source
  assert 'query+=(--profile "$profile")' in source
  assert 'query+=(--command "$_rotom_path")' in source
  assert 'query+=(--tool "$tool")' in source
  assert '(( ${_rotom_option_words[(Ie)$option]} )) || return 1' in source
  assert '(( ${_rotom_option_words[(Ie)$value_option]} )) || return 1' in source
  assert 'machine=default' not in source and 'profile=pi-base' not in source
  assert 'work-type' in source and 'work-template' in source and 'work-named' in source


def test_fpath_and_path_are_deduplicated_before_any_compinit_or_plugin():
  source = ZSHRC.read_text()
  assert 'typeset -U path' in source
  assert 'typeset -U fpath' in source
  marker = 'fpath=("$HOME/.local/share/rotom/zsh/site-functions" "${fpath[@]}")'
  inserted = source.index(marker)
  for later in ('source "$_termcfg_zsh_plugins/zinit/zinit.zsh"', 'source "$ZSH/oh-my-zsh.sh"', 'autoload -Uz compinit && compinit'):
    assert inserted < source.index(later)
  assert source.index('if [[ "$HOME" == /* ]]') < inserted
  assert '*":$HOME/.local/bin:"*) ;;' in source


def test_public_sources_describe_static_completion_ownership():
  source = (ROOT / "terminals/SOURCES.md").read_text()
  assert "zsh/_rotom" in source and ".local/share/rotom/zsh/site-functions/_rotom" in source
  assert "0644" in source and "NUL" in source


def test_tool_position_candidates_follow_real_optional_tool_parsers():
  source = frontend()
  branch = re.search(r'(?m)^\s+([^\n]+)\) \(\( \$\{#positions\} == 0 \)\) && kind=tool ;;$', source)
  assert branch
  assert set(shlex.split(branch.group(1).replace("|", " "))) == {"run", "resume", "agent run"}
  leaves = dict(cli.parser_leaves(cli.build_parser()))
  for path, name in ((("run",), "tool"), (("agent", "run"), "agent")):
    _, actions = leaves[path]
    action = next(action for action in actions if action.dest == name)
    assert action.nargs == "?" and set(action.choices) == {"dsh", "pi", "omp"}
  parser = cli.build_parser()
  assert parser.parse_args(["run"]).tool is None
  selected = parser.parse_args(["agent", "--profile", "pi-base", "run"])
  assert selected.agent is None and selected.profile == "pi-base"


def test_agent_run_native_boundary_and_no_run_profile_preference_injection():
  source = frontend()
  condition = re.search(r'if \[\[ "\$_rotom_path" == \(([^)]+)\) && \$\{#positions\} -eq 0', source)
  assert condition
  assert set(shlex.split(condition.group(1).replace("|", " "))) == {"run", "resume", "agent run"}
  # 前端不读取或注入根run的profile偏好；只有用户输入的profile可进入scope查询。
  assert 'profile=""' in source and "run_profiles" not in source
  assert "load_preferences" not in source
  assert 'profile="$value"' in source and 'query+=(--profile "$profile")' in source
  # --后包含--machine/--profile等字词也不允许进入管理参数捕获。
  loop = source.index('for (( index=2; index<CURRENT; index++ )); do')
  guard = source.index('[[ "$token" == -- ]] && return 1', loop)
  capture = source.index('if [[ -z "$need" && "$token" == -* ]]; then', loop)
  assert guard < capture
