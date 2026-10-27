"""内部工厂使用真实私人元数据和 fake 原句柄；不启动宿主或发送信号。"""
from copy import deepcopy
import os
from types import SimpleNamespace

import pytest

from agentcfg import dsh_stop_control as control, dsh_stop_scope, run_owners as owners
from agentcfg.spawned_host import SpawnedHost
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict
from test_rotom_host_registration import HOST, handle
from test_rotom_run_records import MANAGER, RUN_ID, store, v2_record, write_record, record_bytes

# 真实临时部署/两 SH/快照 fixture；无原生宿主。单测 fake inspector 不替代此关联验证。
from test_rotom_dsh_stop_request_scope import saved
from test_rotom_dsh_stop_snapshot import prepared
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


IDENTITY = "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d"


@pytest.fixture
def case(store, handle, monkeypatch):
  monkeypatch.setattr("agentcfg.stop_locks.time.monotonic_ns", lambda: 0)
  record = v2_record(store)
  record["deployed_identity"]["runtime"] = IDENTITY
  record["host_identity"] = deepcopy(HOST)
  record["process_observation"]["host_identity"] = deepcopy(HOST)
  write_record(store, record)
  workspace = SimpleNamespace(state_root=store.registry.root.parent, binding=store.binding)
  calls = []
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", lambda *a, **kw: {"synthetic-layout": 1})
  monkeypatch.setattr(SpawnedHost, "send_sigterm_once", lambda self: calls.append("send"))
  monkeypatch.setattr(owners, "observed_process_identity", lambda pid: deepcopy(MANAGER if pid == MANAGER["pid"] else HOST["identity"]))
  fd = os.open(store.cwd, os.O_RDONLY | os.O_DIRECTORY)
  try:
    yield SimpleNamespace(ws=workspace, store=store, host=handle, fd=fd, calls=calls)
  finally:
    os.close(fd)


def make(case):
  return control.factory_for(case.ws, instance_fd=case.fd, state_fd=case.fd)(run_id=RUN_ID, host=case.host)


def request():
  return {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop", "request_id": "d" * 32,
    "batch_id": "e" * 32, "plan_id": "f" * 64, "run_id": RUN_ID,
    "manager_identity": deepcopy(MANAGER), "host_identity": deepcopy(HOST["identity"]), "deadline_ns": 1}


def test_factory_binds_original_endpoint_and_keeps_channel_read_only(case):
  service = make(case)
  assert type(service) is StopService and service.belongs_to(RUN_ID, case.host)
  record = case.store.registry.snapshot()[RUN_ID]
  before = record_bytes(case.store)
  with case.store.registry._locked(nonblocking=True):
    state = control.channel_state(case.ws, record)
  assert state == {"endpoint": service.describe(), "requests": [], "dispatch": None}
  assert control.available(case.ws, record) is True
  state["endpoint"]["nonce"] = "a" * 32
  assert service.describe()["nonce"] != "a" * 32
  assert record_bytes(case.store) == before and not case.calls
  os.fstat(case.fd)


@pytest.mark.parametrize("change", ["platform", "runtime", "agent", "backend", "domain"])
def test_supported_is_exact_static_combination(case, monkeypatch, change):
  record = case.store.registry.snapshot()[RUN_ID]
  assert control.supported(record) is True
  if change == "platform": monkeypatch.setattr(control.sys, "platform", "darwin")
  elif change == "runtime": record["deployed_identity"]["runtime"] = "c" * 64
  elif change == "agent": record["agent"] = "unsupported"
  elif change == "backend": record["backend"] = "ssh"
  else: record["coordination_domain"] = {}
  assert control.supported(record) is False


@pytest.mark.parametrize("change", ["wrong-run", "host-dict", "host-drift", "closed-fd", "unsupported"])
def test_factory_refuses_before_creating_inbox(case, monkeypatch, change):
  callback = control.factory_for(case.ws, instance_fd=case.fd, state_fd=case.fd)
  run, host = RUN_ID, case.host
  if change == "wrong-run": run = "b" * 32
  elif change == "host-dict": host = deepcopy(HOST)
  elif change == "host-drift": monkeypatch.setattr(SpawnedHost, "snapshot", lambda self: {**deepcopy(HOST), "source": "other"})
  elif change == "closed-fd":
    other = os.dup(case.fd); os.close(other)
    with pytest.raises(Conflict): control.factory_for(case.ws, instance_fd=other, state_fd=case.fd)
    return
  else: monkeypatch.setattr(control.sys, "platform", "darwin")
  with pytest.raises(Conflict): callback(run_id=run, host=host)
  assert not (case.ws.state_root / "stop-inboxes").exists() and not case.calls


