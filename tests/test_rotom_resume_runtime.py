"""受管恢复的内部执行接缝；只使用假进程，不准入真实恢复能力。"""

from contextlib import contextmanager
import fcntl
import os
import re

import pytest

from agentcfg import deployment, run_owners, runtime
from agentcfg.backends import DshBackend
from agentcfg.dependencies import read_lock
from agentcfg.dsh_optional import TEAM_SELECTION_FILE
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_rotom_runtime_observation import MANAGER, observation
from test_runtime import local_file


@pytest.fixture
def managed(tmp_path, prepared_runtime, monkeypatch, observation):
  path = tmp_path / "local.toml"
  local_file(path)
  workspace = load_workspace(path)
  lock = read_lock(workspace.repository)
  deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity),
    workspace.binding, runtime.record(workspace, lock))
  prepared_runtime(workspace, lock)
  package = {"active": False, "path": tmp_path / "synthetic-package.lock"}
  @contextmanager
  def package_guard(backend, selected, identity):
    assert selected is workspace and identity == lock.identity
    fd = os.open(package["path"], os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    package.update(active=True, fd=fd)
    try:
      yield fd
    finally:
      package["active"] = False
      os.close(fd)
  monkeypatch.setattr(DshBackend, "runtime_guard", package_guard, raising=False)
  return workspace, lock, package, observation


def records(workspace):
  return run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()


def assert_exclusive_busy(path):
  fd = os.open(path, os.O_RDONLY)
  try:
    with pytest.raises(BlockingIOError):
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  finally:
    os.close(fd)


def assert_exclusive_free(path):
  fd = os.open(path, os.O_RDONLY)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  finally:
    os.close(fd)


@pytest.mark.parametrize("complete", [False, True])
def test_resume_callback_receives_registered_identity_and_live_three_leases(managed, tmp_path,
    fake_subprocess, complete):
  workspace, lock, package, observation = managed
  observation["value"] = complete
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  marker = object()
  seen = []
  def resume(selected, spec, env, lease, contract, *, run_id, lifecycle_fd, package_fd):
    assert selected is workspace and spec.cwd == tmp_path
    assert contract["lock_identity"] == lock.identity
    assert re.fullmatch(r"[0-9a-f]{32}", run_id)
    entry = records(workspace)[run_id]
    assert entry["lifecycle_state"] == "active" and entry["manager_identity"] == MANAGER
    assert env["DSH_HOME"] == str(workspace.instance / "dsh-home")
    assert package["active"] and package_fd == package["fd"]
    assert len({lease, lifecycle_fd, package_fd}) == 3
    for fd in (lease, lifecycle_fd, package_fd):
      os.fstat(fd)
    for path in (workspace.instance, workspace.state_root / "instance.lock", package["path"]):
      assert_exclusive_busy(path)
    seen.append(run_id)
    return marker
  assert runtime.run(workspace, cwd=tmp_path, resume_operation=resume) is marker
  assert len(seen) == 1 and len(fake_subprocess.calls) == 1
  assert records(workspace)[seen[0]]["lifecycle_state"] == ("idle_confirmed" if complete else "unknown")
  assert package["active"] is False
  for path in (workspace.instance, workspace.state_root / "instance.lock", package["path"]):
    assert_exclusive_free(path)


@pytest.mark.parametrize("failure", [ValueError, OSError])
def test_resume_callback_exception_keeps_existing_owner_exit_observation(managed, tmp_path,
    fake_subprocess, failure):
  workspace, lock, package, observation = managed
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  def resume(*args, **kwargs):
    assert package["active"]
    raise failure("synthetic-operation-error")
  with pytest.raises(runtime.DependencyError if failure is OSError else failure):
    runtime.run(workspace, cwd=tmp_path, resume_operation=resume)
  entry, = records(workspace).values()
  assert entry["lifecycle_state"] == "unknown"
  assert package["active"] is False and len(fake_subprocess.calls) == 1
  assert_exclusive_free(workspace.instance)
  assert_exclusive_free(workspace.state_root / "instance.lock")
  assert_exclusive_free(package["path"])


@pytest.mark.parametrize("run_id", [None, "", "not-a-run", "g" * 32, True])
def test_resume_callback_refuses_unreliable_registration(managed, tmp_path,
    fake_subprocess, monkeypatch, run_id):
  workspace, lock, package, observation = managed
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  @contextmanager
  def unregistered(*args, **kwargs):
    yield run_id
  monkeypatch.setattr(workspace.adapter, "run_owner_guard", unregistered)
  def forbidden(*args, **kwargs):
    pytest.fail("恢复回调必须取得可信新运行身份")
  with pytest.raises(runtime.DependencyError):
    runtime.run(workspace, cwd=tmp_path, resume_operation=forbidden)
  assert len(fake_subprocess.calls) == 1 and package["active"] is False


def test_resume_callback_requires_an_owner_guard(managed, tmp_path, fake_subprocess, monkeypatch):
  workspace, lock, package, observation = managed
  monkeypatch.setattr(workspace.adapter, "run_owner_guard", None)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  def forbidden(*args, **kwargs):
    pytest.fail("没有可靠登记时不得调用恢复回调")
  with pytest.raises(runtime.DependencyError):
    runtime.run(workspace, cwd=tmp_path, resume_operation=forbidden)
  assert len(fake_subprocess.calls) == 1


def test_launch_and_resume_callbacks_are_mutually_exclusive(managed, tmp_path):
  workspace, lock, package, observation = managed
  def forbidden(*args, **kwargs):
    pytest.fail("冲突操作不执行回调")
  with pytest.raises(ConfigError):
    runtime.run(workspace, cwd=tmp_path, launch_operation=forbidden, resume_operation=forbidden)


@pytest.mark.parametrize("override", [{"inherit_env": ("SYNTHETIC_EXTRA",)}, {"unset_env": ("SYNTHETIC_EXTRA",)}])
def test_resume_callback_cannot_change_the_operation_environment(managed, tmp_path, override):
  workspace, lock, package, observation = managed
  def forbidden(*args, **kwargs):
    pytest.fail("恢复接缝不能绕过操作环境限制")
  with pytest.raises(ConfigError):
    runtime.run(workspace, cwd=tmp_path, resume_operation=forbidden, **override)
  assert records(workspace) == {}


@pytest.mark.parametrize("failure", ["binding", "drift", "package"])
def test_resume_preflight_refusal_never_invokes_the_callback(managed, tmp_path,
    monkeypatch, fake_subprocess, failure):
  workspace, lock, package, observation = managed
  if failure == "binding":
    workspace.local_path = tmp_path / "different-local.toml"
  elif failure == "drift":
    (workspace.instance / TEAM_SELECTION_FILE).write_text("synthetic drift\n")
  else:
    monkeypatch.setattr(DshBackend, "status", lambda *args: "missing")
  def forbidden(*args, **kwargs):
    pytest.fail("部署、漂移和包检查必须先于恢复回调")
  with pytest.raises(runtime.DependencyError if failure == "package" else Conflict):
    runtime.run(workspace, cwd=tmp_path, resume_operation=forbidden)
  assert fake_subprocess.calls == []


def test_resume_without_deployment_never_invokes_the_callback(tmp_path, prepared_runtime,
    fake_subprocess):
  path = tmp_path / "local.toml"
  local_file(path)
  workspace = load_workspace(path)
  prepared_runtime(workspace, read_lock(workspace.repository))
  def forbidden(*args, **kwargs):
    pytest.fail("未部署实例不能通过恢复接缝启动")
  with pytest.raises(Conflict):
    runtime.run(workspace, cwd=tmp_path, resume_operation=forbidden)
  assert fake_subprocess.calls == []


def test_existing_launch_callback_signature_and_result_remain_compatible(managed, tmp_path, fake_subprocess):
  workspace, lock, package, observation = managed
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  marker = object()
  def launch(selected, spec, env, lease, contract, *, lifecycle_fd):
    assert selected is workspace and spec.cwd == tmp_path
    os.fstat(lease)
    os.fstat(lifecycle_fd)
    assert package["active"] and len(records(workspace)) == 1
    return marker
  assert runtime.run(workspace, cwd=tmp_path, launch_operation=launch) is marker
  assert len(fake_subprocess.calls) == 1 and package["active"] is False


def test_ordinary_run_without_registered_identity_keeps_native_stdio_and_exit(managed,
    tmp_path, fake_subprocess, monkeypatch):
  workspace, lock, package, observation = managed
  monkeypatch.setattr(workspace.adapter, "run_owner_guard", None)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=-15)
  assert runtime.run(workspace, cwd=tmp_path, arguments=("--opaque-native",)) == 143
  native = fake_subprocess.calls[-1]
  assert native["argv"][-1] == "--opaque-native" and native["cwd"] == tmp_path
  assert len(native["pass_fds"]) == 3 and len(fake_subprocess.calls) == 2
  assert package["active"] is False and records(workspace) == {}


