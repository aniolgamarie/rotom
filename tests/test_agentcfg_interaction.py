"""首批 CLI 交互契约：纯解析与合成 payload，不依赖私人状态。"""

from contextlib import contextmanager
from copy import deepcopy
import io
import json
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

import pytest

from agentcfg import cli, presentation


CANARY = "synthetic-private-value-$(never-run)-凭据"


@contextmanager
def no_state(monkeypatch):
  """显式禁止帮助和展示层触碰配置、路径元数据或输入。"""
  def forbidden(*args, **kwargs):
    raise AssertionError("导航与展示不得访问状态或输入")
  with monkeypatch.context() as patch:
    for name in ("stat", "lstat", "exists", "is_file", "open", "read_text", "read_bytes"):
      patch.setattr(Path, name, forbidden)
    patch.setattr("builtins.open", forbidden)
    patch.setattr("builtins.input", forbidden)
    patch.setattr(cli, "resolve_selection", forbidden)
    patch.setattr(cli, "dispatch", forbidden)
    yield


@pytest.mark.parametrize("argv", [[], ["--machine", CANARY], ["--local", CANARY], ["--profile", "omp-default"]])
def test_bare_navigation_is_short_static_and_state_free(argv, monkeypatch, capsys):
  with no_state(monkeypatch):
    assert cli.main(argv) == 2
  result = capsys.readouterr()
  assert not result.err
  assert CANARY not in result.out
  assert len(result.out.splitlines()) <= 16
  for word in ("首次", "日常", "诊断", "恢复", "init-local", "setup", "run", "--help"):
    assert word in result.out


@pytest.mark.parametrize("path, fragments", [
  ([], ("首次", "公共选择", "命令")),
  (["init-local"], ("--profile", "默认", "子命令后")),
  (["setup"], ("联网", "重新校验", "漂移")),
  (["run"], ("--inherit-env", "--unset-env", "--profile omp-default", "不切换")),
  (["doctor"], ("--environment", "--input", "--live", "诊断文件")),
  (["project"], ("仅 Pi", "OpenSpec")),
  (["project", "init"], ("仅 Pi", "--path", "--profile pi-default")),
  (["model"], ("key", "url", "子命令")),
  (["capture"], ("提案", "不是恢复")),
  (["recover"], ("默认只生成", "同时提供 --stop 与 --expect-plan")),
])
def test_layered_help_keeps_current_capabilities(path, fragments, monkeypatch, capsys):
  with no_state(monkeypatch):
    with pytest.raises(SystemExit) as error:
      cli.main([*path, "--help"])
  assert error.value.code == 0
  result = capsys.readouterr()
  assert not result.err
  for fragment in fragments:
    assert fragment in result.out
  assert "等价于依次" not in result.out


@pytest.mark.parametrize("command", [None, "run", "usage"], ids=["root", "run", "usage"])
def test_native_tail_help_keeps_execution_boundary_scope(command, monkeypatch):
  # usage --help 属于原生尾部；只读取注册帮助，不调度 CLI 或宿主。
  with no_state(monkeypatch):
    parser = cli.build_parser()
    if command is not None:
      subparsers = next(action for action in parser._actions
        if isinstance(action, cli.argparse._SubParsersAction))
      parser = subparsers.choices[command]
    text = parser.format_help()
  assert "CLI 本层不解释或重排" in text
  assert "后续既有受管身份、凭据及适配器边界检查仍适用" in text
  assert "不由管理器解释" not in text
  if command == "usage":
    assert "包括 --help" in text and "不提供管理器局部 help" in text


def test_every_registered_parser_has_scoped_help_and_parseable_examples(monkeypatch):
  from agentcfg.cli_help import EXAMPLES
  with no_state(monkeypatch):
    parser = cli.build_parser()
    def visit(current):
      assert current.description
      assert current.epilog
      for action in current._actions:
        if isinstance(action, cli.argparse._SubParsersAction):
          for child in action.choices.values():
            visit(child)
    visit(parser)
    for examples in EXAMPLES.values():
      for words in examples:
        parsed = parser.parse_args(list(words))
        assert parsed.command is not None


