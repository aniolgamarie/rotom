"""真实私人元数据与文件锁、虚构退出观察；等待成功不授予维护许可。"""

from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, run_owners
from agentcfg.control_deadline import ControlDeadline
from agentcfg.maintenance_wait import wait_for_release
from agentcfg.storage import Conflict, Tree, advisory_lock, instance_lock


@pytest.fixture
def running(tmp_path):
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    profile="synthetic-profile", binding={"machine": "synthetic-machine",
      "local": str(tmp_path / "synthetic-local.toml"), "profile": "synthetic-profile"})
  with lifecycle.guard(workspace):
    pass
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  with ExitStack() as stack:
    stack.enter_context(lifecycle.guard(workspace, shared=True, create=False))
    state = stack.enter_context(Tree(workspace.state_root, create=True))
    stack.enter_context(instance_lock(state, shared=True))
    package = tmp_path / "synthetic-package.lock"
    package.touch(mode=0o600)
    handle = stack.enter_context(package.open("rb"))
    stack.enter_context(advisory_lock(handle.fileno(), shared=True))
    targets = {}
    for index in range(3):
      manager = {"pid": 1200 + index, "birth_id": "synthetic-birth-" + str(index),
        "source": "synthetic-full-identity"}
      targets[registry.register(manager)] = manager
    yield SimpleNamespace(workspace=workspace, registry=registry, targets=targets,
      package=package, stack=stack)


def proof(run, manager):
  return run_owners.ReleaseObservation(run, deepcopy(manager), True, True)


def no_sleep(seconds):
  pytest.fail("complete observations must not sleep")


def record_to(registry):
  return lambda value: registry.finish_current(value.run_id, value.manager_identity, value)


def assert_leases_held(running):
  with pytest.raises(Conflict):
    with lifecycle.inactive_guard(running.workspace):
      pytest.fail("observer completion must not bypass physical EX")
  with Tree(running.workspace.state_root) as state, pytest.raises(Conflict):
    with instance_lock(state):
      pytest.fail("observer completion must not drop state SH")
  with running.package.open("rb") as handle, pytest.raises(Conflict):
    with advisory_lock(handle.fileno()):
      pytest.fail("observer completion must not drop package SH")


def test_persisted_complete_observations_do_not_release_manager_leases(running):
  result = wait_for_release(running.targets, deadline=ControlDeadline(clock=lambda: 0),
    observe=proof, record=record_to(running.registry), sleep=no_sleep)
  assert result.exit_code == 0 and result.pending_runs == ()
  assert set(result.confirmed_runs) == set(running.targets)
  assert all(run_owners.record_state(row) == "idle_confirmed"
    for row in running.registry.snapshot().values())
  assert_leases_held(running)
  running.stack.close()
  with lifecycle.inactive_guard(running.workspace):
    pass


def test_two_selected_observations_do_not_touch_third_or_unlock_maintenance(running):
  chosen = sorted(running.targets)[:2]
  third = next(run for run in running.targets if run not in chosen)
  untouched = running.registry.snapshot()[third]
  seen = []
  def observe(run, manager):
    seen.append(run)
    return proof(run, manager)
  result = wait_for_release({run: running.targets[run] for run in chosen},
    deadline=ControlDeadline(clock=lambda: 0), observe=observe,
    record=record_to(running.registry), sleep=no_sleep)
  assert result.exit_code == 0 and seen == chosen and result.confirmed_runs == tuple(chosen)
  assert running.registry.snapshot()[third] == untouched
  assert_leases_held(running)
  running.stack.close()
  # 即使物理锁后来空闲，未选择的第三项仍阻止维护。
  with pytest.raises(Conflict):
    with lifecycle.inactive_guard(running.workspace):
      pytest.fail("unselected active owner must survive")


def test_record_response_loss_preserves_written_fact_without_retry(running):
  selected = sorted(running.targets)
  observed, recorded = [], []
  def observe(run, manager):
    observed.append(run)
    return proof(run, manager)
  def record(value):
    recorded.append(value.run_id)
    running.registry.finish_current(value.run_id, value.manager_identity, value)
    raise OSError("synthetic private response loss")
  result = wait_for_release(running.targets, deadline=ControlDeadline(clock=lambda: 0),
    observe=observe, record=record, sleep=no_sleep)
  assert result.exit_code == 4 and result.reason == "record-unconfirmed"
  assert result.confirmed_runs == () and result.pending_runs == tuple(selected)
  assert observed == recorded == selected[:1]
  saved = running.registry.snapshot()
  assert run_owners.record_state(saved[selected[0]]) == "idle_confirmed"
  assert all(run_owners.record_state(saved[run]) == "active" for run in selected[1:])
  assert_leases_held(running)