@pytest.mark.parametrize("changed", [False, True])
def test_approved_deployment_is_rechecked_under_original_locks(managed, tmp_path,
    fake_subprocess, monkeypatch, changed):
  from agentcfg.setup_preview import setup_deployment_digest
  from agentcfg.storage import Tree
  workspace, lock, package, observation = managed
  observation["value"] = True
  with Tree(workspace.state_root) as state:
    approved = setup_deployment_digest(deployment.read_state(state)["current"])
  original_guard = workspace.adapter.run_lifecycle_guard_for
  original_read = runtime.read_state
  reads, dispatched = [], []

  @contextmanager
  def competing_update(selected, arguments):
    # 模拟上层审阅之后、原物理 SH 获取之前，另一部署已完整提交。
    if changed:
      candidate = workspace.candidate(lock.identity)
      from dataclasses import replace
      candidate = replace(candidate, generation="f" * 64)
      deployment.apply(workspace.instance, workspace.state_root, candidate,
        workspace.binding, runtime.record(workspace, lock))
    with original_guard(selected, arguments) as fd:
      yield fd

  def locked_read(state):
    assert_exclusive_busy(workspace.instance)
    assert_exclusive_busy(workspace.state_root / "instance.lock")
    reads.append(True)
    return original_read(state)

  def resume(*args, **kwargs):
    dispatched.append(kwargs["run_id"])
    return 0

  monkeypatch.setattr(workspace.adapter, "run_lifecycle_guard_for", competing_update)
  monkeypatch.setattr(runtime, "read_state", locked_read)
  if changed:
    with pytest.raises(Conflict):
      runtime.run(workspace, cwd=tmp_path, resume_operation=resume, expected_deployment=approved)
    assert not dispatched and records(workspace) == {} and fake_subprocess.calls == []
  else:
    fake_subprocess.queue(returncode=0, stdout="v24.2.0")
    assert runtime.run(workspace, cwd=tmp_path, resume_operation=resume, expected_deployment=approved) == 0
    assert len(dispatched) == 1
  assert reads


@pytest.mark.parametrize("digest", [True, "", "z" * 64, "a" * 63])
def test_invalid_restore_binding_rejected_before_host_or_registration(managed, tmp_path, fake_subprocess, digest):
  workspace, _, _, _ = managed
  with pytest.raises(ConfigError):
    runtime.run(workspace, cwd=tmp_path, resume_operation=lambda *a, **kw: pytest.fail("invalid binding"),
      expected_deployment=digest)
  assert fake_subprocess.calls == [] and records(workspace) == {}


def test_restore_binding_cannot_authorize_an_ordinary_run(managed, tmp_path, fake_subprocess):
  workspace, _, _, _ = managed
  with pytest.raises(ConfigError):
    runtime.run(workspace, cwd=tmp_path, expected_deployment="a" * 64)
  assert fake_subprocess.calls == [] and records(workspace) == {}