@pytest.mark.parametrize("argv, help_command, registered", [
  (["model", "key"], "./agentcfg model key --help", "provider"),
  (["lock"], "./agentcfg lock --help", "--agent"),
  (["recover", "pi"], "./agentcfg recover --help", "--lease"),
  (["project", "init", "openspec"], "./agentcfg project init --help", "--path"),
  (["model"], "./agentcfg model --help", "子命令"),
  (["model", CANARY], "./agentcfg model --help", "key"),
  (["doctor", "--synthetic-private-option", CANARY], "./agentcfg doctor --help", "--format"),
  (["run", "--cwd"], "./agentcfg run --help", "--cwd"),
  (["model", "key", "bad/" + CANARY], "./agentcfg model key --help", "provider"),
  (["doctor", "--format", CANARY], "./agentcfg doctor --help", "human"),
  (["--machine", "workstation", "--local", CANARY, "doctor"], "./agentcfg --help", "--machine"),
  (["--machine", "workstation", "--machine", CANARY, "doctor"], "./agentcfg --help", "--machine"),
  (["--machine", CANARY, "init-local"], "./agentcfg init-local --help", "--profile"),
])
def test_parameter_errors_are_specific_but_never_echo_values(argv, help_command, registered, monkeypatch, capsys):
  with no_state(monkeypatch):
    with pytest.raises(SystemExit) as error:
      cli.build_parser().parse_args(argv)
  assert error.value.code == 2
  result = capsys.readouterr()
  assert not result.out
  assert CANARY not in result.err
  assert "--synthetic-private-option" not in result.err
  assert help_command in result.err
  assert registered in result.err


def test_reused_parser_does_not_leak_previous_help_context(capsys):
  parser = cli.build_parser()
  parser.parse_args(["model", "key", "kimi-code"])
  with pytest.raises(SystemExit):
    parser.parse_args(["--machine"])
  output = capsys.readouterr().err
  assert "./agentcfg --help" in output
  assert "./agentcfg model key --help" not in output


@pytest.mark.parametrize("argv", [
  ["status"], ["doctor", "--verbose"], ["run", "--profile", "omp-default"],
  ["--mach", "workstation", "doctor"], ["--profile", "dsh-default", "profiles"],
  ["--machine", "workstation", "model", "presets"],
])
def test_no_new_syntax_or_selector_relaxation(argv, capsys):
  with pytest.raises(SystemExit) as error:
    cli.build_parser().parse_args(argv)
  assert error.value.code == 2


@pytest.mark.parametrize("prefix", [["usage"], ["run", "--"], ["--profile", "omp-default", "usage"]])
def test_native_tail_remains_literal_and_uninspected(prefix, monkeypatch, capsys):
  tail = ["--help", "--machine", CANARY, "--profile", "native", "", "中文 空格", "--"]
  with no_state(monkeypatch):
    parsed = cli.build_parser().parse_args([*prefix, *tail])
  assert parsed.passthrough == tail
  assert not capsys.readouterr().out


def test_existing_selector_defaults_repetition_and_equals_forms_are_unchanged():
  parser = cli.build_parser()
  parsed = parser.parse_args(["init-local", "--profile", "dsh-default", "--profile", "pi-default"])
  assert parsed.init_profile == "pi-default"
  assert parsed.machine is None and parsed.profile is None
  parsed = parser.parse_args(["--machine=workstation", "--profile=omp-default", "usage", "--help"])
  assert parsed.machine == "workstation" and parsed.profile == "omp-default"
  assert parsed.passthrough == ["--help"]
  parsed = parser.parse_args(["run"])
  assert parsed.agent is None and parsed.passthrough == []


@pytest.mark.parametrize("argv", [
  ["--profile", "dsh-default", "--profile", CANARY, "doctor"],
  ["--local", "/path/to/config.toml", "--local", CANARY, "doctor"],
  ["init-local", "--machine", "workstation", "--machine", CANARY],
])
def test_existing_unique_selector_rejections_do_not_echo_values(argv, capsys):
  with pytest.raises(SystemExit) as error:
    cli.build_parser().parse_args(argv)
  assert error.value.code == 2
  output = capsys.readouterr().err
  assert "选择器不得重复" in output and CANARY not in output


def doctor_payload(**updates):
  payload = {"command": "doctor", "agent": "dsh", "profile": "dsh-default",
    "deployed": True, "previous_backup": True, "dependencies": "installed",
    "deployed_dependencies": "installed", "recovery_pending": False,
    "live": False, "drift": False, "conflicts": False, "changes_pending": 0,
    "readiness": {"status": "offline-ready", "blockers": [], "next_commands": []}}
  payload.update(updates)
  return payload


def render(payload, **selection):
  args = SimpleNamespace(format="human", machine="workstation", local=None, profile=payload.get("profile"))
  for name, value in selection.items():
    setattr(args, name, value)
  out = io.StringIO()
  presentation._render_human(payload, args, out)
  return out.getvalue()


