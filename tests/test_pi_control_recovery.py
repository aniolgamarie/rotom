"""只读核对与显式停止恢复分开；信号均由假后端记录。"""

from datetime import datetime, timedelta, timezone

import pytest

from agentcfg.storage import Conflict
from test_pi_activity import make_store, begin, identity
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_workspace_leases import worktree


class SimulatedCrash(BaseException):
  pass


def orphan(tmp_path):
  old, processes = make_store(tmp_path)
  worker = identity(201)
  processes.current[201] = worker
  lease = begin(old, lambda _: worker)
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  return old, new, processes, lease


def test_read_only_reconcile_then_explicit_stop_revokes_and_reclaims(tmp_path):
  old, new, processes, lease = orphan(tmp_path)
  assert new.reconcile(lease["lease_id"])["protected"]
  assert processes.signals == []
  plan = new.plan_stop(lease["lease_id"])
  assert plan["plan_kind"] == "stop_execution"
  assert processes.signals == []
  result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="user-stop")
  assert result["state"] == "reclaimed"
  assert result["grant_generation"] == 2
  assert len(processes.signals) == 1
  assert new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="user-stop") == result
  assert len(processes.signals) == 1
  new.assert_mutable()
  with pytest.raises(Conflict):
    old.request_cancel(lease["lease_id"], old.owner)


def test_live_old_controller_pid_reuse_and_expired_plan_are_not_stop_authority(tmp_path):
  old, new, processes, lease = orphan(tmp_path)
  processes.current[101] = old.owner["supervisor_process_identity"]
  with pytest.raises(Conflict):
    new.plan_stop(lease["lease_id"])
  processes.current.pop(101)
  plan = new.plan_stop(lease["lease_id"])
  processes.current[201] = identity(201, "reused")
  with pytest.raises(Conflict):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="pid-reuse")
  processes.current[201] = identity(201)
  new.now = lambda: datetime(2026, 9, 16, tzinfo=timezone.utc) + timedelta(seconds=301)
  with pytest.raises(Conflict):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="expired")
  assert processes.signals == []


@pytest.mark.parametrize("phase", ["intent", "reserved", "journal", "starting"])
def test_crash_during_allocation_only_uncommitted_intent_can_abort(tmp_path, phase):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  def crash(point, lease):
    if point == phase:
      raise SimulatedCrash()
  old, processes = make_store(tmp_path, fault=crash)
  old.workspaces = manager
  spawned = []
  with pytest.raises(SimulatedCrash):
    old.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
      planned_workspaces=[planned], spawn=lambda lease: spawned.append(lease))
  assert spawned == []
  lease = old.records()[0]
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  new.workspaces = manager
  if phase == "starting":
    with pytest.raises(Conflict):
      new.plan_stop(lease["lease_id"])
    assert new.reconcile(lease["lease_id"])["protected"]
  else:
    plan = new.plan_stop(lease["lease_id"])
    assert plan["plan_kind"] == "abort_allocation"
    result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="abort")
    assert result["state"] == "failed"
    assert result["termination_evidence"]["kind"] == "never-started"
    marker = manager.read(planned)
    assert marker is None or marker["state"] == "released"
    new.assert_mutable()
  assert processes.signals == []


@pytest.mark.parametrize("phase", ["recovery-authorized", "recovery-revoked", "recovery-stopped"])
def test_recovery_crash_reuses_same_authorization_and_generation(tmp_path, phase):
  _, new, processes, lease = orphan(tmp_path)
  plan = new.plan_stop(lease["lease_id"])
  def crash(point, value):
    if point == phase:
      raise SimulatedCrash()
  new.fault = crash
  with pytest.raises(SimulatedCrash):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="same-request")
  new.fault = lambda *args: None
  result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="same-request")
  assert result["state"] == "reclaimed"
  assert result["grant_generation"] == 2
  assert len(processes.signals) == 1


def test_stop_keeps_both_leases_until_external_work_is_proven_terminated(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  old, processes = make_store(tmp_path)
  old.workspaces = manager
  worker = identity(201)
  processes.current[201] = worker
  lease = old.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[planned], spawn=lambda _: worker)
  old.record_external(lease["lease_id"], old.owner, ["external"])
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  new.workspaces = manager
  plan = new.plan_stop(lease["lease_id"])
  with pytest.raises(Conflict):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="stop-external")
  assert new.reconcile(lease["lease_id"])["protected"]
  assert manager.read(planned)["state"] == "active"
  processes.external["external"] = "terminated"
  result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="stop-external")
  assert result["state"] == "reclaimed"
  assert manager.read(planned)["state"] == "released"
  assert len(processes.signals) == 1


