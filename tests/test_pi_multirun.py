"""多个监督者共享持久记录，控制权、端点和工作树仍各有边界。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from pathlib import Path

import pytest

from agentcfg.activity import protected
from agentcfg.pi_supervisor import Principal, SupervisorServer, SupervisorService
from agentcfg.storage import Conflict, Tree
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_activity import begin, identity, make_store
from test_pi_supervisor import request
from test_pi_workspace_leases import worktree


def pair(tmp_path):
  first, processes = make_store(tmp_path)
  second, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  first.concurrent = second.concurrent = True
  return first, second, processes


def test_project_discovery_retains_exclusive_physical_admission(tmp_path):
  from agentcfg.pi import PiAdapter
  adapter = PiAdapter(Path(__file__).resolve().parents[1])
  def workspace(project_resources):
    return SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state", profile="pi-default",
      binding={"machine": "fixture", "profile": "pi-default"},
      resolved=SimpleNamespace(data={"profile": {"agent_options": {"discovery": {"project_resources": project_resources}}}}))
  ordinary, discovered = workspace(False), workspace(True)
  with adapter.lifecycle_guard(ordinary):
    pass
  with adapter.run_lifecycle_guard(ordinary), adapter.run_lifecycle_guard(ordinary):
    with pytest.raises(Conflict):
      with adapter.run_lifecycle_guard(discovered):
        pytest.fail("cwd-dependent resource generation entered shared native state")
  with adapter.run_lifecycle_guard(discovered):
    with pytest.raises(Conflict):
      with adapter.run_lifecycle_guard(ordinary):
        pytest.fail("ordinary run entered exclusive project discovery")


def start(store, processes, pid):
  processes.current[pid] = identity(pid)
  return begin(store, lambda _: processes.current[pid])


def test_two_runs_have_independent_ids_endpoints_and_control(tmp_path):
  first, second, processes = pair(tmp_path)
  one = start(first, processes, 201)
  second.assert_admissible()
  two = start(second, processes, 202)
  assert one["execution_id"] == two["execution_id"] and one["lease_id"] != two["lease_id"]
  services = [SupervisorService(store, None, None) for store in (first, second)]
  endpoints = [SupervisorServer(service).endpoint for service in services]
  assert endpoints[0] != endpoints[1]
  assert len(first.owned_records()) == len(second.owned_records()) == 1
  assert services[0].handle(Principal("user"), request("activity_summary", {}))["active_count"] == 1
  with pytest.raises(Conflict):
    services[0].handle(Principal("user"), request("inspect", {"lease_id": two["lease_id"]}))
  with pytest.raises(Conflict):
    first.request_cancel(two["lease_id"], first.owner)
  first.request_cancel(one["lease_id"], first.owner)
  assert second.read(two["lease_id"])["state"] == "running"
  assert processes.signals == []


def test_legacy_unknown_and_dead_owners_require_explicit_recovery(tmp_path):
  first, second, processes = pair(tmp_path)
  one = start(first, processes, 201)
  owner_path = first.root / "activity/supervisors/supervisor-one.json"
  saved = owner_path.read_bytes()
  owner_path.write_bytes(b"{}")
  with pytest.raises(Conflict):
    second.assert_admissible()
  owner_path.write_bytes(saved)
  processes.current.pop(101)
  with pytest.raises(Conflict):
    second.assert_admissible()
  recovery, _ = make_store(tmp_path, processes=processes, activation="supervisor-three")
  plan = recovery.plan_stop(one["lease_id"])
  reclaimed = recovery.recover_stop(one["lease_id"], plan["plan_digest"], request_id="recovery")
  assert not protected(reclaimed)
  second.assert_admissible()


def test_cross_run_writer_conflict_preserves_original_owner(tmp_path):
  first, second, processes = pair(tmp_path)
  manager = WorkspaceLeases("fixture-boot")
  first.workspaces = second.workspaces = manager
  planned = manager.identify(worktree(tmp_path))
  def allocate(store):
    return store.allocate(kind="worker", execution_id="same", task_id="task", attempt_id="attempt",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64,
      candidate_digest="d" * 64, planned_workspaces=[planned])
  one = allocate(first)
  with pytest.raises(Conflict):
    allocate(second)
  assert manager.read(planned)["allocation_id"] == one["allocation_id"]
  assert protected(first.read(one["lease_id"]))


def test_record_scan_serializes_across_different_store_objects(tmp_path, monkeypatch):
  first, second, processes = pair(tmp_path)
  one = start(first, processes, 201)
  entered, release = Event(), Event()
  original = first._save
  def save(tree, lease):
    temporary = first.root / "activity/leases/.agentcfg-inflight-fixture"
    temporary.write_bytes(b"synthetic in-flight metadata")
    entered.set()
    assert release.wait(5)
    temporary.unlink()
    original(tree, lease)
  monkeypatch.setattr(first, "_save", save)
  with ThreadPoolExecutor(max_workers=2) as pool:
    writer = pool.submit(first.request_cancel, one["lease_id"], first.owner)
    try:
      assert entered.wait(5)
      # 普通读保持可取消的非阻塞语义；监督主循环对 busy 延后本轮检查。
      from agentcfg.storage import LockBusy
      with pytest.raises(LockBusy):
        second.records()
    finally:
      release.set()
    writer.result(timeout=5)
    assert second.records()[0]["state"] == "cancel_requested"


def test_interrupted_v2_recovery_can_be_resumed_after_controller_death(tmp_path):
  first, second, processes = pair(tmp_path)
  one = start(first, processes, 201)
  processes.current.pop(101)
  plan = second.plan_stop(one["lease_id"])
  def crash(phase, value):
    if phase == "recovery-revoked":
      raise OSError("synthetic interrupted recovery")
  second.fault = crash
  with pytest.raises(OSError):
    second.recover_stop(one["lease_id"], plan["plan_digest"], request_id="stop")
  processes.current.pop(102)
  third, _ = make_store(tmp_path, processes=processes, activation="supervisor-three")
  assert not protected(third.recover_stop(one["lease_id"], plan["plan_digest"], request_id="stop"))
  assert len(processes.signals) == 1


def test_transient_peer_mutation_does_not_end_host_supervision(tmp_path):
  import threading
  from types import SimpleNamespace
  from agentcfg.pi_host import HostSupervisor
  from agentcfg.storage import LockBusy
  host = object.__new__(HostSupervisor)
  host.config = {"argv": ["synthetic-host"], "cwd": str(tmp_path), "lock_identity": "a" * 64,
    "slice_identity": "b" * 64, "policy_digest": "c" * 64}
  host.repository = tmp_path
  host.children = {}
  host.host_exit = 0
  reads = []
  def records():
    reads.append(True)
    if len(reads) == 1:
      raise LockBusy("synthetic other-run mutation")
    return []
  host.store = SimpleNamespace(owner={"instance_id": "instance"}, owned_records=records,
    allocate=lambda **kwargs: {"lease_id": "host"}, start=lambda *args, **kwargs: {"lease_id": "host"})
  host.service = SimpleNamespace(mutex=threading.RLock(), closing=False, issue_capability=lambda *args: "synthetic")
  closed = []
  host.server = SimpleNamespace(endpoint=tmp_path / "endpoint", open=lambda: None,
    poll=lambda: None, close=lambda: closed.append(True))
  host.poll = lambda: None
  host.spawn = lambda *args: None
  host.activate = lambda *args: None
  assert host.run() == 0
  assert len(reads) == 2 and closed == [True]
