"""启动/停止入口只在第一次元数据操作前等短锁；真实独立 FD，无宿主。"""
from contextlib import contextmanager, ExitStack
import fcntl
import os
import threading
import time

import pytest

from agentcfg import dsh_stop, dsh_stop_control as control, dsh_stop_scope, run_stop_fence
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_stop_control_factory import case, make
from test_rotom_host_registration import handle
from test_rotom_run_records import store, RUN_ID, record_bytes
from test_rotom_dsh_reviewed_snapshot import candidate, save, consume
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


_REAL_NS = time.monotonic_ns


@contextmanager
def owner_lock(root, *, release=False):
  fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  timer = None
  released = threading.Event()
  fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  def unlock():
    fcntl.flock(fd, fcntl.LOCK_UN)
    released.set()
  try:
    if release:
      timer = threading.Timer(0.05, unlock)
      timer.start()
    yield released
  finally:
    if timer is not None:
      timer.cancel()
      timer.join()
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@pytest.fixture
def real_case_clock(case, monkeypatch):
  # 复用夹具的请求时钟为0；本组真实锁等待单独使用可前进的单调时钟。
  monkeypatch.setattr(time, "monotonic_ns", _REAL_NS)
  return case


def test_factory_first_owner_read_waits_once_for_query(real_case_clock):
  state = real_case_clock
  with owner_lock(state.store.registry.root, release=True) as released:
    service = make(state)
  try:
    assert released.is_set() and service.belongs_to(RUN_ID, state.host)
    assert state.store.registry.snapshot()[RUN_ID]["protocol"]["control"]["endpoint"] == service.describe()
    assert not state.calls
  finally:
    service.close()


def test_factory_bind_waits_after_single_layout_inspection(real_case_clock, monkeypatch):
  state = real_case_clock
  inspections = []
  with ExitStack() as stack:
    def inspect(*args, **kwargs):
      inspections.append(True)
      stack.enter_context(owner_lock(state.store.registry.root, release=True))
      return {"synthetic-layout": 1}
    monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
    service = make(state)
  try:
    assert inspections == [True]
    assert state.store.registry.snapshot()[RUN_ID]["protocol"]["control"]["endpoint"] == service.describe()
    assert not state.calls
  finally:
    service.close()


def service_for(state):
  inbox, journal = control._stores(state.ws, RUN_ID, wait_for_lock=True)
  return StopService(RUN_ID, state.host, inbox=inbox, journal=journal, verify=lambda value: True)


@pytest.mark.parametrize("budget_ns", [-1, 20_000_000])
def test_bind_expired_deadline_does_not_write_or_close_host(real_case_clock, monkeypatch, budget_ns):
  state = real_case_clock
  service = service_for(state)
  before = record_bytes(state.store)
  monkeypatch.setattr(Tree, "replace", lambda *args, **kwargs: pytest.fail("expired binding wrote"))
  try:
    with owner_lock(state.store.registry.root):
      with pytest.raises(Conflict):
        state.store.registry.bind_current_control(RUN_ID, state.host, service, deadline_ns=_REAL_NS() + budget_ns)
    assert record_bytes(state.store) == before and service.belongs_to(RUN_ID, state.host)
    assert not state.calls
  finally:
    service.close()


def test_binding_write_ack_failure_is_not_replayed(real_case_clock, monkeypatch):
  state = real_case_clock
  service = service_for(state)
  writes = []
  original = Tree.replace
  def replace(tree, name, data, **kwargs):
    writes.append(name)
    original(tree, name, data, **kwargs)
    raise OSError("synthetic acknowledgement lost")
  monkeypatch.setattr(Tree, "replace", replace)
  try:
    with pytest.raises(Conflict):
      state.store.registry.bind_current_control(RUN_ID, state.host, service, deadline_ns=_REAL_NS() + 1_000_000_000)
    assert writes == [RUN_ID + ".json"]
    assert state.store.registry.snapshot()[RUN_ID]["protocol"]["control"]["endpoint"] == service.describe()
    assert not state.calls
  finally:
    service.close()


def test_capture_owner_query_contention_does_not_repeat_layout(prepared, monkeypatch):
  ws, registry, args, runs = prepared
  inspections = []
  original = dsh_stop_scope.inspect_deployment
  def inspect(*values, **kwargs):
    inspections.append(True)
    return original(*values, **kwargs)
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
  before = registry.snapshot()
  with owner_lock(registry.root, release=True) as released:
    result, records, _ = dsh_stop.capture_stop(ws, selected_runs=runs[:2])
  assert released.is_set() and result["plan"]["selected_runs"] == sorted(runs[:2])
  assert records == before and inspections == [True, True]
  assert run_stop_fence.read(registry) is None


def test_available_locked_waits_for_inbox_read_without_granting_signals(real_case_clock):
  state = real_case_clock
  service = make(state)
  try:
    record = state.store.registry.snapshot()[RUN_ID]
    with state.store.registry._locked(nonblocking=True):
      with owner_lock(service._inbox.root, release=True) as released:
        assert control.available_locked(state.ws, record, deadline_ns=_REAL_NS() + 1_000_000_000)
    assert released.is_set() and not state.calls
  finally:
    service.close()


