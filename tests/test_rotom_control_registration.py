"""停止 endpoint 描述登记；临时元数据与 fake 原句柄，不启动宿主或发送信号。"""
from copy import deepcopy

import pytest

from agentcfg import run_owners as owners
from agentcfg.spawned_host import SpawnedHost
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict, Tree
from test_rotom_host_registration import HOST, handle
from test_rotom_run_records import MANAGER, RUN_ID, record_bytes, store, v2_record, write_record


@pytest.fixture
def registered(store, handle, tmp_path, monkeypatch):
  record = v2_record(store)
  record["host_identity"] = deepcopy(HOST)
  record["process_observation"]["host_identity"] = deepcopy(HOST)
  write_record(store, record)
  inbox = StopInbox(tmp_path / "control-inbox", store.binding)
  journal = StopDispatches(tmp_path / "control-journal", store.binding)
  service = StopService(RUN_ID, handle, inbox=inbox, journal=journal,
    verify=lambda request: pytest.fail("登记不能请求批准"))
  monkeypatch.setattr(SpawnedHost, "send_sigterm_once", lambda self: pytest.fail("登记不能发送信号"))
  return store, handle, service, inbox, journal


def control_record(registered):
  store, host, service, inbox, journal = registered
  result = store.registry.snapshot()[RUN_ID]
  result["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": inbox.describe()}
  return result


def test_bind_records_only_detached_endpoint_without_starting_control(registered):
  store, host, service, inbox, journal = registered
  before = store.registry.snapshot()[RUN_ID]
  assert store.registry.bind_current_control(RUN_ID, host, service) is None
  record = store.registry.snapshot()[RUN_ID]
  expected = deepcopy(before)
  expected["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": inbox.describe()}
  assert record == expected and record["protocol"]["registration"] == 2
  assert record["session_observation"] is None and record["session_cwd"] is None
  assert not journal.root.exists()
  assert set(path.name for path in inbox.root.iterdir()) == {"endpoint.json"}
  assert "path" not in record["protocol"]["control"]["endpoint"]


def test_service_description_is_detached_read_only_and_releases_inbox_lock(registered):
  store, host, service, inbox, journal = registered
  before = {p.name: p.read_bytes() for p in inbox.root.iterdir()}
  value = service.describe()
  assert value == inbox.describe()
  value["manager_identity"]["pid"] = 99
  assert service.describe()["manager_identity"] == MANAGER
  with inbox._registry._locked(nonblocking=True):
    pass
  assert {p.name: p.read_bytes() for p in inbox.root.iterdir()} == before
  assert not journal.root.exists() and service.belongs_to(RUN_ID, host) is True


@pytest.mark.parametrize("state", ["active", "unknown", "idle_confirmed"])
def test_codec_keeps_null_and_historical_control_metadata_without_live_permission(registered, state):
  store, host, service, inbox, journal = registered
  record = control_record(registered)
  owners._set_state(record, state)
  store.registry._validate_record(RUN_ID + ".json", record)
  record["protocol"]["control"] = None
  store.registry._validate_record(RUN_ID + ".json", record)


@pytest.mark.parametrize("change", ["extra", "kind", "version-bool", "run", "binding", "manager", "host",
  "nonce", "nonce-upper", "physical-extra", "device-bool", "device-float", "device-negative", "inode-zero",
  "pid-bool", "birth-long", "endpoint-path", "descriptor-extra", "same-pid", "source", "relationship", "pi", "omp", "ssh"])
