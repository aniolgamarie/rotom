"""仅由当次管理器记录启动句柄；记录仍不授予控制能力。"""

from copy import deepcopy

import pytest

from agentcfg import run_owners as owners, spawned_host
from agentcfg.storage import Conflict, Tree
from test_rotom_run_records import MANAGER, RUN_ID, store, v2_record, write_record, record_bytes


HOST = {"identity": {"pid": 13371338, "birth_id": "linux:00000000-0000-4000-8000-000000000001:333"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}


@pytest.fixture
def handle(monkeypatch):
  # 内核句柄自身由独立 fake 内核测试覆盖；此处只替换它的现场核验方法。
  item = object.__new__(spawned_host.SpawnedHost)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: deepcopy(HOST))
  monkeypatch.setattr(owners, "current_process_identity", lambda: deepcopy(MANAGER))
  return item


def test_bind_preserves_complete_record_and_other_runs_without_control(store, handle):
  original = v2_record(store)
  write_record(store, original)
  other = deepcopy(original)
  other["run_id"] = "d" * 32
  with Tree(store.registry.root) as tree:
    tree.write_new(other["run_id"] + ".json", owners._encode(other))
  assert store.registry.bind_current_host(RUN_ID, handle) is None
  records = store.registry.snapshot()
  bound = records[RUN_ID]
  assert bound["host_identity"] == HOST
  assert bound["process_observation"]["host_identity"] == HOST
  assert bound["protocol"]["control"] is None
  assert bound["lifecycle_state"] == "active" and bound["session_observation"] is None
  expected = deepcopy(original)
  expected["host_identity"] = deepcopy(HOST)
  expected["process_observation"]["host_identity"] = deepcopy(HOST)
  expected["process_observation"]["observed_at_ns"] = bound["process_observation"]["observed_at_ns"]
  assert bound == expected and records[other["run_id"]] == other


def test_attached_host_observation_uses_current_observation_time(store, handle, monkeypatch):
  write_record(store, v2_record(store))
  monkeypatch.setattr(owners.time, "time_ns", lambda: 123456)
  store.registry.bind_current_host(RUN_ID, handle)
  assert store.registry.snapshot()[RUN_ID]["process_observation"]["observed_at_ns"] == 123456


def test_busy_owner_skips_optional_observation_without_waiting(store, handle):
  write_record(store, v2_record(store))
  before = record_bytes(store)
  with store.registry._locked():
    with pytest.raises(Conflict):
      store.registry.bind_current_host(RUN_ID, handle)
  assert record_bytes(store) == before


def test_root_replaced_during_host_observation_cannot_receive_updated_record(store, handle, monkeypatch):
  path = write_record(store, v2_record(store))
  before = path.read_bytes()
  moved = store.registry.root.with_name("old-owner-root")
  def snapshot(self):
    store.registry.root.rename(moved)
    store.registry.root.mkdir(mode=0o700)
    return deepcopy(HOST)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", snapshot)
  with pytest.raises(Conflict):
    store.registry.bind_current_host(RUN_ID, handle)
  assert record_bytes(store) == {} and (moved / path.name).read_bytes() == before


@pytest.mark.parametrize("change", ["missing", "v1", "unknown", "idle", "bound", "omp", "ssh", "manager"])
def test_noneligible_owner_does_not_change(store, handle, change):
  record = v2_record(store)
  if change == "v1":
    run_id = store.registry.register(MANAGER)
  else:
    run_id = RUN_ID
    if change in ("unknown", "idle"):
      owners._set_state(record, "unknown" if change == "unknown" else "idle_confirmed")
    elif change == "bound":
      record["host_identity"] = deepcopy(HOST)
      record["process_observation"]["host_identity"] = deepcopy(HOST)
    elif change == "omp":
      record["agent"] = "omp"
      record["native_home_ref"]["kind"] = "omp-managed-home"
    elif change == "ssh":
      record["backend"] = "ssh"
    elif change == "manager":
      changed = {**MANAGER, "birth_id": "different-birth"}
      record["manager_identity"] = changed
      record["process_observation"]["manager_identity"] = changed
    if change != "missing":
      write_record(store, record)
  before = record_bytes(store)
  with pytest.raises(Conflict):
    store.registry.bind_current_host(run_id, handle)
  assert record_bytes(store) == before


@pytest.mark.parametrize("change", ["json", "same-pid", "manager", "current-manager", "source", "relationship"])
def test_untrusted_or_changed_host_does_not_change_record(store, handle, monkeypatch, change):
  write_record(store, v2_record(store))
  observation = deepcopy(HOST)
  if change == "json":
    handle = observation
  elif change == "same-pid":
    observation["identity"]["pid"] = MANAGER["pid"]
  elif change == "manager":
    observation["manager_identity"]["birth_id"] = "changed"
  elif change == "current-manager":
    monkeypatch.setattr(owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "changed"})
  elif change == "source":
    observation["source"] = "caller-json"
  else:
    observation["relationship"] = "guessed"
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: observation)
  before = record_bytes(store)
  with pytest.raises(Conflict):
    store.registry.bind_current_host(RUN_ID, handle)
  assert record_bytes(store) == before


def test_handle_rechecked_under_owner_lock(store, handle, monkeypatch):
  write_record(store, v2_record(store))
  def snapshot(self):
    with pytest.raises(Conflict):
      with store.registry._locked(nonblocking=True):
        pytest.fail("owner must remain locked during host observation")
    return deepcopy(HOST)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", snapshot)
  store.registry.bind_current_host(RUN_ID, handle)


@pytest.mark.parametrize("error", [Conflict, OSError, KeyboardInterrupt, SystemExit])
def test_failed_observation_keeps_record_and_propagates_controls(store, handle, monkeypatch, error):
  write_record(store, v2_record(store))
  def snapshot(self):
    raise error("synthetic private error")
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", snapshot)
  before = record_bytes(store)
  expected = error if error in (KeyboardInterrupt, SystemExit) else Conflict
  with pytest.raises(expected) as caught:
    store.registry.bind_current_host(RUN_ID, handle)
  if expected is Conflict:
    assert "synthetic private error" not in str(caught.value)
  assert record_bytes(store) == before


@pytest.mark.parametrize("after", [False, True])
def test_write_failure_keeps_observed_fact_without_retry(store, handle, monkeypatch, after):
  write_record(store, v2_record(store))
  replace, calls = Tree.replace, []
  def fail(tree, path, data, **kwargs):
    calls.append(path)
    if after:
      replace(tree, path, data, **kwargs)
    raise OSError("synthetic private write error")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", fail)
    with pytest.raises(Conflict):
      store.registry.bind_current_host(RUN_ID, handle)
  assert calls == [RUN_ID + ".json"]
  record = store.registry.snapshot()[RUN_ID]
  assert record["host_identity"] == (HOST if after else None)
  assert record["protocol"]["control"] is None
