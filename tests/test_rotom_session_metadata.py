"""官方 stat 的 Python 包装；临时部署与假进程，不读取真实会话。"""

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agentcfg import dsh_sessions, sessions
from agentcfg.backends import DshBackend
from agentcfg.storage import Tree, instance_lock
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import observation


@pytest.fixture
def query(managed, monkeypatch, tmp_path):
  workspace, lock, package, _ = managed
  calls = []
  payload = {"status": "metadata", "session_id": "native-example", "cwd": str(tmp_path),
    "source": "session-persistence-stat"}
  result = {"value": payload, "code": 0, "error": None, "version": "v24.2.0"}
  def run(argv, **kwargs):
    calls.append((list(argv), kwargs))
    assert package["active"]
    assert_exclusive_busy(workspace.instance)
    assert_exclusive_busy(workspace.state_root / "instance.lock")
    for fd in kwargs.get("pass_fds", ()):
      os.fstat(fd)
    if argv == ["node", "--version"]:
      return SimpleNamespace(returncode=0, stdout=result["version"], stderr="")
    if result["error"] is not None:
      raise result["error"]
    value = result["value"]
    return SimpleNamespace(returncode=result["code"], stdout=value if type(value) is str else json.dumps(value), stderr="synthetic-private-output")
  monkeypatch.setattr(subprocess, "run", run)
  def forbidden(*args, **kwargs):
    pytest.fail("只读元数据查询不能启动宿主或解析凭据")
  monkeypatch.setattr(dsh_sessions.runtime, "run", forbidden)
  monkeypatch.setattr(type(workspace.secret_store), "resolve", forbidden)
  return workspace, lock, package, calls, result


def snapshot(workspace):
  return {str(path): (path.lstat().st_ino, path.lstat().st_mode, path.lstat().st_mtime_ns,
      os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None)
    for root in (workspace.instance, workspace.state_root) for path in (root, *root.rglob("*"))}


def test_stat_returns_historical_metadata_without_inventing_a_run_and_is_read_only(query, monkeypatch):
  workspace, lock, package, calls, result = query
  for name in ("NODE_OPTIONS", "NODE_PATH", "DSH_TUI_SESSION_ROOT", "AGENTCFG_KEY_SYNTHETIC"):
    monkeypatch.setenv(name, "synthetic-private-control")
  before = snapshot(workspace)
  target = dsh_sessions.lookup_metadata(workspace, "native-example")
  assert target.run_id is None and target.confirmation == target.cwd_status == "historical"
  assert target.ref.native_ref == "native-example" and target.scope == dsh_sessions.scope_key(workspace.binding)
  assert target.profile == workspace.profile and target.cwd == result["value"]["cwd"]
  assert len(calls) == 2
  argv, options = calls[-1]
  assert argv == ["node", str(workspace.repository / "agents/dsh/templates/session-metadata.mjs"),
    str(workspace.backend.root(workspace, lock.identity)), str(workspace.instance / "dsh-home/sessions"), "native-example"]
  assert options["stdin"] == subprocess.DEVNULL and options["capture_output"] is True
  assert options["timeout"] == 10 and len(options["pass_fds"]) == 3
  assert not any(name.startswith(("NODE_", "DSH_", "AGENTCFG_")) for name in options["env"])
  assert options["env"]["HOME"] == str(workspace.instance / "user-home")
  assert snapshot(workspace) == before and package["active"] is False
  assert not (workspace.state_root / "run-owners").exists()


@pytest.mark.parametrize("payload", [None, [], {"status": "unavailable"},
  {"status": "metadata", "session_id": "other", "cwd": "/tmp", "source": "session-persistence-stat"},
  {"status": "metadata", "session_id": "native-example", "cwd": "relative", "source": "session-persistence-stat"},
  {"status": "metadata", "session_id": "native-example", "cwd": "/tmp/../elsewhere", "source": "session-persistence-stat"},
  {"status": "metadata", "session_id": "native-example", "cwd": "/tmp", "source": "ready"},
  {"status": "metadata", "session_id": "native-example", "cwd": "/tmp", "source": "session-persistence-stat", "loaded": True},
  '{"status":"metadata","status":"unavailable"}', "synthetic-private-output", pytest.param("x" * 17000, id="oversized")])