def test_verify_requires_reviewed_stop_and_exact_registered_record(case, monkeypatch):
  service = make(case)
  calls = []
  def inspect(ws, value, **kwargs):
    calls.append((ws, value, kwargs))
    return case.store.registry.snapshot()[RUN_ID]
  monkeypatch.setattr(dsh_stop_scope, "inspect_stop_request", inspect)
  assert service._verify_request(request()) is True
  assert calls[0][2] == {"instance_fd": case.fd, "state_fd": case.fd,
    "expected_layout": {"synthetic-layout": 1}, "require_reviewed_stop": True}
  record = case.store.registry.snapshot()[RUN_ID]
  record["start_cwd"]["observed_at_ns"] += 1
  write_record(case.store, record)
  with pytest.raises(Conflict): service._verify_request(request())
  assert not case.calls


@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt, SystemExit])
def test_bind_failure_closes_service_without_closing_host(case, monkeypatch, failure):
  saved = []
  original = StopService.close
  def close(self): saved.append(self); original(self)
  monkeypatch.setattr(StopService, "close", close)
  error = failure("synthetic-private-canary")
  def fail(*a, **kw): raise error
  monkeypatch.setattr(owners.Registry, "bind_current_control", fail)
  with pytest.raises(Conflict if failure is ValueError else failure) as caught: make(case)
  if failure is not ValueError: assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  assert len(saved) == 1 and not saved[0].belongs_to(RUN_ID, case.host)
  assert case.host.snapshot() == HOST and not case.calls


@pytest.mark.parametrize("change", ["unknown", "manager", "host", "endpoint", "request", "dispatch"])
def test_available_does_not_upgrade_historical_or_pending_state(case, monkeypatch, change):
  service = make(case)
  record = case.store.registry.snapshot()[RUN_ID]
  if change == "unknown": owners._set_state(record, "unknown")
  elif change in ("manager", "host"):
    target = MANAGER["pid"] if change == "manager" else HOST["identity"]["pid"]
    original = owners.observed_process_identity
    monkeypatch.setattr(owners, "observed_process_identity", lambda pid: None if pid == target else original(pid))
  elif change == "endpoint":
    value = service.describe(); value["nonce"] = "b" * 32
    (service._inbox.root / "endpoint.json").write_bytes(owners._encode(value))
  elif change == "request": service._inbox.submit(request(), expected=service.describe())
  else: service._handler._journal.begin(request())
  assert control.available(case.ws, record) is False and not case.calls


def test_channel_reads_sorted_requests_without_current_manager_or_writes(case, monkeypatch):
  service = make(case)
  record = case.store.registry.snapshot()[RUN_ID]
  for ident in ("f" * 32, "a" * 32):
    value = request(); value["request_id"] = ident
    service._inbox.submit(value, expected=service.describe())
  monkeypatch.setattr(owners, "current_process_identity", lambda: pytest.fail("历史读取不能要求当前 manager"))
  before = {p.relative_to(case.ws.state_root): p.read_bytes() for p in case.ws.state_root.rglob("*") if p.is_file()}
  with case.store.registry._locked(nonblocking=True):
    result = control.channel_state(case.ws, record)
  assert [value["request_id"] for value in result["requests"]] == ["a" * 32, "f" * 32]
  assert before == {p.relative_to(case.ws.state_root): p.read_bytes() for p in case.ws.state_root.rglob("*") if p.is_file()}
  assert not case.calls


@pytest.mark.parametrize("stage", ["owner", "inbox"])
def test_busy_metadata_factory_deadline_or_inbox_nb_never_grants_availability(case, stage, monkeypatch):
  if stage == "owner":
    # 新工厂允许期限内等 owner；可前进时钟核验到期零端点/写入，不死等。
    ticks = iter((0, 0, 2_000_000_001))
    monkeypatch.setattr("agentcfg.stop_locks.time.monotonic_ns", lambda: next(ticks, 2_000_000_001))
    before = record_bytes(case.store)
    with case.store.registry._locked(nonblocking=True):
      with pytest.raises(Conflict): make(case)
    assert not (case.ws.state_root / "stop-inboxes").exists()
    assert record_bytes(case.store) == before and not case.calls
  else:
    service = make(case)
    record = case.store.registry.snapshot()[RUN_ID]
    with service._inbox._registry._locked(nonblocking=True):
      assert control.available(case.ws, record) is False
      with pytest.raises(Conflict): control.channel_state(case.ws, record)


