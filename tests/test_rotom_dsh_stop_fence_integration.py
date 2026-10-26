"""停止意图在正式 DSH run/apply/sync 门禁中生效；临时文件/假进程身份，无真实宿主。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agentcfg import commands, dependencies, deployment, dsh_stop_scope, lifecycle, run_owners, runtime
from agentcfg import run_stop_fence as fence
from agentcfg import run_stop_snapshot
from agentcfg.backends import DshBackend
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_resume_runtime import managed, assert_exclusive_busy, assert_exclusive_free
from test_rotom_runtime_observation import MANAGER, observation


def recovery_snapshot(registry, records):
  info = registry.root.stat()
  return run_stop_snapshot.build_snapshot(binding=registry.binding,
    registry_physical={"device": info.st_dev, "inode": info.st_ino},
    batch_id="a" * 32, plan_id="b" * 64, expected_records=records, selected_runs=sorted(records))


@pytest.fixture(params=[False, True], ids=["blocking-only", "manual-snapshot"])
def fenced(managed, tmp_path, monkeypatch, request):
  ws, lock, package, observed = managed
  # 恢复正式 DSH 的实例/状态两锁布局，不注入独立运行包锁。
  monkeypatch.delattr(DshBackend, "runtime_guard")
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  with lifecycle.guard(ws, shared=True, create=False) as physical, Tree(ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
    current = deployment.read_state(state)["current"]
    metadata = runtime.run_metadata(ws, current, runtime.decode(current["launch"], tmp_path, ()))
    run = registry.register_v2(MANAGER, metadata)
    expected = registry.snapshot()
    layout = dsh_stop_scope.inspect_deployment(ws, expected[run], instance_fd=physical, state_fd=state_fd)
    snapshot = recovery_snapshot(registry, expected) if request.param else None
    def before():
      assert_exclusive_busy(ws.instance)
      assert_exclusive_busy(ws.state_root / "instance.lock")
      if not request.param:
        assert dsh_stop_scope.inspect_deployment(ws, expected[run], instance_fd=physical, state_fd=state_fd) == layout
    if request.param:
      dsh_stop_scope.save_manual_snapshot(ws, instance_fd=physical, state_fd=state_fd,
        expected_records=expected, selected_runs=[run], expected_layout=layout,
        batch_id="a" * 32, plan_id="b" * 64, before_publish=before)
    else:
      fence.install(registry, batch_id="a" * 32, plan_id="b" * 64,
        expected_records=expected, before_publish=before)
    # 排除 active/unknown 自身的阻断：以下入口必须仅因持久 fence 而拒绝。
    registry.finish_current(run, MANAGER, run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
    assert fence.read_snapshot(registry, "a" * 32) == snapshot
    if snapshot is not None:
      assert snapshot["records"][run]["lifecycle_state"] == "active"
      assert snapshot["records"][run]["session_observation"] is None
      assert snapshot["records"][run]["session_cwd"] is None
  return SimpleNamespace(ws=ws, lock=lock, registry=registry, cwd=tmp_path)


def test_ordinary_run_rejects_after_preflight_before_new_owner_or_host(fenced, fake_subprocess):
  case = fenced; before = case.registry.snapshot()
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  with pytest.raises(Conflict): runtime.run(case.ws, cwd=case.cwd)
  assert case.registry.snapshot() == before and len(fake_subprocess.calls) == 1
  assert_exclusive_free(case.ws.instance)
  assert_exclusive_free(case.ws.state_root / "instance.lock")


def test_resume_callback_cannot_bypass_same_registration_gate(fenced, fake_subprocess):
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  def forbidden(*args, **kwargs): pytest.fail("cannot dispatch resume after stop fence")
  with pytest.raises(Conflict): runtime.run(fenced.ws, cwd=fenced.cwd, resume_operation=forbidden)
  assert len(fake_subprocess.calls) == 1 and len(fenced.registry.snapshot()) == 1


@pytest.mark.parametrize("operation", ["apply", "sync", "rollback"])
def test_existing_write_entrypoints_refuse_before_operation_even_with_idle_owners(fenced, monkeypatch, operation):
  case = fenced
  def forbidden(*args, **kwargs): pytest.fail("fenced operation must not mutate deployment or package")
  if operation == "apply":
    monkeypatch.setattr(deployment, "apply", forbidden)
    action = lambda: commands.apply_candidate(case.ws, case.lock, {})
  elif operation == "sync":
    monkeypatch.setattr(dependencies, "_sync", forbidden)
    action = lambda: case.ws.backend.sync(case.ws, case.lock)
  else:
    monkeypatch.setattr(commands, "workspace", lambda args: case.ws)
    monkeypatch.setattr(deployment, "rollback", forbidden)
    action = lambda: commands.cmd_rollback(SimpleNamespace())
  before = fence.read(case.registry)
  with pytest.raises(Conflict): action()
  assert fence.read(case.registry) == before
  assert_exclusive_free(case.ws.instance)


def test_acceptance_outer_shared_lease_cannot_enter_during_original_maintenance_ex(managed):
  ws, lock, package, observed = managed
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  with ws.adapter.lifecycle_guard(ws):
    with pytest.raises(Conflict):
      with lifecycle.guard(ws, shared=True, create=False):
        pytest.fail("cannot install stop intent inside existing exclusive maintenance")
  assert registry.snapshot() == {} and fence.read(registry) is None


@pytest.mark.parametrize("damage", ["launcher", "generation", "pending", "runtime-replaced", "state-lock"])
@pytest.mark.parametrize("with_snapshot", [False, True], ids=["blocking-only", "manual-snapshot"])
def test_changed_deployed_scope_before_fence_does_not_publish_intent(managed, tmp_path, monkeypatch, damage, with_snapshot):
  ws, lock, package, observed = managed
  monkeypatch.delattr(DshBackend, "runtime_guard")
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  with lifecycle.guard(ws, shared=True, create=False) as physical, Tree(ws.state_root) as state, instance_lock(state, shared=True) as state_fd:
    current = deployment.read_state(state)["current"]
    metadata = runtime.run_metadata(ws, current, runtime.decode(current["launch"], tmp_path, ()))
    run = registry.register_v2(MANAGER, metadata)
    expected = registry.snapshot()
    layout = dsh_stop_scope.inspect_deployment(ws, expected[run], instance_fd=physical, state_fd=state_fd)
    if damage == "launcher": (ws.instance / "launch.mjs").write_text("synthetic-private-canary")
    elif damage == "generation":
      path = ws.state_root / "deployment.json"
      value = json.loads(path.read_bytes()); value["current"]["generation"] = "0" * 64
      path.write_bytes(deployment.json_bytes(value))
    elif damage == "pending":
      path = ws.state_root / "pending.json"; path.write_bytes(b""); path.chmod(0o600)
    elif damage == "runtime-replaced":
      path = ws.instance / "runtimes" / lock.identity
      path.rename(path.with_name("saved-runtime")); path.mkdir(mode=0o700)
    else:
      path = ws.state_root / "instance.lock"
      path.rename(path.with_name("saved-instance.lock")); path.write_bytes(b""); path.chmod(0o600)
    events = []
    def before():
      current_layout = dsh_stop_scope.inspect_deployment(ws, expected[run], instance_fd=physical, state_fd=state_fd)
      if current_layout != layout: raise Conflict("deployed resource identity changed")
      events.append("ready-for-recovery-snapshot")
    with pytest.raises(Conflict) as caught:
      if with_snapshot:
        dsh_stop_scope.save_manual_snapshot(ws, instance_fd=physical, state_fd=state_fd,
          expected_records=expected, selected_runs=[run], expected_layout=layout,
          batch_id="a" * 32, plan_id="b" * 64, before_publish=before)
      else:
        fence.install(registry, batch_id="a" * 32, plan_id="b" * 64,
          expected_records=expected, before_publish=before)
    assert events == [] and "synthetic-private-canary" not in str(caught.value)
    assert fence.read(registry) is None and registry.snapshot() == expected
    assert fence.read_snapshot(registry, "a" * 32) is None
