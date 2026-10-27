"""原 pane 恢复的静态帮助与普通 session 边界，不查询真实终端。"""
import io
import shlex
import subprocess

import pytest

from agentcfg.sessions import KnownSession, SessionRef
from rotom import cli
from rotom.context import InputGateway
from rotom.resume import CandidateResume


def forbidden(*args, **kwargs):
  pytest.fail("pane boundary notices must not read configuration or invoke native processes")


@pytest.mark.parametrize("path", [["run"], ["agent", "run"], ["resume"], ["agent", "maintenance", "restore"]])
def test_help_explains_pane_boundary_without_io(path, monkeypatch, capsys):
  from agentcfg import config, workspace
  from rotom import preferences
  from termcfg import work, work_config
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  monkeypatch.setattr(config, "read_local_document", forbidden)
  monkeypatch.setattr(workspace, "load_workspace", forbidden)
  monkeypatch.setattr(work_config, "read_settings", forbidden)
  monkeypatch.setattr(work_config, "resolve_executable", forbidden)
  monkeypatch.setattr(work, "connected", forbidden)
  monkeypatch.setattr(subprocess, "Popen", forbidden)
  assert cli.main([*path, "--help"]) == 0
  text = capsys.readouterr().out
  assert "驻留启动器托管" in text
  if path[-1] == "run":
    assert "Rotom Herdr 专用入口" in text
  else:
    for expected in ("已保存完整 workflow 清单", "逐工具/Linux/Herdr/驻留准入", "位置诊断", "加载待确认", "不发送继续"):
      assert expected in text
  if path[-1] == "run":
    assert "Agent 退出后返回 shell" in text
    assert "处于 Herdr 中也不会自动获得原 pane 恢复能力" in text
  else:
    for expected in ("不需要 Herdr", "--original/--new-tab", "Rotom Herdr 入口", "该工具已验收的新实例",
        "只停止 Agent", "旧普通实例", "直接官方 CLI", "launcher 或 pane 关闭/丢失", "--stopped --list", "--here"):
      assert expected in text


@pytest.mark.parametrize("option", ["--original", "--new-tab"])
@pytest.mark.parametrize("scope", [["--machine", "synthetic"], ["--local", "/tmp/synthetic scope.toml"]])
@pytest.mark.parametrize("output_format", ["human", "json"])
def test_rejected_location_preserves_stdout_scope_and_exit(option, scope, output_format, monkeypatch):
  streams = InputGateway(io.StringIO(), io.StringIO(), io.StringIO())
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  target = KnownSession(SessionRef("dsh", "managed", "home-a", "example"),
    "scope-a", "dsh-default", "/tmp/synthetic-cwd", "historical", "historical", 1, "a" * 32)
  candidate = CandidateResume(lambda selected: ("scope-a", (target,)), forbidden)
  assert cli.main(["--no-input", "resume", "dsh", *scope, "--profile", "dsh-default",
    "--session", "example", option, "--format", output_format], resume_candidate=candidate) == 5
  assert streams.stdout.getvalue() == ""
  text = streams.stderr.getvalue()
  command = next(line.split("：", 1)[1] for line in text.splitlines() if line.startswith("同范围当前终端恢复命令："))
  assert shlex.split(command) == ["rotom", "resume", "dsh", *scope, "--profile", "dsh-default",
    "--session", "example", "--here"]
  for expected in ("尚未开放", "安装 Herdr 也不会启用", "刚新启动也不等于可原位恢复", "该工具已验收的新实例",
      "只停止 Agent", "launcher 或 pane 关闭/丢失", "不需要 Herdr", "--stopped --list"):
    assert expected in text


@pytest.mark.parametrize("option", ["--session"])
def test_stopped_session_conflict_fails_before_candidate(option, monkeypatch):
  streams = InputGateway(io.StringIO(), io.StringIO(), io.StringIO())
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  suffix = [option, "example"] if option == "--session" else [option]
  candidate = CandidateResume(forbidden, forbidden)
  assert cli.main(["--no-input", "resume", "--stopped", *suffix], resume_candidate=candidate) == 2
  assert streams.stdout.getvalue() == ""
  assert "尚未开放" not in streams.stderr.getvalue()
