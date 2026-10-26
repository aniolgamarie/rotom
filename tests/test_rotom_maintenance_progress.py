"""真实临时 Domain 进展提交，fake proof/clock；无 host、信号或维护许可。"""
from copy import deepcopy

import pytest

from agentcfg import maintenance_progress as progress, maintenance_store as store, run_owners
from agentcfg.control_deadline import ControlDeadline
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance import acceptance
from test_rotom_maintenance_recovery import group, RUNS, BATCH, ledger
from test_rotom_resource_owners import owner_path


@pytest.fixture
def accepted(group):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  return case, value


def items(batch): return {item["run_id"]: item for item in batch["items"]}


def proof(value, run=RUNS[0], **changes):
  fields = {"run_id": run, "manager_identity": deepcopy(value["records"][run]["manager_identity"]),
    "complete": True, "all_related_exited": True}
  fields.update(changes)
  return run_owners.ReleaseObservation(**fields)


def test_initial_progress_is_acceptance_batch_read_only_detached(accepted):
  case, value = accepted; before = ledger(case.domain)
  batch = progress.read_batch(case.domain, BATCH)
  assert batch == value["batch"] and batch["revision"] == 0
  batch["items"][0]["facts"]["exit_confirmed"] = True
  assert progress.read_batch(case.domain, BATCH) == value["batch"] and ledger(case.domain) == before


def test_requested_exit_separate_and_third_owner_reservation_unchanged(accepted):
  case, value = accepted
  owners = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  third = deepcopy(case.domain.snapshot()["reservations"][RUNS[2]])
  batch = progress.record_stop_requested(case.domain, BATCH, expected_revision=0, run_id=RUNS[0])
  assert batch["revision"] == 1 and batch["phase"] == "stop_requested"
  assert items(batch)[RUNS[0]]["facts"] == {"stop_requested": True, "exit_confirmed": False,
    "resources_released": False, "session_sealed": False}
  batch = progress.record_exit(case.domain, BATCH, expected_revision=1, proof=proof(value))
  assert batch["revision"] == 2 and items(batch)[RUNS[0]]["facts"]["exit_confirmed"] is True
  assert batch["phase"] == "stop_requested" and items(batch)[RUNS[0]]["stop_phase"] == "stop_requested"
  assert all(not item["facts"]["resources_released"] and not item["facts"]["session_sealed"] for item in batch["items"])
  assert case.domain.snapshot()["reservations"][RUNS[2]] == third
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owners


def test_complete_exit_without_request_does_not_invent_stop_or_resources(accepted):
  case, value = accepted
  batch = progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  assert batch["phase"] == "accepted" and batch["revision"] == 1
  assert items(batch)[RUNS[0]]["facts"] == {"stop_requested": False, "exit_confirmed": True,
    "resources_released": False, "session_sealed": False}


@pytest.mark.parametrize("revision", [True, -1, 1, 0.0, None])
def test_revision_cas_rejects_invalid_or_stale_without_writes(accepted, revision):
  case, value = accepted; before = ledger(case.domain)
  with pytest.raises(Conflict): progress.record_stop_requested(case.domain, BATCH, expected_revision=revision, run_id=RUNS[0])
  assert ledger(case.domain) == before


@pytest.mark.parametrize("operation", ["requested", "exit"])
def test_duplicate_fact_conflicts_even_at_fresh_revision(accepted, operation):
  case, value = accepted
  def invoke(revision):
    if operation == "requested":
      return progress.record_stop_requested(case.domain, BATCH, expected_revision=revision, run_id=RUNS[0])
    return progress.record_exit(case.domain, BATCH, expected_revision=revision, proof=proof(value))
  invoke(0); before = ledger(case.domain)
  with pytest.raises(Conflict): invoke(1)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("change", ["incomplete", "survivor", "complete-int", "wrong-manager", "manager-extra", "wrong-run", "dict"])
