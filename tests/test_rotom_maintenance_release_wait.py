"""共享预算的真实临时元数据/锁组合；假退出观察，不执行停止或 setup。"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest

from agentcfg import maintenance, maintenance_progress as progress, maintenance_release as release
from agentcfg import maintenance_store as store, resource_owners as owners
from agentcfg.control_deadline import ControlDeadline
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_live_store import acceptance, leases_for
from test_rotom_maintenance_progress import proof
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_maintenance_release import assert_locks
from test_rotom_resource_coordination import locked
from test_rotom_resource_owners import IDENTITY, owner_path


class Clock:
  def __init__(self):
    self.now = 0
    self.broken = False

  def __call__(self):
    if self.broken:
      raise OSError("synthetic-private-canary")
    return self.now


def build_ready(group, operation="setup", *, unknown=False):
  case = group(separate_third=True)
  value = acceptance(case)
  plan = maintenance._plan({**value["batch"]["plan"], "operation": operation}, verify=False)
  value = maintenance.build_stop_acceptance(batch_id=BATCH, plan=plan,
    records=value["records"], expected_revision=value["expected_revision"])
  with leases_for(case) as leases:
    store.accept_stop_snapshot_live(case.domain, value, leases=leases)
    for run in RUNS[:2]:
      if unknown and run == RUNS[0]:
        case.domain.mark_unknown(run)
        continue
      owners.finish_owner(case.domain, run, observation=proof(value, run),
        **{key: item for key, item in leases[run].items() if key != "state_fd"})
  # 除 unknown 场景外 owner 已完成记账；Batch 未预写 exit，须由本次等待保存。
  assert progress.read_batch(case.domain, BATCH)["revision"] == 0
  return case, value, {row.run: row.workspace for row in case.rows[:2]}


@pytest.fixture
def ready(group):
  return build_ready(group)


def wait(ready, *, clock=None, observe=None, workspaces=None):
  case, value, targets = ready
  clock = Clock() if clock is None else clock
  return release.wait_for_setup_release(case.domain, BATCH,
    deadline=ControlDeadline(1, clock=clock),
    observe=(lambda run, manager: proof(value, run)) if observe is None else observe,
    workspaces=targets if workspaces is None else workspaces)


def no_confirm(monkeypatch):
  monkeypatch.setattr(release, "confirm_setup_release",
    lambda *a, **k: pytest.fail("must not enter physical release confirmation"))


def test_exit_wait_then_real_ex_commit_has_one_budget_and_no_permit(ready):
  case, value, workspaces = ready
  third = deepcopy(case.domain.snapshot()["reservations"][RUNS[2]])
  owners_before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  result = wait(ready)
  assert type(result) is release.SetupReleaseWaitResult
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.release_confirmed and result.revision == 3 and result.exit_code == 0 and result.reason is None
  with pytest.raises(FrozenInstanceError):
    result.revision = 99
  batch = progress.read_batch(case.domain, BATCH)
  assert batch["phase"] == "stopped_confirmed" and batch["revision"] == 3
  assert all(item["facts"] == {"stop_requested": False, "exit_confirmed": True,
    "resources_released": True, "session_sealed": False} for item in batch["items"])
  assert batch["maintenance_dispatch"]["state"] == "not_dispatched"
  assert case.domain.snapshot()["reservations"][RUNS[2]] == third
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owners_before
  assert_locks(case, workspaces, held=False)


@pytest.mark.parametrize("change", ["missing", "extra", "not-dict", "deadline", "observe"])
def test_invalid_inputs_reject_before_observation_or_writes(ready, change):
  case, value, targets = ready
  workspaces = dict(targets)
  deadline = ControlDeadline(1, clock=lambda: 0)
  observe = lambda *a: pytest.fail("invalid preflight must not observe")
  if change == "missing": del workspaces[RUNS[0]]
  elif change == "extra": workspaces[RUNS[2]] = case.rows[2].workspace
  elif change == "not-dict": workspaces = tuple(workspaces.items())
  elif change == "deadline": deadline = object()
  else: observe = None
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    release.wait_for_setup_release(case.domain, BATCH, deadline=deadline,
      observe=observe, workspaces=workspaces)
  assert ledger(case.domain) == before


def test_stop_only_is_not_taken_over_before_any_observation(group):
  case, value, workspaces = build_ready(group, operation="stop_only")
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    wait((case, value, workspaces), observe=lambda *a: pytest.fail("stop_only cannot observe"))
  assert ledger(case.domain) == before


def test_workspace_value_rejection_preserves_legally_recorded_exit_facts(ready):
  case, value, workspaces = ready
  workspaces[RUNS[0]] = case.rows[2].workspace
  result = wait(ready)
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.revision == 2 and result.reason == "release-unconfirmed" and not result.release_confirmed
  assert all(item["facts"]["exit_confirmed"] for item in progress.read_batch(case.domain, BATCH)["items"])


@pytest.mark.parametrize("broken", [False, True])
def test_initial_expiry_or_clock_failure_preserves_facts_without_ex(ready, monkeypatch, broken):
  case, value, workspaces = ready
  clock = Clock(); deadline = ControlDeadline(1, clock=clock)
  clock.broken = broken; clock.now = 1
  no_confirm(monkeypatch); before = ledger(case.domain)
  result = release.wait_for_setup_release(case.domain, BATCH, deadline=deadline,
    observe=lambda *a: pytest.fail("initial budget unavailable"), workspaces=workspaces)
  assert result.exit_code == 4 and not result.release_confirmed and result.revision == 0
  assert result.reason == ("clock-unconfirmed" if broken else "deadline-expired")
  assert result.confirmed_runs == () and result.pending_runs == RUNS[:2]
  assert ledger(case.domain) == before


def test_exit_record_crossing_deadline_never_enters_ex(ready, monkeypatch):
  case, value, workspaces = ready; clock = Clock(); no_confirm(monkeypatch)
  def observe(run, manager):
    clock.now += 0.6
    return proof(value, run)
  result = wait(ready, clock=clock, observe=observe)
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.revision == 2 and result.exit_code == 4 and result.reason == "deadline-expired"
  assert not result.release_confirmed
  assert all(not item["facts"]["resources_released"] for item in progress.read_batch(case.domain, BATCH)["items"])


def test_lost_exit_record_reply_keeps_last_known_revision_without_readback(ready, monkeypatch):
  case, value, workspaces = ready; original = progress.record_exit; calls = []
  def record(*args, **kwargs):
    calls.append(kwargs["expected_revision"]); original(*args, **kwargs)
    raise OSError("synthetic-private-canary")
  monkeypatch.setattr(progress, "record_exit", record); no_confirm(monkeypatch)
  result = wait(ready)
  assert result.revision == 0 and result.confirmed_runs == () and result.pending_runs == RUNS[:2]
  assert result.exit_code == 4 and result.reason == "record-unconfirmed" and not result.release_confirmed
  assert calls == [0] and progress.read_batch(case.domain, BATCH)["revision"] == 1
  assert "canary" not in repr(result)


def test_wait_to_confirm_revision_race_does_not_resign_cas(ready, monkeypatch):
  case, value, workspaces = ready; original = progress.wait_for_batch_release
  def race(*args, **kwargs):
    result = original(*args, **kwargs)
    progress.record_stop_requested(case.domain, BATCH, expected_revision=result.revision, run_id=RUNS[0])
    return result
  monkeypatch.setattr(progress, "wait_for_batch_release", race)
  result = wait(ready)
  assert result.revision == 2 and not result.release_confirmed
  assert result.exit_code == 4 and result.reason == "release-unconfirmed"
  assert progress.read_batch(case.domain, BATCH)["revision"] == 3
  assert_locks(case, workspaces, held=False)


@pytest.mark.parametrize("kind", ["instance", "state", "runtime"])
def test_physical_sh_conflict_keeps_exit_facts_but_not_release(ready, kind):
  case, value, workspaces = ready; ws = workspaces[RUNS[0]]
  guard = (locked(case.cache, IDENTITY) if kind == "runtime" else
    _shared_file(ws.instance, ".agentcfg-omp.lock") if kind == "instance" else
    _shared_file(ws.state_root, "instance.lock"))
  with guard:
    result = wait(ready)
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.revision == 2 and not result.release_confirmed and result.reason == "release-unconfirmed"
  assert result.exit_code == 4
  assert_locks(case, workspaces, held=False)


def test_unknown_reservation_blocks_even_after_all_exit_facts_and_ex_available(group):
  case, value, workspaces = build_ready(group, unknown=True)
  result = wait((case, value, workspaces))
  assert result.revision == 2 and result.confirmed_runs == RUNS[:2]
  assert not result.release_confirmed and result.reason == "release-unconfirmed"
  assert case.domain.snapshot()["reservations"][RUNS[0]]["phase"] == "unknown"


@pytest.mark.parametrize("after", [False, True])
def test_physical_commit_failure_is_unknown_and_not_retried(ready, monkeypatch, after):
  case, value, workspaces = ready; replace = Tree.replace; calls = []
  def commit(tree, name, data, *args, **kwargs):
    if name == "coordination.json" and json.loads(data)["intents"][BATCH]["progress"]["phase"] == "stopped_confirmed":
      calls.append(name)
      if after: replace(tree, name, data, *args, **kwargs)
      raise OSError("synthetic-private-canary")
    return replace(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", commit)
  result = wait(ready)
  assert result.revision == 2 and result.exit_code == 4 and not result.release_confirmed
  assert result.reason == "release-unconfirmed" and calls == ["coordination.json"]
  assert progress.read_batch(case.domain, BATCH)["revision"] == (3 if after else 2)
  assert_locks(case, workspaces, held=False)


@pytest.mark.parametrize("broken", [False, True])
def test_late_physical_success_keeps_confirmed_fact_but_cannot_continue(ready, monkeypatch, broken):
  case, value, workspaces = ready; clock = Clock(); original = release.confirm_setup_release
  def confirm(*args, **kwargs):
    result = original(*args, **kwargs)
    clock.now = 1.2; clock.broken = broken
    return result
  def observe(run, manager):
    clock.now += 0.3
    return proof(value, run)
  monkeypatch.setattr(release, "confirm_setup_release", confirm)
  result = wait(ready, clock=clock, observe=observe)
  assert result.release_confirmed and result.revision == 3 and result.exit_code == 4
  assert result.reason == ("clock-unconfirmed" if broken else "deadline-expired")
  assert progress.read_batch(case.domain, BATCH)["phase"] == "stopped_confirmed"
  assert_locks(case, workspaces, held=False)


def test_clock_failure_between_wait_and_ex_does_not_enter_confirm(ready, monkeypatch):
  clock = Clock(); original = progress.wait_for_batch_release
  def observed(*args, **kwargs):
    result = original(*args, **kwargs); clock.broken = True; return result
  monkeypatch.setattr(progress, "wait_for_batch_release", observed); no_confirm(monkeypatch)
  result = wait(ready, clock=clock)
  assert result.revision == 2 and result.exit_code == 4 and result.reason == "clock-unconfirmed"
  assert not result.release_confirmed


def test_caller_mapping_mutation_does_not_retarget_confirm(ready):
  case, value, workspaces = ready
  def observe(run, manager):
    workspaces.clear()
    return proof(value, run)
  result = wait(ready, observe=observe)
  assert result.exit_code == 0 and result.release_confirmed and workspaces == {}


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(7)])
def test_control_exception_propagates_without_release_or_fact(ready, error):
  case, value, workspaces = ready; before = ledger(case.domain)
  def observe(*args): raise error
  with pytest.raises(type(error)) as caught:
    wait(ready, observe=observe)
  assert caught.value is error and ledger(case.domain) == before
  assert_locks(case, workspaces, held=False)
