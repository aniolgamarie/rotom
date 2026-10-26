"""公共启动路径的归属登记，实际宿主由测试替身替代。"""

import pytest

from agentcfg import deployment, lifecycle, run_owners, runtime
from agentcfg.dependencies import read_lock
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_runtime import CANARY, local_file


@pytest.fixture
def owner_workspace(tmp_path, monkeypatch, prepared_runtime):
  path = tmp_path / "local.toml"
  local_file(path)
  workspace = load_workspace(path)
  lock = read_lock(workspace.repository)
  deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity),
    workspace.binding, runtime.record(workspace, lock))
  prepared_runtime(workspace, lock)
  monkeypatch.setattr(run_owners, "current_process_identity",
    lambda: {"pid": 101, "birth_id": "synthetic-boot-and-start"})
  monkeypatch.setattr(workspace.adapter, "run_owner_guard",
    lambda selected, **kwargs: lifecycle.registered_run(selected, **kwargs), raising=False)
  return workspace


def registry(workspace):
  return run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)


def test_native_exit_kept_and_unknown_descendants_block_maintenance(owner_workspace,
    fake_subprocess, tmp_path):
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=19)
  assert runtime.run(owner_workspace, cwd=tmp_path) == 19
  records = registry(owner_workspace).snapshot()
  assert len(records) == 1
  assert run_owners.record_state(next(iter(records.values()))) == "unknown"
  with lifecycle.guard(owner_workspace, create=False):
    with pytest.raises(Conflict):
      registry(owner_workspace).assert_inactive()


def test_bookkeeping_failure_does_not_replace_native_exit(owner_workspace, fake_subprocess,
    tmp_path, monkeypatch, capsys):
  def fail(*args):
    raise Conflict("synthetic recording failure")
  monkeypatch.setattr(run_owners.Registry, "mark_unknown", fail)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=23)
  assert runtime.run(owner_workspace, cwd=tmp_path) == 23
  assert run_owners.record_state(next(iter(registry(owner_workspace).snapshot().values()))) == "active"
  output = capsys.readouterr()
  assert "运行归属状态未能更新" in output.err
  assert CANARY not in output.err + output.out


def test_failed_preflight_does_not_register_run(owner_workspace, fake_subprocess, tmp_path):
  fake_subprocess.queue(returncode=0, stdout="v1.0.0")
  with pytest.raises(DependencyError):
    runtime.run(owner_workspace, cwd=tmp_path)
  assert registry(owner_workspace).snapshot() == {}


@pytest.mark.parametrize("error", [BrokenPipeError, ValueError])
def test_closed_diagnostic_stream_does_not_replace_native_exit(owner_workspace,
    fake_subprocess, tmp_path, monkeypatch, error):
  class ClosedStream:
    def write(self, value):
      raise error("synthetic closed diagnostic stream")
  with monkeypatch.context() as patch:
    def fail(*args):
      # 仅在宿主已退出、归属记账失败后关闭诊断输出。
      patch.setattr(lifecycle.sys, "stderr", ClosedStream())
      raise Conflict("synthetic recording failure")
    patch.setattr(run_owners.Registry, "mark_unknown", fail)
    fake_subprocess.queue(returncode=0, stdout="v24.2.0")
    fake_subprocess.queue(returncode=29)
    assert runtime.run(owner_workspace, cwd=tmp_path) == 29
  assert run_owners.record_state(next(iter(registry(owner_workspace).snapshot().values()))) == "active"


def test_two_shared_runs_only_update_their_own_record(owner_workspace, fake_subprocess, tmp_path):
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  def second(*args, **kwargs):
    records = registry(owner_workspace).snapshot()
    assert len(records) == 2
    assert all(run_owners.record_state(record) == "active" for record in records.values())
    return 7
  def first(*args, **kwargs):
    assert len(registry(owner_workspace).snapshot()) == 1
    assert runtime.run(owner_workspace, cwd=tmp_path, launch_operation=second) == 7
    assert sorted(run_owners.record_state(record) for record in registry(owner_workspace).snapshot().values()) == ["active", "unknown"]
    return 11
  assert runtime.run(owner_workspace, cwd=tmp_path, launch_operation=first) == 11
  records = registry(owner_workspace).snapshot()
  assert len(records) == 2
  assert all(run_owners.record_state(record) == "unknown" for record in records.values())
