"""共享预算释放等待：所有观察、时钟与sleep均fake。"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from agentcfg.control_deadline import ControlDeadline
from agentcfg import maintenance_wait as wait
from agentcfg.run_owners import ReleaseObservation
from agentcfg.storage import Conflict


RUNS = tuple(char * 32 for char in "abc")
MANAGER = {"pid": 101, "birth_id": "synthetic-manager", "extra": {"generation": 1}}


@pytest.fixture
def case():
  state = SimpleNamespace(now=0, clock_error=None, seen=[], recorded=[], sleeps=[],
    targets={run: deepcopy(MANAGER) for run in RUNS[:2]})
  def clock():
    if state.clock_error: raise state.clock_error
    return state.now
  state.deadline = ControlDeadline(1, clock=clock)
  def observe(run, manager):
    state.seen.append((run, deepcopy(manager)))
    return ReleaseObservation(run, manager, True, True)
  def record(proof): state.recorded.append(proof)
  def sleep(seconds): state.sleeps.append(seconds); state.now += seconds
  state.observe, state.record, state.sleep = observe, record, sleep
  return state


def invoke(case, **kwargs):
  options = dict(deadline=case.deadline, observe=case.observe, record=case.record, sleep=case.sleep)
  options.update(kwargs)
  return wait.wait_for_release(case.targets, **options)


def test_two_selected_sorted_only_recorded_once_immutable_and_silent(case, capsys):
  case.targets = dict(reversed(list(case.targets.items())))
  result = invoke(case)
  assert result == wait.ReleaseWaitResult(RUNS[:2], (), 0, None)
  assert [run for run, _ in case.seen] == list(RUNS[:2])
  assert [proof.run_id for proof in case.recorded] == list(RUNS[:2])
  assert RUNS[2] not in result.confirmed_runs and case.sleeps == []
  assert capsys.readouterr() == ("", "")
  with pytest.raises(FrozenInstanceError): result.exit_code = 4


def test_shared_deadline_not_reset_per_target_and_records_late_fact(case):
  def observe(run, manager):
    case.seen.append(run); case.now += 0.6
    return ReleaseObservation(run, manager, True, True)
  case.observe = observe
  result = invoke(case)
  assert result == wait.ReleaseWaitResult(RUNS[:2], (), 4, "deadline-expired")
  assert len(case.recorded) == 2 and case.now == 1.2 and case.sleeps == []


def test_expiry_before_next_run_keeps_unobserved_pending(case):
  def record(proof): case.recorded.append(proof); case.now = 1
  case.record = record
  result = invoke(case)
  assert result == wait.ReleaseWaitResult(RUNS[:1], RUNS[1:2], 4, "deadline-expired")
  assert [run for run, _ in case.seen] == [RUNS[0]]


def test_already_expired_does_not_observe_or_sleep(case):
  case.now = 1
  assert invoke(case).reason == "deadline-expired"
  assert not case.seen and not case.recorded and not case.sleeps


@pytest.mark.parametrize("damage", ["none", "type", "subclass", "wrong-run", "wrong-manager", "bool-extra", "float-extra", "incomplete", "descendant", "truthy-complete", "invalid-manager"])
def test_unconfirmed_proofs_never_record_or_grant_release(case, damage):
  class Other(ReleaseObservation): pass
  def observe(run, manager):
    if damage == "none": return None
    if damage == "type": return {"run_id": run, "complete": True}
    if damage == "subclass": return Other(run, manager, True, True)
    if damage == "wrong-run": run = RUNS[2]
    if damage == "wrong-manager": manager["birth_id"] = "other"
    if damage == "bool-extra": manager["extra"]["generation"] = True
    if damage == "float-extra": manager["extra"]["generation"] = 1.0
    if damage == "invalid-manager": manager["pid"] = True
    return ReleaseObservation(run, manager, damage != "descendant",
      1 if damage == "truthy-complete" else damage != "incomplete")
  case.observe = observe
  result = invoke(case, interval=0.3)
  assert result == wait.ReleaseWaitResult((), RUNS[:2], 4, "deadline-expired")
  assert case.recorded == [] and len(case.sleeps) == 4
  assert sum(case.sleeps) == pytest.approx(1) and case.sleeps[-1] == pytest.approx(0.1)


def test_observe_gets_fresh_copies_and_confirmed_run_never_repolled(case):
  counts = {run: 0 for run in RUNS[:2]}
  before = deepcopy(case.targets)
  def observe(run, manager):
    counts[run] += 1
    assert manager == MANAGER
    if run == RUNS[1] and counts[run] == 1:
      manager["extra"]["generation"] = 999
      case.targets[RUNS[0]]["extra"]["generation"] = 777
      return None
    return ReleaseObservation(run, manager, True, True)
  case.observe = observe
  result = invoke(case)
  assert result.exit_code == 0 and counts == {RUNS[0]: 1, RUNS[1]: 2}
  assert len(case.sleeps) == 1 and len(case.recorded) == 2
  assert before[RUNS[1]] == case.targets[RUNS[1]]


@pytest.mark.parametrize("site,reason", [("observe", "observation-unconfirmed"), ("record", "record-unconfirmed"), ("clock", "clock-unconfirmed")])
def test_error_keeps_previous_confirmations_and_never_retries_record(case, site, reason):
  def observe(run, manager):
    if run == RUNS[1] and site == "observe": raise ValueError("synthetic-private-canary")
    return ReleaseObservation(run, manager, True, True)
  def record(proof):
    case.recorded.append(proof)
    if proof.run_id == RUNS[1] and site == "record": raise OSError("synthetic-private-canary")
    if proof.run_id == RUNS[0] and site == "clock": case.clock_error = OSError("synthetic-private-canary")
  case.observe, case.record = observe, record
  result = invoke(case)
  assert result == wait.ReleaseWaitResult(RUNS[:1], RUNS[1:2], 4, reason)
  assert [p.run_id for p in case.recorded].count(RUNS[1]) == (1 if site == "record" else 0)
  assert "synthetic-private-canary" not in repr(result)


def test_sleep_error_is_fixed_pending_and_no_retry(case):
  case.observe = lambda *args: None
  calls = []
  def sleep(seconds): calls.append(seconds); raise OSError("synthetic-private-canary")
  result = invoke(case, sleep=sleep)
  assert result == wait.ReleaseWaitResult((), RUNS[:2], 4, "wait-unconfirmed")
  assert calls == [0.05] and not case.recorded


@pytest.mark.parametrize("site", ["observe", "record", "clock", "sleep"])
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_control_exception_is_original_no_conversion(case, site, kind):
  error = kind("synthetic-control")
  def fail(*args): raise error
  if site == "clock": case.clock_error = error
  elif site == "sleep": case.observe = lambda *args: None; case.sleep = fail
  else: setattr(case, site, fail)
  with pytest.raises(kind) as caught: invoke(case)
  assert caught.value is error


@pytest.mark.parametrize("damage", ["empty", "list", "run", "manager", "too-many", "deadline", "observe", "record", "sleep", "bool", "zero", "negative", "large", "infinite", "nan", "string"])
def test_invalid_inputs_fail_before_any_callback(case, damage):
  options = {}
  if damage == "empty": case.targets = {}
  elif damage == "list": case.targets = list(case.targets)
  elif damage == "run": case.targets = {"bad": MANAGER}
  elif damage == "manager": case.targets[RUNS[0]]["pid"] = True
  elif damage == "too-many": case.targets = {format(i, "032x"): MANAGER for i in range(1025)}
  elif damage == "deadline": options["deadline"] = object()
  elif damage in ("observe", "record", "sleep"): options[damage] = None
  else: options["interval"] = {"bool": True, "zero": 0, "negative": -1, "large": 1.01,
    "infinite": float("inf"), "nan": float("nan"), "string": "0.1"}[damage]
  with pytest.raises(Conflict) as caught: invoke(case, **options)
  assert "synthetic-private-canary" not in str(caught.value)
  assert not case.seen and not case.recorded and not case.sleeps


def test_record_gets_independent_proof_and_complete_manager_extensions_survive(case):
  proofs = []
  def observe(run, manager):
    proof = ReleaseObservation(run, manager, True, True)
    proofs.append(proof)
    return proof
  def record(proof):
    assert proof is not proofs[-1]
    assert proof.manager_identity == MANAGER
    proof.manager_identity["extra"]["generation"] = 999
  case.observe, case.record = observe, record
  result = invoke(case)
  assert result.exit_code == 0
  assert all(proof.manager_identity == MANAGER for proof in proofs)
  assert all(manager == MANAGER for manager in case.targets.values())


def test_record_fsync_exceeding_deadline_preserves_all_saved_facts_but_no_success(case):
  def record(proof):
    case.recorded.append(proof)
    if proof.run_id == RUNS[1]: case.now = 2
  case.record = record
  result = invoke(case)
  assert result == wait.ReleaseWaitResult(RUNS[:2], (), 4, "deadline-expired")
