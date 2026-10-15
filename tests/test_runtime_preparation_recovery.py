"""用虚构运行包路径验证配置事务与 DSH 投影准备的同一恢复边界。"""

from dataclasses import replace
import json

import pytest

from agentcfg import commands, deployment, profile_runtime
from agentcfg.dependencies import read_lock, runtime_root
from agentcfg.storage import Conflict, Tree
from agentcfg.workspace import load_workspace
from test_runtime import local_file


def fixture(tmp_path):
  local = tmp_path / "local.toml"
  local_file(local)
  workspace = load_workspace(local)
  first = read_lock(workspace.repository)
  second = replace(first, identity="b" * 64)
  commands.apply_candidate(workspace, first, workspace.candidate(first.identity))
  return workspace, first, second


def current_lock(workspace):
  with Tree(workspace.state_root) as state:
    return deployment.read_state(state)["current"]["launch"]["lock_identity"]


@pytest.mark.parametrize("stage", ["prepare", "apply", "rollback"])
def test_failed_maintenance_restores_current_launch_projections(tmp_path, monkeypatch, stage):
  workspace, first, second = fixture(tmp_path)
  expected = first
  if stage == "rollback":
    commands.apply_candidate(workspace, second, workspace.candidate(second.identity))
    expected = second
  calls = []
  if stage == "prepare":
    original = profile_runtime.project_runtime_modules
    def fail_once(*args):
      original(*args)
      if not calls:
        calls.append("interrupted")
        raise OSError("synthetic preparation interruption")
    monkeypatch.setattr(profile_runtime, "project_runtime_modules", fail_once)
  else:
    original = deployment.write_changes
    def fail_once(*args, **kwargs):
      if not calls:
        calls.append("interrupted")
        raise OSError("synthetic deployment interruption")
      return original(*args, **kwargs)
    monkeypatch.setattr(deployment, "write_changes", fail_once)
  with pytest.raises(OSError):
    if stage == "rollback":
      with workspace.adapter.lifecycle_guard(workspace):
        deployment.rollback(workspace.instance, workspace.state_root, workspace.binding,
          prepare=lambda launch: commands.prepare_launch(workspace, launch))
    else:
      commands.apply_candidate(workspace, second, workspace.candidate(second.identity))
  assert calls == ["interrupted"]
  assert current_lock(workspace) == expected.identity
  profile_runtime.verify(workspace, runtime_root(workspace, expected))
  assert not (workspace.state_root / "pending.json").exists()


def test_interrupted_preparation_requires_explicit_recovery_callback(tmp_path, monkeypatch):
  workspace, first, second = fixture(tmp_path)
  with monkeypatch.context() as patch:
    # 模拟进程在准备完成后退出，没有机会执行异常清理。
    patch.setattr(deployment, "recover", lambda *args, **kwargs: False)
    patch.setattr(deployment, "write_changes", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic crash")))
    with pytest.raises(OSError):
      commands.apply_candidate(workspace, second, workspace.candidate(second.identity))
  assert current_lock(workspace) == first.identity
  assert (workspace.state_root / "pending.json").exists()
  with Tree(workspace.instance) as target, Tree(workspace.state_root) as state:
    with pytest.raises(Conflict, match="apply/rollback"):
      deployment.recover(target, state)
  commands.apply_candidate(workspace, first, workspace.candidate(first.identity))
  profile_runtime.verify(workspace, runtime_root(workspace, first))
  assert not (workspace.state_root / "pending.json").exists()


def test_repeated_interruption_keeps_observed_projection_ownership(tmp_path, monkeypatch):
  workspace, first, second = fixture(tmp_path)
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  original = Tree.write_state
  phase = ["new-runtime"]
  def interrupt(tree, path, raw, *args, **kwargs):
    if tree.root == profile and path == ".agentcfg-package-owner.json":
      record = json.loads(raw)
      if phase[0] == "new-runtime" and "pending_modules" not in record:
        raise SystemExit("synthetic crash before final owner")
      if phase[0] == "recovery" and "pending_modules" in record:
        original(tree, path, raw, *args, **kwargs)
        raise SystemExit("synthetic second crash after recovery intent")
    return original(tree, path, raw, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", interrupt)
    with pytest.raises(SystemExit):
      profile_runtime.prepare(workspace, runtime_root(workspace, second))
    phase[0] = "recovery"
    with pytest.raises(SystemExit):
      profile_runtime.prepare(workspace, runtime_root(workspace, first))
  profile_runtime.prepare(workspace, runtime_root(workspace, first))
  profile_runtime.verify(workspace, runtime_root(workspace, first))