def test_unavailable_or_untrusted_output_never_becomes_a_known_session(query, payload):
  workspace, _, _, calls, result = query
  result["value"] = payload
  with pytest.raises(sessions.SessionError) as caught:
    dsh_sessions.lookup_metadata(workspace, "native-example")
  assert caught.value.code == 5 and "synthetic-private" not in str(caught.value)
  assert len(calls) == 2 and not (workspace.state_root / "run-owners").exists()


@pytest.mark.parametrize("error", [OSError("synthetic-private"), subprocess.TimeoutExpired("synthetic-private", 10)])
def test_query_failure_is_sanitized_and_never_retried(query, error):
  workspace, _, _, calls, result = query
  result["error"] = error
  with pytest.raises(sessions.SessionError) as caught:
    dsh_sessions.lookup_metadata(workspace, "native-example")
  assert caught.value.code == 5 and "synthetic-private" not in str(caught.value)
  assert len(calls) == 2


def test_deep_helper_json_is_unavailable_without_parser_exception(query):
  workspace, _, _, calls, result = query
  result["value"] = "[" * 2000 + "0" + "]" * 2000
  with pytest.raises(sessions.SessionError) as caught:
    dsh_sessions.lookup_metadata(workspace, "native-example")
  assert caught.value.code == 5 and len(calls) == 2


@pytest.mark.parametrize("change,code", [("binding", 4), ("pending", 4), ("profile", 4),
  ("launcher", 4), ("session-link", 4), ("lock-missing", 4), ("package", 5)])
def test_unverified_scope_configuration_or_runtime_never_queries(query, monkeypatch, tmp_path, change, code):
  workspace, _, _, calls, _ = query
  if change == "binding":
    workspace.local_path = tmp_path / "different.toml"
  elif change == "pending":
    (workspace.state_root / "pending.json").write_text("{}")
  elif change == "profile":
    (workspace.instance / "dsh-home/cordis.patch.yml").write_text("- id: extra\n  disabled: true\n")
  elif change == "launcher":
    (workspace.instance / "launch.mjs").write_text("synthetic drift")
  elif change == "session-link":
    (workspace.instance / "dsh-home/sessions").symlink_to(tmp_path, target_is_directory=True)
  elif change == "lock-missing":
    (workspace.state_root / "instance.lock").unlink()
  else:
    monkeypatch.setattr(DshBackend, "status", lambda *args: "damaged")
  before = snapshot(workspace)
  with pytest.raises(sessions.SessionError) as caught:
    dsh_sessions.lookup_metadata(workspace, "native-example")
  assert caught.value.code == code and calls == [] and snapshot(workspace) == before


def test_missing_read_lease_never_creates_a_lock(tmp_path):
  root = tmp_path / "empty-state"
  root.mkdir(mode=0o700)
  with Tree(root) as state, pytest.raises(FileNotFoundError):
    with instance_lock(state, shared=True, create=False):
      pytest.fail("缺只读租约必须拒绝")
  assert list(root.iterdir()) == []


def test_read_lease_rejects_fifo_without_blocking(tmp_path, monkeypatch):
  from agentcfg.storage import Conflict
  root = tmp_path / "fifo-state"
  root.mkdir(mode=0o700)
  os.mkfifo(root / "instance.lock", 0o600)
  original = os.open
  def opened(name, flags, *args, **kwargs):
    if name == "instance.lock":
      assert flags & os.O_NONBLOCK
    return original(name, flags, *args, **kwargs)
  monkeypatch.setattr(os, "open", opened)
  with Tree(root) as state, pytest.raises(Conflict):
    with instance_lock(state, shared=True, create=False):
      pytest.fail("非普通文件不能成为只读租约")


@pytest.mark.parametrize("change", ["darwin", "win32", "full-lock"])
def test_metadata_admission_blocks_unknown_platform_or_full_lock_before_any_helper(query, monkeypatch, change):
  from dataclasses import replace
  workspace, lock, package, calls, result = query
  before = snapshot(workspace)
  if change == "full-lock":
    monkeypatch.setattr(type(workspace.backend), "read_lock", lambda *args: replace(lock, identity="0" * 64))
  else:
    monkeypatch.setattr(dsh_sessions, "sys", SimpleNamespace(platform=change), raising=False)
  with pytest.raises(sessions.SessionError) as caught:
    dsh_sessions.lookup_metadata(workspace, "native-example")
  assert caught.value.code == 5 and calls == [] and not package["active"]
  assert snapshot(workspace) == before
