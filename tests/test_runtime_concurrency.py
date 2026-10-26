"""真实文件锁与假宿主验证并行准入；不执行第三方程序。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from agentcfg import commands, runtime
from agentcfg.dependencies import read_lock
from agentcfg.lifecycle import guard
from agentcfg.storage import Conflict, Tree, instance_lock
from agentcfg.workspace import load_workspace
from test_runtime import local_file


def test_distinct_dsh_runs_share_admission_and_exclude_maintenance(tmp_path, monkeypatch, prepared_runtime, sentinel_factory):
  local = tmp_path / "local.toml"
  local_file(local)
  workspace = load_workspace(local)
  lock = read_lock(workspace.repository)
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  prepared_runtime(workspace, lock)
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  before = sentinel_factory(profile)
  ready, finish = Barrier(3), Event()
  def preflight(argv, **kwargs):
    assert argv[1:] == ["--version"]
    return SimpleNamespace(returncode=0, stdout="v24.2.0", stderr="")
  def child(spec, env, pass_fds, **kwargs):
    ready.wait(timeout=10)
    assert finish.wait(10)
    return 0
  monkeypatch.setattr(runtime.subprocess, "run", preflight)
  monkeypatch.setattr(runtime, "_run_dsh_child", child)
  with ThreadPoolExecutor(max_workers=2) as pool:
    runs = [pool.submit(runtime.run, workspace, cwd=tmp_path) for _ in range(2)]
    try:
      ready.wait(timeout=10)
      with pytest.raises(Conflict):
        with guard(workspace):
          pass
      with pytest.raises(Conflict):
        with Tree(workspace.state_root) as state, instance_lock(state):
          pass
    finally:
      finish.set()
    assert [run.result(timeout=10) for run in runs] == [0, 0]
  before.assert_unchanged()
  with guard(workspace), Tree(workspace.state_root) as state, instance_lock(state):
    pass


def test_unprepared_dsh_launch_fails_without_repair(tmp_path, prepared_runtime, sentinel_factory):
  local = tmp_path / "local.toml"
  local_file(local)
  workspace = load_workspace(local)
  lock = read_lock(workspace.repository)
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  prepared_runtime(workspace, lock)
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  owner = profile / ".agentcfg-package-owner.json"
  owner.write_bytes(b'{"pending_modules":"isolated"}')
  before = sentinel_factory(profile)
  with pytest.raises(Conflict, match="plan/apply"):
    runtime.run(workspace, cwd=tmp_path)
  before.assert_unchanged()


def test_physical_instance_cannot_be_aliased_with_another_state_root(tmp_path):
  local = tmp_path / "local.toml"
  local_file(local)
  workspace = load_workspace(local)
  with guard(workspace):
    pass
  alternate = SimpleNamespace(instance=workspace.instance, state_root=tmp_path / "other-state",
    profile=workspace.profile, binding=workspace.binding)
  with pytest.raises(Conflict):
    with guard(alternate, shared=True, create=False):
      pass