def test_reviewed_snapshot_waits_before_consuming_original_review(candidate):
  prepared, plan, review = candidate
  ws, registry, args, runs = prepared
  with owner_lock(registry.root, release=True) as released:
    save(candidate, deadline_ns=_REAL_NS() + 1_000_000_000)
  assert released.is_set()
  assert run_stop_fence.read_snapshot(registry, args["batch_id"])["plan"] == plan
  assert run_stop_fence.read(registry)["plan_id"] == plan["plan_id"]
  with pytest.raises(Conflict): consume(candidate)


@pytest.mark.parametrize("budget_ns", [-1, 20_000_000])
def test_expired_snapshot_does_not_consume_review_or_publish(candidate, monkeypatch, budget_ns):
  prepared, _, _ = candidate
  _, registry, args, _ = prepared
  monkeypatch.setattr(Tree, "write_new", lambda *args, **kwargs: pytest.fail("expired snapshot wrote"))
  with owner_lock(registry.root):
    with pytest.raises(Conflict): save(candidate, deadline_ns=_REAL_NS() + budget_ns)
  assert run_stop_fence.read(registry) is None
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is None
  consume(candidate)


def test_snapshot_write_ack_failure_keeps_once_consumed_review(candidate, monkeypatch):
  prepared, _, _ = candidate
  _, registry, args, _ = prepared
  original = Tree.write_new
  writes = []
  def write(tree, name, data):
    writes.append(name)
    original(tree, name, data)
    raise OSError("synthetic acknowledgement lost")
  monkeypatch.setattr(Tree, "write_new", write)
  with pytest.raises(Conflict): save(candidate, deadline_ns=_REAL_NS() + 1_000_000_000)
  assert writes == [run_stop_fence._snapshot_name(registry, args["batch_id"])]
  assert run_stop_fence.read_snapshot(registry, args["batch_id"]) is not None
  assert run_stop_fence.read(registry) is None
  with pytest.raises(Conflict): consume(candidate)


def test_scope_discovery_waits_for_owner_query_without_repeating_candidates(prepared, monkeypatch):
  ws, registry, _, runs = prepared
  calls = []
  monkeypatch.setattr("agentcfg.local.available_profiles", lambda: [(ws.profile, ws.agent)])
  def workspaces(local, profiles):
    calls.append((local, profiles))
    return (ws,)
  monkeypatch.setattr("agentcfg.workspace.load_instance_workspaces", workspaces)
  with owner_lock(registry.root, release=True) as released:
    assert dsh_stop.workspace_for_scope(ws.local_path, selected_runs=runs[:2], profile=ws.profile) is ws
  assert released.is_set() and calls == [(ws.local_path, [ws.profile])]
  assert run_stop_fence.read(registry) is None


def test_factory_expired_owner_wait_does_not_create_endpoint_or_change_owner(real_case_clock, monkeypatch):
  state = real_case_clock
  before = record_bytes(state.store)
  ticks = iter((0, 0, 0, 2_000_000_001))
  monkeypatch.setattr(time, "monotonic_ns", lambda: next(ticks, 2_000_000_001))
  with owner_lock(state.store.registry.root):
    with pytest.raises(Conflict): make(state)
  assert record_bytes(state.store) == before
  assert not (state.ws.state_root / "stop-inboxes").exists() and not state.calls


@pytest.fixture
def unbound_host(store, handle):
  from test_rotom_run_records import v2_record, write_record
  write_record(store, v2_record(store))
  return store, handle


def test_host_binding_waits_for_query_then_preserves_manager_and_control(unbound_host):
  from test_rotom_host_registration import HOST
  state, host = unbound_host
  before = state.registry.snapshot()[RUN_ID]
  with owner_lock(state.registry.root, release=True) as released:
    assert state.registry.bind_current_host(RUN_ID, host) is None
  after = state.registry.snapshot()[RUN_ID]
  assert released.is_set() and after["host_identity"] == HOST
  assert after["manager_identity"] == before["manager_identity"]
  assert after["protocol"] == before["protocol"] and after["lifecycle_state"] == "active"
  assert host.snapshot() == HOST


def test_host_binding_wait_deadline_keeps_owner_bytes_and_original_host(unbound_host, monkeypatch):
  from test_rotom_host_registration import HOST
  state, host = unbound_host
  before = record_bytes(state)
  ticks = iter((0, 0, 0, 2_000_000_001))
  monkeypatch.setattr(time, "monotonic_ns", lambda: next(ticks, 2_000_000_001))
  monkeypatch.setattr(Tree, "replace", lambda *args, **kwargs: pytest.fail("expired host bind wrote"))
  with owner_lock(state.registry.root):
    with pytest.raises(Conflict): state.registry.bind_current_host(RUN_ID, host)
  assert record_bytes(state) == before and host.snapshot() == HOST


def test_host_binding_write_ack_failure_keeps_one_commit_without_replay(unbound_host, monkeypatch):
  from test_rotom_host_registration import HOST
  state, host = unbound_host
  original = Tree.replace
  writes = []
  def replace(tree, name, data, **kwargs):
    writes.append(name)
    original(tree, name, data, **kwargs)
    raise OSError("synthetic host binding acknowledgement lost")
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict): state.registry.bind_current_host(RUN_ID, host)
  assert writes == [RUN_ID + ".json"]
  assert state.registry.snapshot()[RUN_ID]["host_identity"] == HOST and host.snapshot() == HOST
  with pytest.raises(Conflict): state.registry.bind_current_host(RUN_ID, host)
  assert writes == [RUN_ID + ".json"]