def test_invalid_exit_observation_never_changes_facts(accepted, change):
  case, value = accepted; observation = proof(value)
  if change == "incomplete": observation = proof(value, complete=False)
  elif change == "survivor": observation = proof(value, all_related_exited=False)
  elif change == "complete-int": observation = proof(value, complete=1)
  elif change == "wrong-manager": observation = proof(value, manager_identity={**observation.manager_identity, "birth_id": "other"})
  elif change == "manager-extra": observation = proof(value, manager_identity={**observation.manager_identity, "extra": True})
  elif change == "wrong-run": observation = proof(value, run_id=RUNS[2])
  else: observation = {"run_id": RUNS[0]}
  before = ledger(case.domain)
  with pytest.raises(Conflict): progress.record_exit(case.domain, BATCH, expected_revision=0, proof=observation)
  assert ledger(case.domain) == before


def test_unknown_retains_facts_and_blocks_later_writes_or_wait_observers(accepted):
  case, value = accepted
  progress.record_stop_requested(case.domain, BATCH, expected_revision=0, run_id=RUNS[0])
  previous = progress.record_exit(case.domain, BATCH, expected_revision=1, proof=proof(value))
  batch = progress.mark_unknown(case.domain, BATCH, expected_revision=2, run_id=RUNS[0])
  assert batch["revision"] == 3 and batch["phase"] == "unknown" and batch["review_required"] is True
  assert items(batch)[RUNS[0]]["facts"] == items(previous)[RUNS[0]]["facts"]
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "unknown"
  before = ledger(case.domain)
  with pytest.raises(Conflict): progress.record_exit(case.domain, BATCH, expected_revision=3, proof=proof(value, RUNS[1]))
  with pytest.raises(Conflict):
    progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0),
      observe=lambda *a: pytest.fail("unknown cannot resume automatic waiting"))
  assert progress.read_batch(case.domain, BATCH) == batch and ledger(case.domain) == before


@pytest.mark.parametrize("operation", ["requested", "unknown"])
def test_unselected_third_cannot_be_changed(accepted, operation):
  case, value = accepted; before = ledger(case.domain)
  fn = progress.record_stop_requested if operation == "requested" else progress.mark_unknown
  with pytest.raises(Conflict): fn(case.domain, BATCH, expected_revision=0, run_id=RUNS[2])
  assert ledger(case.domain) == before


def test_dispatched_intent_can_record_but_does_not_release_or_clear_protection(accepted):
  case, value = accepted; case.domain.dispatch_intent(BATCH)
  result = progress.record_stop_requested(case.domain, BATCH, expected_revision=0, run_id=RUNS[0])
  assert result["revision"] == 1 and case.domain.snapshot()["intents"][BATCH]["phase"] == "dispatched"
  assert all(entry["phase"] == "dispatched" for entry in case.domain.snapshot()["reservations"].values())


def test_old_intent_missing_progress_remains_readable_but_new_api_does_not_infer(accepted):
  case, value = accepted
  with case.domain._transaction(write=True) as state: state["intents"][BATCH].pop("progress")
  assert store.read_stop_snapshot(case.domain, BATCH)["acceptance"] == value
  before = ledger(case.domain)
  with pytest.raises(Conflict): progress.read_batch(case.domain, BATCH)
  with pytest.raises(Conflict): progress.record_stop_requested(case.domain, BATCH, expected_revision=0, run_id=RUNS[0])
  assert ledger(case.domain) == before


def test_cancelled_intent_does_not_observe_or_write(accepted):
  case, value = accepted; case.domain.cancel_intent(BATCH)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0),
      observe=lambda *a: pytest.fail("cancelled cannot observe"))
  with pytest.raises(Conflict): progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  assert ledger(case.domain) == before


@pytest.mark.parametrize("stage", ["before", "after"])
def test_commit_or_response_loss_preserves_exact_readback_and_does_not_retry(accepted, monkeypatch, stage):
  case, value = accepted; original = Tree.replace; calls = []
  def replace(tree, name, data, **kwargs):
    if name == "coordination.json":
      calls.append(True)
      if stage == "before": raise OSError("synthetic-private-canary")
      original(tree, name, data, **kwargs)
      raise OSError("synthetic-private-canary")
    return original(tree, name, data, **kwargs)
  monkeypatch.setattr(Tree, "replace", replace)
  with pytest.raises(Conflict) as caught: progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  assert "synthetic-private-canary" not in str(caught.value) and calls == [True]
  batch = progress.read_batch(case.domain, BATCH)
  assert batch["revision"] == (1 if stage == "after" else 0)
  assert items(batch)[RUNS[0]]["facts"]["exit_confirmed"] is (stage == "after")