def test_corrupted_allocation_journal_cannot_be_used_as_never_started_proof(tmp_path):
  import json
  def crash(point, lease):
    if point == "intent":
      raise SimulatedCrash()
  old, processes = make_store(tmp_path, fault=crash)
  with pytest.raises(SimulatedCrash):
    begin(old, lambda _: identity(201))
  lease = old.records()[0]
  path = old.root / old._path(lease["lease_id"])
  document = json.loads(path.read_bytes())
  document["allocation_journal_digest"] = "0" * 64
  path.write_text(json.dumps(document))
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  with pytest.raises(Conflict):
    new.plan_stop(lease["lease_id"])
  with pytest.raises(Conflict):
    new.assert_mutable()
  assert processes.signals == []


def test_next_recovery_activation_requires_previous_controller_death(tmp_path):
  _, new, processes, lease = orphan(tmp_path)
  plan = new.plan_stop(lease["lease_id"])
  new.fault = lambda phase, _: (_ for _ in ()).throw(SimulatedCrash()) if phase == "recovery-revoked" else None
  with pytest.raises(SimulatedCrash):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="continuation")
  third, _ = make_store(tmp_path, processes=processes, activation="supervisor-three")
  with pytest.raises(Conflict):
    third.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="continuation")
  processes.current.pop(102)
  assert third.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="continuation")["state"] == "reclaimed"
  fourth, _ = make_store(tmp_path, processes=processes, activation="supervisor-four")
  with pytest.raises(Conflict):
    fourth.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="continuation")


def test_stop_recovers_registered_descendants_after_worker_leader_exits(tmp_path):
  _, new, processes, lease = orphan(tmp_path)
  processes.current.pop(201)
  active = [True]
  calls = []
  processes.termination_status = lambda expected: "active" if active[0] else "terminated"
  def stop(expected, *, grant_generation):
    assert processes.observe(expected) == "dead"
    calls.append(grant_generation)
    active[0] = False
  processes.stop = stop
  plan = new.plan_stop(lease["lease_id"])
  assert new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="remaining-descendants")["state"] == "reclaimed"
  assert calls == [2]


def test_release_crash_reuses_durable_proof_even_after_pid_reuse(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  old, processes = make_store(tmp_path)
  old.workspaces = manager
  worker = identity(201)
  processes.current[201] = worker
  lease = old.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[planned], spawn=lambda _: worker)
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  new.workspaces = manager
  plan = new.plan_stop(lease["lease_id"])
  def crash(point, value):
    if point == "recovery-released":
      raise SimulatedCrash()
  new.fault = crash
  with pytest.raises(SimulatedCrash):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="release-crash")
  released = manager.read(planned)
  assert released["state"] == "released"
  processes.current[201] = identity(201, "reused-by-unrelated-process")
  new.fault = lambda *args: None
  result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="release-crash")
  assert result["state"] == "reclaimed"
  assert result["termination_evidence"]["evidence_digest"] in released["termination_evidence_refs"]
  assert processes.current[201]["start_time"] == "reused-by-unrelated-process"
  assert len(processes.signals) == 1


def test_multi_workspace_allocation_and_cleanup_crashes_keep_one_recovery_proof(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = [manager.identify(worktree(tmp_path, name)) for name in ("first", "second")]
  count = [0]
  def crash(point, lease):
    if point == "reserved":
      count[0] += 1
      if count[0] == 2:
        raise SimulatedCrash()
  old, processes = make_store(tmp_path, fault=crash)
  old.workspaces = manager
  with pytest.raises(SimulatedCrash):
    old.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
      planned_workspaces=planned, spawn=lambda _: pytest.fail("uncommitted intent cannot spawn"))
  lease = old.records()[0]
  assert len(lease["planned_workspaces"]) == 2
  assert len(lease["workspace_write_lease_ids"]) == 1
  processes.current.pop(101)
  new, _ = make_store(tmp_path, processes=processes, activation="supervisor-two")
  new.workspaces = manager
  plan = new.plan_stop(lease["lease_id"])
  assert len(plan["workspace_write_lease_ids"]) == 2
  new.fault = lambda point, _: (_ for _ in ()).throw(SimulatedCrash()) if point == "recovery-released" else None
  with pytest.raises(SimulatedCrash):
    new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="all-workspaces")
  assert sorted(manager.read(item)["state"] for item in planned) == ["released", "reserved"]
  new.fault = lambda *args: None
  new.now = lambda: datetime(2026, 9, 16, tzinfo=timezone.utc) + timedelta(seconds=100)
  result = new.recover_stop(lease["lease_id"], plan["plan_digest"], request_id="all-workspaces")
  assert result["state"] == "failed"
  assert all(manager.read(item)["termination_evidence_refs"] == [result["termination_evidence"]["evidence_digest"]] for item in planned)
  assert processes.signals == []