@pytest.mark.parametrize("damage", ["missing-reviewed-fence", "close-marker"])
def test_service_never_sends_when_reviewed_chain_rejects(case, monkeypatch, damage):
  service = make(case)
  def inspect(*a, **kw):
    assert kw["require_reviewed_stop"] is True
    raise Conflict("synthetic-private-canary-" + damage)
  monkeypatch.setattr(dsh_stop_scope, "inspect_stop_request", inspect)
  service._inbox.submit(request(), expected=service.describe())
  service._handler._clock = lambda: 0
  with pytest.raises(Conflict) as caught: service()
  assert "synthetic-private-canary" not in str(caught.value)
  assert not service.belongs_to(RUN_ID, case.host) and not case.calls
  assert not service._handler._journal.root.exists()


def test_post_bind_read_failure_closes_service_and_preserves_committed_descriptor(case, monkeypatch):
  original = owners.Registry.bind_current_control
  services = []
  def bind(registry, run_id, host, service, *, deadline_ns=None):
    services.append(service)
    original(registry, run_id, host, service, **({} if deadline_ns is None else {"deadline_ns": deadline_ns}))
    def fail(*a, **kw): raise ValueError("synthetic-private-canary")
    monkeypatch.setattr(control, "_current", fail)
  monkeypatch.setattr(owners.Registry, "bind_current_control", bind)
  with pytest.raises(Conflict) as caught: make(case)
  assert "synthetic-private-canary" not in str(caught.value)
  assert len(services) == 1 and not services[0].belongs_to(RUN_ID, case.host)
  assert case.store.registry.snapshot()[RUN_ID]["protocol"]["control"] is not None
  assert case.host.snapshot() == HOST and not case.calls


def test_record_drift_after_preview_prevents_binding(case, monkeypatch):
  def inspect(*a, **kw):
    record = case.store.registry.snapshot()[RUN_ID]
    owners._set_state(record, "unknown")
    write_record(case.store, record)
    return {"synthetic-layout": 1}
  monkeypatch.setattr(dsh_stop_scope, "inspect_deployment", inspect)
  with pytest.raises(Conflict): make(case)
  assert case.store.registry.snapshot()[RUN_ID]["protocol"]["control"] is None
  assert not case.calls


@pytest.mark.parametrize("error", [KeyboardInterrupt("synthetic-private-canary"), SystemExit(7)])
def test_read_only_control_exceptions_are_not_changed(case, monkeypatch, error):
  service = make(case)
  record = case.store.registry.snapshot()[RUN_ID]
  def fail(*a, **kw): raise error
  monkeypatch.setattr(StopInbox, "_load", fail)
  for callback in (lambda: control.channel_state(case.ws, record), lambda: control.available(case.ws, record)):
    with pytest.raises(type(error)) as caught: callback()
    assert caught.value is error
  assert service.belongs_to(RUN_ID, case.host) and not case.calls


def test_invalid_null_descriptor_and_missing_root_are_not_created(case):
  record = case.store.registry.snapshot()[RUN_ID]
  before = record_bytes(case.store)
  with pytest.raises(Conflict): control.channel_state(case.ws, record)
  assert control.available(case.ws, record) is False
  assert record_bytes(case.store) == before
  assert not (case.ws.state_root / "stop-inboxes").exists()


@pytest.mark.parametrize("identity", ["manager", "host"])
def test_available_rechecks_identity_after_channel_read(case, monkeypatch, identity):
  make(case)
  record = case.store.registry.snapshot()[RUN_ID]
  original = control.channel_state
  target = MANAGER["pid"] if identity == "manager" else HOST["identity"]["pid"]
  before = owners.observed_process_identity
  def channel(*a, **kw):
    result = original(*a, **kw)
    monkeypatch.setattr(owners, "observed_process_identity", lambda pid: None if pid == target else before(pid))
    return result
  monkeypatch.setattr(control, "channel_state", channel)
  assert control.available(case.ws, record) is False and not case.calls




def test_real_manual_snapshot_is_not_a_reviewed_stop_request(saved):
  ws, registry, args, runs, value = saved
  with pytest.raises(Conflict):
    dsh_stop_scope.inspect_stop_request(ws, value, instance_fd=args["instance_fd"], state_fd=args["state_fd"],
      expected_layout=args["expected_layout"], require_reviewed_stop=True)


def test_locked_availability_reuses_owner_lock_without_reentry(case, monkeypatch):
  make(case)
  record = case.store.registry.snapshot()[RUN_ID]
  original = owners.Registry._locked
  paths = []
  def locked(registry, **kwargs):
    paths.append(registry.root)
    return original(registry, **kwargs)
  with case.store.registry._locked(nonblocking=True):
    monkeypatch.setattr(owners.Registry, "_locked", locked)
    assert control.available_locked(case.ws, record) is True
  assert case.store.registry.root not in paths
  assert control.available(case.ws, record) is True
  assert paths.count(case.store.registry.root) == 1