def test_wait_skips_existing_fact_and_returns_all_confirmed_without_resource_claim(accepted):
  case, value = accepted; progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  seen = []
  def observe(run, manager):
    seen.append(run)
    assert manager == value["records"][run]["manager_identity"]
    manager["birth_id"] = "external-mutation"
    return proof(value, run)
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0), observe=observe)
  assert result.exit_code == 0 and result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert type(result) is progress.BatchReleaseWaitResult and isinstance(result, progress.ReleaseWaitResult)
  assert result.revision == 2
  assert seen == [RUNS[1]]
  batch = progress.read_batch(case.domain, BATCH)
  assert batch["revision"] == 2 and batch["phase"] == "accepted"
  assert all(item["facts"]["exit_confirmed"] and not item["facts"]["resources_released"] for item in batch["items"])


def test_wait_uses_shared_deadline_even_when_last_record_commits_after_expiry(accepted):
  case, value = accepted; now = [0]; seen = []
  def observe(run, manager): now[0] += 0.6; seen.append(run); return proof(value, run)
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: now[0]), observe=observe)
  assert result.exit_code == 4 and result.reason == "deadline-expired"
  assert result.confirmed_runs == RUNS[:2] and not result.pending_runs and seen == list(RUNS[:2])
  assert result.revision == 2
  assert progress.read_batch(case.domain, BATCH)["revision"] == 2


def test_wait_record_response_loss_preserves_prior_fact_and_never_retries(accepted, monkeypatch):
  case, value = accepted; progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  original = progress.record_exit; calls = []
  def record(*a, **kw):
    calls.append(kw["proof"].run_id); original(*a, **kw); raise OSError("synthetic-private-canary")
  monkeypatch.setattr(progress, "record_exit", record)
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0),
    observe=lambda run, manager: proof(value, run))
  assert result.exit_code == 4 and result.reason == "record-unconfirmed"
  assert result.confirmed_runs == RUNS[:1] and result.pending_runs == RUNS[1:2] and calls == [RUNS[1]]
  assert result.revision == 1
  assert all(item["facts"]["exit_confirmed"] for item in progress.read_batch(case.domain, BATCH)["items"])


@pytest.mark.parametrize("expired", [False, True])
def test_all_saved_facts_check_deadline_without_observing(accepted, expired):
  case, value = accepted
  for revision, run in enumerate(RUNS[:2]): progress.record_exit(case.domain, BATCH, expected_revision=revision, proof=proof(value, run))
  now = [0]; deadline = ControlDeadline(1, clock=lambda: now[0]); now[0] = 1 if expired else 0
  before = ledger(case.domain)
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=deadline,
    observe=lambda *a: pytest.fail("saved facts must not be observed again"))
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.revision == 2
  assert result.exit_code == (4 if expired else 0)
  assert result.reason == ("deadline-expired" if expired else None) and ledger(case.domain) == before


@pytest.mark.parametrize("error", [KeyboardInterrupt("synthetic-private-canary"), SystemExit(7)])
def test_wait_control_exception_propagates_unchanged_and_does_not_record(accepted, error):
  case, value = accepted; before = ledger(case.domain)
  def observe(*a): raise error
  with pytest.raises(type(error)) as caught:
    progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0), observe=observe)
  assert caught.value is error and ledger(case.domain) == before


def test_concurrent_progress_revision_conflicts_without_reobserving_or_retry(accepted):
  case, value = accepted; seen = []
  def observe(run, manager):
    seen.append(run)
    progress.record_stop_requested(case.domain, BATCH, expected_revision=0, run_id=RUNS[1])
    return proof(value, run)
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0), observe=observe)
  assert result.reason == "record-unconfirmed" and result.exit_code == 4
  assert result.revision == 0
  assert seen == [RUNS[0]] and result.confirmed_runs == () and result.pending_runs == RUNS[:2]
  batch = progress.read_batch(case.domain, BATCH)
  assert batch["revision"] == 1 and items(batch)[RUNS[1]]["facts"]["stop_requested"] is True
  assert not any(item["facts"]["exit_confirmed"] for item in batch["items"])


