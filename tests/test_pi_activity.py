"""监督契约以身份替身测试，不发送信号、不创建真实子进程。"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os

import pytest

from agentcfg.activity import ExecutionStore
from agentcfg.storage import Conflict


def identity(pid, start="100"):
  return {"platform": "linux", "boot_id": "fixture-boot", "pid": pid, "ppid": 1,
    "pgid": pid, "start_time": start, "namespace": "fixture-namespace", "uid": os.geteuid()}


class FakeProcesses:
  def __init__(self):
    self.current = {}
    self.signals = []
    self.external = {}

  def observe(self, expected):
    actual = self.current.get(expected["pid"])
    if actual is None:
      return "dead"
    return "alive" if actual == expected else "unknown"

  def stop(self, expected, *, grant_generation=None):
    if self.observe(expected) != "alive":
      raise Conflict("unowned process")
    self.signals.append(deepcopy(expected))
    self.current.pop(expected["pid"])

  def external_status(self, identifier):
    return self.external.get(identifier, "unknown")

  def termination_status(self, expected):
    return {"alive": "active", "dead": "terminated", "unknown": "unknown"}[self.observe(expected)]


def make_store(tmp_path, *, processes=None, activation="supervisor-one", fault=None):
  processes = processes or FakeProcesses()
  supervisor = identity({"supervisor-one": 101, "supervisor-two": 102, "supervisor-three": 103, "supervisor-four": 104}[activation])
  processes.current[supervisor["pid"]] = supervisor
  owner = {"instance_id": "fixture-instance", "supervisor_activation_id": activation,
    "manager_activation_id": "manager-" + activation, "owner_nonce": "nonce-" + activation,
    "supervisor_process_identity": supervisor}
  return ExecutionStore(tmp_path / "state", owner, processes, fault=fault,
    now=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc)), processes


def begin(store, spawn, **kwargs):
  return store.begin(kind="worker", execution_id="execution-one", task_id="task-one", attempt_id="attempt-one",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[], spawn=spawn, **kwargs)


def test_durable_starting_boundary_precedes_spawn_and_parent_exit_does_not_reclaim(tmp_path):
  store, processes = make_store(tmp_path)
  worker = identity(201)
  observed = []
  def spawn(lease):
    saved = store.read(lease["lease_id"])
    observed.append((saved["state"], saved["spawn_committed"], saved["process_identity"]))
    processes.current[201] = worker
    return worker
  lease = begin(store, spawn)
  assert observed == [("starting", True, None)]
  assert lease["state"] == "running"
  processes.current.pop(101)
  replacement, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  assert replacement.reconcile(lease["lease_id"])["protected"] is True
  assert processes.signals == []
  with pytest.raises(Conflict):
    replacement.assert_mutable()


def test_cancel_is_revocation_not_termination_and_pid_reuse_stays_unknown(tmp_path):
  store, processes = make_store(tmp_path)
  worker = identity(201)
  processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  canceled = store.request_cancel(lease["lease_id"], store.owner)
  assert canceled["state"] == "cancel_requested"
  assert canceled["grant_generation"] == 2
  assert store.reconcile(lease["lease_id"])["protected"] is True
  processes.current[201] = identity(201, "reused")
  with pytest.raises(Conflict):
    store.finish(lease["lease_id"], store.owner)
  assert store.read(lease["lease_id"])["state"] != "reclaimed"
  assert processes.signals == []


def test_foreign_activation_cannot_dispatch_or_control_old_execution(tmp_path):
  store, processes = make_store(tmp_path)
  worker = identity(201)
  processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  other, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  with pytest.raises(Conflict):
    other.request_cancel(lease["lease_id"], store.owner)
  assert other.reconcile(lease["lease_id"])["protected"] is True
  with pytest.raises(Conflict):
    other.assert_mutable()


def test_terminal_result_cannot_release_unconfirmed_external_work(tmp_path):
  store, processes = make_store(tmp_path)
  worker = identity(201)
  processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  store.record_external(lease["lease_id"], store.owner, ["external-one"])
  processes.current.pop(201)
  with pytest.raises(Conflict):
    store.finish(lease["lease_id"], store.owner)
  processes.external["external-one"] = "terminated"
  assert store.finish(lease["lease_id"], store.owner)["state"] == "reclaimed"
  store.assert_mutable()


def test_committed_spawn_with_missing_ack_is_not_never_started(tmp_path):
  store, processes = make_store(tmp_path)
  def lost_ack(_):
    raise OSError("synthetic missing acknowledgment")
  with pytest.raises(Conflict):
    begin(store, lost_ack)
  leases = store.records()
  assert len(leases) == 1
  assert leases[0]["spawn_committed"] is True
  assert leases[0]["state"] == "unknown"
  assert leases[0]["process_identity"] is None
  with pytest.raises(Conflict):
    store.assert_mutable()


def test_failed_intent_write_cannot_reserve_or_spawn(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  from agentcfg.workspace_leases import WorkspaceLeases
  from test_pi_workspace_leases import worktree
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  store, _ = make_store(tmp_path)
  store.workspaces = manager
  original = Tree.write_state
  def failed(tree, name, data):
    if str(name).startswith("activity/leases/"):
      raise OSError("synthetic intent write failure")
    return original(tree, name, data)
  monkeypatch.setattr(Tree, "write_state", failed)
  with pytest.raises(OSError):
    store.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
      planned_workspaces=[planned], spawn=lambda _: pytest.fail("missing durable intent cannot spawn"))
  assert manager.read(planned) is None


def test_live_supervisor_reuses_inherited_instance_lock_without_releasing_it(tmp_path):
  from agentcfg.storage import Tree, instance_lock
  store, processes = make_store(tmp_path)
  worker = identity(201)
  processes.current[201] = worker
  with Tree(store.root, create=True) as tree, instance_lock(tree) as fd:
    store.lease_fd = fd
    lease = begin(store, lambda _: worker)
    assert lease["state"] == "running"
    with pytest.raises(Conflict):
      with Tree(store.root) as other, instance_lock(other):
        pass


def test_record_scan_waits_for_inflight_publication_but_rejects_persistent_unknown_files(tmp_path):
  import threading
  from agentcfg.storage import Tree
  store, processes = make_store(tmp_path)
  worker = identity(201); processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  attempted, result = threading.Event(), {}
  class ObservedLock:
    def __init__(self): self.lock = threading.RLock()
    def __enter__(self):
      if threading.current_thread().name == "lease-reader": attempted.set()
      self.lock.acquire(); return self
    def __exit__(self, *_): self.lock.release()
  store.mutex = ObservedLock()
  temporary = store.root / "activity/leases/.agentcfg-inflight-fixture"
  def read():
    try: result["leases"] = store.records()
    except Exception as error: result["error"] = error
  thread = threading.Thread(target=read, name="lease-reader")
  try:
    with store.mutex:
      temporary.write_bytes(b"synthetic in-flight publication")
      thread.start()
      assert attempted.wait(2)
      assert result == {}
      temporary.unlink()
    thread.join(2)
    assert not thread.is_alive() and "error" not in result
    assert [row["lease_id"] for row in result["leases"]] == [lease["lease_id"]]
    # 只有受同一写锁保护的在途发布会等待；静态未知文件不能被忽略。
    temporary.write_bytes(b"synthetic leftover")
    with pytest.raises(Conflict, match="未知状态"): store.records()
  finally:
    temporary.unlink(missing_ok=True)
    thread.join(2)