def test_codec_rejects_unmatched_or_unreviewed_control_description(registered, change):
  store, *_ = registered
  record = control_record(registered)
  value = record["protocol"]["control"]
  endpoint = value["endpoint"]
  if change == "extra": endpoint["extra"] = True
  elif change == "kind": endpoint["kind"] = "other"
  elif change == "version-bool": endpoint["schema_version"] = True
  elif change == "run": endpoint["run_id"] = "b" * 32
  elif change == "binding": endpoint["binding_digest"] = "b" * 64
  elif change == "manager": endpoint["manager_identity"]["birth_id"] = "other"
  elif change == "host": endpoint["host_identity"]["birth_id"] = "other"
  elif change == "nonce": endpoint["nonce"] = "not-hex"
  elif change == "nonce-upper": endpoint["nonce"] = "A" * 32
  elif change == "physical-extra": endpoint["physical"]["path"] = "synthetic-private-canary"
  elif change.startswith("device-"):
    endpoint["physical"]["device"] = {"device-bool": True, "device-float": 1.0, "device-negative": -1}[change]
  elif change == "inode-zero": endpoint["physical"]["inode"] = 0
  elif change == "pid-bool": endpoint["manager_identity"]["pid"] = True
  elif change == "birth-long": endpoint["host_identity"]["birth_id"] = "x" * 513
  elif change == "endpoint-path": endpoint["path"] = "synthetic-private-canary"
  elif change == "descriptor-extra": value["path"] = "synthetic-private-canary"
  elif change == "same-pid":
    endpoint["host_identity"] = deepcopy(MANAGER)
    record["host_identity"]["identity"] = deepcopy(MANAGER)
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
  elif change in ("source", "relationship"):
    record["host_identity"][change] = "other"
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
  elif change in ("pi", "omp"):
    record["agent"] = change
    record["native_home_ref"]["kind"] = "pi-home" if change == "pi" else "omp-managed-home"
  elif change == "ssh": record["backend"] = "ssh"
  with pytest.raises(Conflict) as caught:
    store.registry._validate_record(RUN_ID + ".json", record)
  assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("change", ["missing", "unknown", "idle", "pi", "omp", "ssh", "unbound-host", "current-manager"])
def test_bind_requires_this_active_managed_dsh_owner(registered, monkeypatch, change):
  store, host, service, inbox, journal = registered
  record = store.registry.snapshot()[RUN_ID]
  run = RUN_ID
  if change == "missing": run = "b" * 32
  elif change in ("unknown", "idle"): owners._set_state(record, "unknown" if change == "unknown" else "idle_confirmed")
  elif change in ("pi", "omp"):
    record["agent"] = change
    record["native_home_ref"]["kind"] = "pi-home" if change == "pi" else "omp-managed-home"
  elif change == "ssh": record["backend"] = "ssh"
  elif change == "unbound-host":
    record["host_identity"] = None
    record["process_observation"]["host_identity"] = None
  elif change == "current-manager": monkeypatch.setattr(owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "other"})
  write_record(store, record)
  before = record_bytes(store)
  with pytest.raises(Conflict): store.registry.bind_current_control(run, host, service)
  assert record_bytes(store) == before and not journal.root.exists()


@pytest.mark.parametrize("change", ["host-dict", "service-dict", "other-host", "closed", "failed", "endpoint-drift", "host-drift"])
def test_bind_refuses_reconstruction_or_inactive_service_without_writes(registered, monkeypatch, change):
  store, host, service, inbox, journal = registered
  if change == "host-dict": host = deepcopy(HOST)
  elif change == "service-dict": service = {"endpoint": inbox.describe()}
  elif change == "other-host": host = object.__new__(SpawnedHost)
  elif change == "closed": service.close()
  elif change == "failed":
    monkeypatch.setattr(StopInbox, "pending", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic-private-canary")))
    with pytest.raises(Conflict): service()
  elif change == "endpoint-drift":
    path = inbox.root / "endpoint.json"
    value = inbox.describe()
    value["nonce"] = "b" * 32
    path.write_bytes(owners._encode(value))
  elif change == "host-drift":
    monkeypatch.setattr(SpawnedHost, "snapshot", lambda self: {**deepcopy(HOST), "identity": {"pid": 13371339, "birth_id": "other"}})
  before = record_bytes(store)
  with pytest.raises(Conflict) as caught: store.registry.bind_current_control(RUN_ID, host, service)
  assert "synthetic-private-canary" not in str(caught.value)
  assert record_bytes(store) == before


def test_bind_is_single_use_and_owner_lock_is_nonblocking(registered):
  store, host, service, inbox, journal = registered
  before = record_bytes(store)
  with store.registry._locked():
    with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, host, service)
  assert record_bytes(store) == before
  store.registry.bind_current_control(RUN_ID, host, service)
  bound = record_bytes(store)
  with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, host, service)
  assert record_bytes(store) == bound


@pytest.mark.parametrize("stage", ["before", "after"])
def test_write_failure_preserves_whichever_fact_committed_without_retry(registered, monkeypatch, stage):
  store, host, service, inbox, journal = registered
  original = Tree.replace
  calls = []
  def replace(tree, name, data, **kwargs):
    calls.append(name)
    if stage == "before": raise OSError("synthetic-private-canary")
    original(tree, name, data, **kwargs)
    raise OSError("synthetic-private-canary")
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict) as caught: store.registry.bind_current_control(RUN_ID, host, service)
  assert len(calls) == 1 and "synthetic-private-canary" not in str(caught.value)
  record = store.registry.snapshot()[RUN_ID]
  assert (record["protocol"]["control"] is not None) == (stage == "after")