def test_doctor_overview_names_scope_and_limits_without_state(monkeypatch):
  payload = doctor_payload()
  original = deepcopy(payload)
  with no_state(monkeypatch):
    text = render(payload)
    local_text = render(payload, machine=None, local=Path("/path/to/中文 config.toml"))
  assert "机器" in text and "workstation" in text and "dsh / dsh-default" in text
  assert "检查范围" in text and "离线" in text
  assert "备份" in text and "未验证" in text
  assert "本地配置" in local_text and "/path/to/中文 config.toml" in local_text
  assert payload == original


def test_pending_recovery_precedes_other_actions_and_preserves_payload(monkeypatch):
  payload = doctor_payload(recovery_pending=True, dependencies="sync-required", readiness={
    "status": "action-required", "blockers": ["dependencies-sync-required", "recovery-pending"],
    "next_commands": ["sync", "apply-or-rollback", "setup", "plan"]})
  original = deepcopy(payload)
  with no_state(monkeypatch):
    text = render(payload)
  apply = "./agentcfg --machine workstation --profile dsh-default apply"
  sync = "./agentcfg --machine workstation --profile dsh-default sync"
  assert "恢复前置" in text and "备选" in text
  assert text.index("恢复前置") < text.index(apply)
  assert text.index(apply) < text.index("恢复完成后") < text.index(sync)
  assert payload == original


def test_lock_rebuild_is_not_presented_as_ordinary_repair(monkeypatch):
  payload = doctor_payload(lock="missing-or-invalid", dependencies="unknown", readiness={
    "status": "action-required", "blockers": ["lock-missing-or-invalid"],
    "next_commands": ["lock --agent dsh"]})
  with no_state(monkeypatch):
    text = render(payload)
  lock = "./agentcfg --machine workstation --profile dsh-default lock --agent dsh"
  assert "核对或恢复" in text
  assert "不是普通修复" in text
  assert text.index("核对或恢复") < text.index("不是普通修复") < text.index(lock)


def test_collected_environment_input_live_remain_visible_during_recovery(monkeypatch):
  # 先加载公开 schema 包资源；下方哨兵针对已加载展示逻辑的状态访问。
  from agentcfg.config import _credential_name
  assert _credential_name("API_TOKEN")
  payload = doctor_payload(live=True, recovery_pending=True, readiness={"status": "action-required",
    "blockers": ["recovery-pending"], "next_commands": ["apply-or-rollback"]},
    environment={"status": "host-preview", "policy": "caller", "declarations_pending": False,
      "sensitive_excluded": 1, "variables": [{"name": "PATH", "status": "overridden", "source": "caller"},
        {"name": "API_TOKEN", "status": "overridden", "source": CANARY}]},
    input_diagnostics={"diagnostic_terminal": {"stdin_tty": True, "canonical": True, "echo": True, "signals": True},
      "host_events": None, "note": CANARY},
    service_checks=[{"location_id": "provider:" + "a" * 20, "status": "reachable", "http_status": 200, "url": CANARY}])
  with no_state(monkeypatch):
    text = render(payload)
  for value in ("恢复前置", "PATH", "环境诊断", "诊断 stdin", "HTTP 可达", "200", "未验证"):
    assert value in text
  assert CANARY not in text and "API_TOKEN" not in text


@pytest.mark.parametrize("mode, tty", [("json", True), ("auto", False)])
def test_doctor_json_is_unchanged_even_with_pending_lock_actions(mode, tty, monkeypatch, capsys):
  payload = doctor_payload(recovery_pending=True, lock="missing-or-invalid", readiness={
    "status": "action-required", "blockers": ["recovery-pending", "lock-missing-or-invalid"],
    "next_commands": ["lock --agent dsh", "apply-or-rollback", "sync"]})
  original = deepcopy(payload)
  args = SimpleNamespace(format=mode, machine="workstation", profile="dsh-default")
  monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
  with no_state(monkeypatch):
    presentation.emit_result(payload, args=args)
  result = capsys.readouterr()
  assert json.loads(result.out) == original
  assert not result.err and payload == original


def test_unknown_doctor_readiness_never_claims_ready(monkeypatch):
  payload = doctor_payload(readiness=None)
  with no_state(monkeypatch):
    text = render(payload, machine=None, local=None)
  assert "状态未知" in text
  assert "doctor：离线就绪" not in text


def test_all_required_capability_blockers_keep_their_location_ids():
  capabilities = [{"selected": True, "id": f"capability-{index}",
    "location_id": "capability:" + f"{index:020x}", "dependencies": "missing",
    "blockers": []} for index in range(12)]
  text = render(doctor_payload(agent="pi", profile="pi-default", capabilities=capabilities))
  for capability in capabilities:
    assert capability["location_id"] in text
  assert "最多 8 项" not in text
