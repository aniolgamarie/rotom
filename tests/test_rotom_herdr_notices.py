"""Herdr 前提说明；仅使用隔离目录与合成端点。"""
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from rotom import cli
from termcfg import work, work_config
from termcfg.errors import TermcfgError


@pytest.mark.parametrize("path,expected", [
  (["work"], "配置检查/编辑"),
  (["work", "enter"], "可启动配置的 headless"),
  (["work", "named", "enter"], "可启动配置的 headless"),
  (["work", "open"], "当前 Herdr 调用上下文"),
  (["work", "close"], "当前 Herdr 调用上下文"),
  (["work", "rebind"], "当前 Herdr 调用上下文"),
  (["work", "list"], "离线 work list 不需要 Herdr"),
  (["work", "status"], "不一定表示未安装"),
  (["work", "reconcile"], "不一定表示未安装"),
  (["work", "worktree", "create"], "创建本身不需要 Herdr"),
  (["work", "named", "rename"], "元数据标题保存不需要 Herdr"),
  (["work", "config", "check"], "操作不需要 Herdr"),
  (["work", "config", "edit"], "操作不需要 Herdr"),
  (["work", "source", "add"], "操作不需要 Herdr"),
  (["work", "project", "add"], "操作不需要 Herdr"),
  (["work", "named", "add"], "操作不需要 Herdr"),
  (["resume"], "安装 Herdr 也不会启用"),
  (["agent", "maintenance", "restore"], "不需要 Herdr"),
])
def test_help_explains_herdr_without_lookup(path, expected, monkeypatch, capsys):
  def forbidden(*args, **kwargs):
    pytest.fail("static help must not read settings or discover executable")
  monkeypatch.setattr(work_config, "read_settings", forbidden)
  monkeypatch.setattr(work_config, "resolve_executable", forbidden)
  monkeypatch.setattr(work, "connected", forbidden)
  assert cli.main([*path, "--help"]) == 0
  assert expected in capsys.readouterr().out


def unavailable(code=5, reason="work_executable_not_prepared"):
  @contextmanager
  def connect(*args, **kwargs):
    raise TermcfgError(code, reason, "work status")
    yield
  return connect


@pytest.mark.parametrize("command", ["status", "reconcile", "list"])
@pytest.mark.parametrize("code,reason", [(5, "work_executable_not_prepared"), (4, "work_context_unknown")])
def test_live_unknown_preserves_result_and_explains_boundary(command, code, reason, monkeypatch, capsys):
  from termcfg import work_git, work_projects
  monkeypatch.setattr(work, "connected", unavailable(code, reason))
  monkeypatch.setattr(work_git, "report", lambda settings: {})
  monkeypatch.setattr(work_projects, "discover", lambda settings: SimpleNamespace(candidates=[]))
  assert work.structured_native_command(SimpleNamespace(command=command), object()) == 0
  output = capsys.readouterr()
  assert json.loads(output.out) == {"endpoint": "unavailable-or-unknown", "bindings": [], "reason": reason, **({"candidates": []} if command == "list" else {})}
  assert "Herdr live endpoint" in output.err and "does not prove Herdr is absent" in output.err


def test_title_saved_but_unavailable_keeps_success(monkeypatch, capsys):
  monkeypatch.setattr(work, "connected", unavailable())
  assert work.synchronize_named_title(object(), "example", "Example") == 0
  output = capsys.readouterr()
  assert output.out == "work_named_title: saved; native presentation not synchronized\n"
  assert "Herdr native title sync pending" in output.err


def test_open_without_caller_preserves_conflict_and_names_herdr(monkeypatch, capsys):
  def forbidden(*args, **kwargs):
    pytest.fail("caller rejection must precede configuration and endpoint lookup")
  monkeypatch.setattr(work_config, "read_settings", forbidden)
  monkeypatch.setattr(work, "connected", forbidden)
  assert work.main(["open", "shell"]) == 4
  output = capsys.readouterr()
  assert "work_context_unknown" in output.err
  assert "Herdr prerequisite" in output.err


def test_enter_endpoint_failure_keeps_code_and_names_herdr(monkeypatch, capsys):
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: SimpleNamespace(model="structured-v1"))
  def fail(*args, **kwargs):
    raise TermcfgError(5, "Herdr API unavailable", "work status")
  monkeypatch.setattr(work, "structured_command", fail)
  assert work.main(["enter", "/example/project"]) == 5
  output = capsys.readouterr()
  assert "Herdr API unavailable" in output.err and "Herdr prerequisite" in output.err


def test_title_saved_pending_conflict_keeps_code(monkeypatch, capsys):
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: SimpleNamespace(model="structured-v1"))
  def fail(*args, **kwargs):
    return work.synchronize_named_title(object(), "example", "Example")
  monkeypatch.setattr(work, "connected", unavailable(4, "work_context_unknown"))
  monkeypatch.setattr(work, "structured_command", fail)
  assert work.main(["named", "rename", "example", "--title", "Example"]) == 4
  output = capsys.readouterr()
  assert "work_named_title_saved_native_presentation_pending" in output.err
  assert "metadata title is saved" in output.err


def test_worktree_enter_herdr_failure_keeps_checkout_and_exit_code(monkeypatch, capsys, tmp_path):
  from termcfg import work_git
  checkout = tmp_path / "new-checkout"
  result = {"path": str(checkout)}
  settings = SimpleNamespace(model="structured-v1", selectors=[])
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: settings)
  monkeypatch.setattr(work_git, "preview", lambda *args, **kwargs: SimpleNamespace(as_dict=lambda: {"operation": "create"}))
  def create(*args, **kwargs):
    checkout.mkdir()
    return result
  monkeypatch.setattr(work_git, "create", create)
  original = work.structured_command
  def dispatch(args, settings, **kwargs):
    if args.command == "enter":
      assert checkout.is_dir()
      raise TermcfgError(5, "Herdr API unavailable", "work status")
    return original(args, settings, **kwargs)
  monkeypatch.setattr(work, "structured_command", dispatch)
  assert work.main(["worktree", "create", "--repo", "/example/repo", "--path", str(checkout),
    "--template", "dev", "--existing-branch", "example", "--enter"]) == 5
  output = capsys.readouterr()
  assert checkout.is_dir()
  assert json.loads(output.out.splitlines()[-1]) == result
  assert "Herdr API unavailable" in output.err and "Herdr prerequisite" in output.err
  assert "work_git_checkout_retained" in output.err