@pytest.mark.parametrize("action", ["unknown", "finish"])
def test_exit_observation_retains_description_without_reviving_service(registered, action):
  store, host, service, inbox, journal = registered
  store.registry.bind_current_control(RUN_ID, host, service)
  saved = store.registry.snapshot()[RUN_ID]["protocol"]["control"]
  service.close()
  if action == "unknown": store.registry.mark_unknown(RUN_ID, MANAGER)
  else: store.registry.finish_current(RUN_ID, MANAGER, owners.ReleaseObservation(RUN_ID, MANAGER, True, True))
  assert store.registry.snapshot()[RUN_ID]["protocol"]["control"] == saved
  assert not service.belongs_to(RUN_ID, host)
  with pytest.raises(Conflict): service.describe()
  assert not journal.root.exists()


def test_coordinated_omp_null_stays_readable_but_control_binding_is_refused(registered):
  store, host, service, inbox, journal = registered
  record = store.registry.snapshot()[RUN_ID]
  record["agent"] = "omp"
  record["native_home_ref"]["kind"] = "omp-managed-home"
  record["coordination_domain"] = {"protocol": "rotom-owner-link-v1", "domain_id": "d" * 32,
    "domain_physical": {"device": 1, "inode": 2}, "op_id": "e" * 32, "link_digest": "f" * 64}
  store.registry._validate_record(RUN_ID + ".json", record)
  write_record(store, record)
  before = record_bytes(store)
  with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, host, service)
  assert record_bytes(store) == before
  record["protocol"]["control"] = {"kind": "linux-pidfd-stop-v1", "endpoint": inbox.describe()}
  with pytest.raises(Conflict): store.registry._validate_record(RUN_ID + ".json", record)


def test_inbox_lock_contention_refuses_binding_without_owner_change(registered):
  store, host, service, inbox, journal = registered
  before = record_bytes(store)
  with inbox._registry._locked(nonblocking=True):
    with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, host, service)
  assert record_bytes(store) == before and not journal.root.exists()


def test_describe_busy_does_not_unlock_another_holder_or_leave_service_live(registered):
  store, host, service, inbox, journal = registered
  service._lock.acquire()
  try:
    with pytest.raises(Conflict): service.describe()
    assert service._lock.locked()
  finally:
    service._lock.release()
  assert service.belongs_to(RUN_ID, host) is False


@pytest.mark.parametrize("change", ["service-close", "host", "manager-pid"])
def test_state_change_during_description_prevents_cas(registered, monkeypatch, change):
  store, host, service, inbox, journal = registered
  original = StopService.describe
  def describe(self):
    value = original(self)
    if change == "service-close": self.close()
    elif change == "host": monkeypatch.setattr(SpawnedHost, "snapshot", lambda self: {**deepcopy(HOST), "identity": {"pid": 13371339, "birth_id": "other"}})
    else: monkeypatch.setattr(owners, "current_process_identity", lambda: {**MANAGER, "pid": MANAGER["pid"] + 1})
    return value
  monkeypatch.setattr(StopService, "describe", describe)
  before = record_bytes(store)
  with pytest.raises(Conflict): store.registry.bind_current_control(RUN_ID, host, service)
  assert record_bytes(store) == before


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("stage", ["bind", "describe"])
def test_control_exception_preserves_identity_and_releases_metadata_locks(registered, monkeypatch, kind, stage):
  store, host, service, inbox, journal = registered
  error = kind("synthetic-private-canary")
  def interrupted(*args, **kwargs): raise error
  before = record_bytes(store)
  if stage == "bind":
    monkeypatch.setattr(StopService, "describe", interrupted)
    operation = lambda: store.registry.bind_current_control(RUN_ID, host, service)
  else:
    monkeypatch.setattr(StopInbox, "describe", interrupted)
    operation = service.describe
  with pytest.raises(kind) as caught: operation()
  assert caught.value is error and record_bytes(store) == before
  with store.registry._locked(nonblocking=True):
    pass
  assert not service._lock.locked() and not journal.root.exists()