def test_observation_failure_preserves_already_recorded_fact_and_fixed_reason(accepted):
  case, value = accepted; progress.record_exit(case.domain, BATCH, expected_revision=0, proof=proof(value))
  def observe(*a): raise OSError("synthetic-private-canary")
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0), observe=observe)
  assert result.reason == "observation-unconfirmed" and result.confirmed_runs == RUNS[:1]
  assert result.pending_runs == RUNS[1:2] and "synthetic-private-canary" not in repr(result)
  assert result.revision == 1
  assert progress.read_batch(case.domain, BATCH)["revision"] == 1


def test_all_confirmed_clock_failure_is_not_a_success(accepted):
  case, value = accepted
  for revision, run in enumerate(RUNS[:2]): progress.record_exit(case.domain, BATCH, expected_revision=revision, proof=proof(value, run))
  broken = [False]
  def clock():
    if broken[0]: raise ValueError("synthetic-private-canary")
    return 0
  deadline = ControlDeadline(1, clock=clock); broken[0] = True
  result = progress.wait_for_batch_release(case.domain, BATCH, deadline=deadline, observe=lambda *a: pytest.fail("already recorded"))
  assert result.confirmed_runs == RUNS[:2] and result.pending_runs == ()
  assert result.exit_code == 4 and result.reason == "clock-unconfirmed"
  assert result.revision == 2


def test_read_rejects_changed_domain_physical_root(accepted, monkeypatch):
  from contextlib import contextmanager
  import shutil
  case, value = accepted; transaction = case.domain._transaction
  old = case.domain.root.with_name("moved-domain")
  @contextmanager
  def swapped(*, write=False):
    with transaction(write=write) as state:
      case.domain.root.rename(old)
      shutil.copytree(old, case.domain.root)
      yield state
  monkeypatch.setattr(case.domain, "_transaction", swapped)
  with pytest.raises(Conflict): progress.read_batch(case.domain, BATCH)


@pytest.mark.parametrize("phase", ["failed", "stopped_confirmed"])
@pytest.mark.parametrize("operation", ["requested", "exit", "unknown", "wait"])
def test_stop_frontend_never_takes_over_legal_later_phase(accepted, phase, operation):
  from agentcfg import maintenance
  case, value = accepted
  batch = deepcopy(value["batch"])
  batch["revision"] = 1
  batch["phase"] = phase
  if phase == "failed":
    batch["review_required"] = True
    batch["items"][0]["stop_phase"] = "failed"
  else:
    for item in batch["items"]:
      item["stop_phase"] = "stopped_confirmed"
      item["facts"].update(stop_requested=True, exit_confirmed=True, resources_released=True)
  # 使用现有纯 codec 和真实 Domain commit，证明这是合法后续阶段而非坏格式。
  batch = maintenance.decode_batch(maintenance.encode_batch(batch))
  with case.domain._transaction(write=True) as state: state["intents"][BATCH]["progress"] = deepcopy(batch)
  before = ledger(case.domain); observed = []
  def observe(run, manager): observed.append(run); return proof(value, run)
  with pytest.raises(Conflict):
    if operation == "requested": progress.record_stop_requested(case.domain, BATCH, expected_revision=1, run_id=RUNS[1])
    elif operation == "exit": progress.record_exit(case.domain, BATCH, expected_revision=1, proof=proof(value))
    elif operation == "unknown": progress.mark_unknown(case.domain, BATCH, expected_revision=1, run_id=RUNS[0])
    else: progress.wait_for_batch_release(case.domain, BATCH, deadline=ControlDeadline(1, clock=lambda: 0), observe=observe)
  assert observed == [] and ledger(case.domain) == before
  assert progress.read_batch(case.domain, BATCH) == batch
