"""仅纯计划数据与内存锁；不读现场、不停止或维护。"""
from copy import copy, deepcopy
import pickle

import pytest

from agentcfg import maintenance, stop_review as review
from agentcfg.storage import Conflict
from test_rotom_maintenance_plan import plan as make_plan, scope, snapshots, RUNS


BATCH = "a" * 32


def issue(plan=None, **overrides):
  plan = make_plan() if plan is None else plan
  options = dict(scope=scope(), operation="stop_only", selected_runs=list(reversed(RUNS[:2])),
    plan_id=plan["plan_id"], batch_id=BATCH, approve=lambda plan: True)
  options.update(overrides)
  return review.review_stop_plan(plan, **options)


def consume(value, plan=None, **overrides):
  return review.consume_stop_review(value, plan=make_plan() if plan is None else plan,
    batch_id=overrides.get("batch_id", BATCH))


def test_explicit_approval_sees_independent_complete_plan_and_consumes_once(capsys):
  plan = make_plan(); saved = deepcopy(plan); seen = []
  def approve(value):
    assert value == plan and value is not plan
    seen.append(value)
    value["runs"][0]["restore"]["mode"] = "changed-by-reviewer"
    return True
  accepted = issue(plan, approve=approve)
  assert type(accepted) is review.StopReview and plan == saved and len(seen) == 1
  assert consume(accepted, plan) is None
  with pytest.raises(Conflict): consume(accepted, plan)
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("damage", ["scope", "scope-type", "scope-extra", "scope-profile-default", "operation", "selected-empty", "selected-tuple", "selected-duplicate", "selected-missing", "selected-third", "selected-bool", "plan-id", "plan-id-type", "batch", "batch-type", "approve", "blocked", "corrupt-plan"])
def test_request_or_plan_mismatch_refuses_before_approval(damage):
  plan = make_plan(); calls = []
  options = {"approve": lambda value: calls.append(value) or True}
  if damage == "scope": options["scope"] = {**scope(), "machine": "other"}
  elif damage == "scope-type": options["scope"] = list(scope())
  elif damage == "scope-extra": options["scope"] = {**scope(), "synthetic-private-canary": True}
  elif damage == "scope-profile-default": options["scope"] = {**scope(), "profile": "omp-0"}
  elif damage == "operation": options["operation"] = "setup"
  elif damage == "selected-empty": options["selected_runs"] = []
  elif damage == "selected-tuple": options["selected_runs"] = tuple(RUNS[:2])
  elif damage == "selected-duplicate": options["selected_runs"] = [RUNS[0], RUNS[0], RUNS[1]]
  elif damage == "selected-missing": options["selected_runs"] = RUNS[:1]
  elif damage == "selected-third": options["selected_runs"] = RUNS[:3]
  elif damage == "selected-bool": options["selected_runs"] = [True]
  elif damage == "plan-id": options["plan_id"] = "0" * 64
  elif damage == "plan-id-type": options["plan_id"] = True
  elif damage == "batch": options["batch_id"] = "invalid"
  elif damage == "batch-type": options["batch_id"] = True
  elif damage == "approve": options["approve"] = None
  elif damage == "blocked": plan = make_plan(operation="setup"); options["operation"] = "setup"
  else: plan["runs"][0]["deployment_digest"] = "9" * 64
  with pytest.raises(Conflict) as caught: issue(plan, **options)
  assert calls == [] and "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("answer", [False, None, 1, "true", {}, []])
def test_approval_requires_exact_true(answer):
  with pytest.raises(Conflict): issue(approve=lambda plan: answer)


@pytest.mark.parametrize("kind", [ValueError, KeyboardInterrupt, SystemExit])
def test_callback_error_or_cancel_propagates_original(kind):
  error = kind("synthetic-original-cancel")
  def rejected(plan): raise error
  with pytest.raises(kind) as caught: issue(approve=rejected)
  assert caught.value is error


@pytest.mark.parametrize("change", ["restore", "deployment", "generation", "observation", "scope"])
def test_full_canonical_plan_bound_and_invalid_attempt_does_not_consume(change):
  original = make_plan(); accepted = issue(original)
  runs, resources = snapshots(); requested_scope = scope()
  if change == "restore": runs[0]["restore"]["capability"] = "supported"
  elif change == "deployment": runs[0]["deployment_digest"] = "7" * 64
  elif change == "generation": resources[0]["generation"] = 2
  elif change == "observation": runs[0]["observation"]["record_digest"] = "8" * 64
  else: requested_scope["agent"] = "omp"
  altered = maintenance.build_stop_plan(scope=requested_scope, operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert altered["plan_id"] != original["plan_id"]
  with pytest.raises(Conflict): consume(accepted, altered)
  assert consume(accepted, original) is None


def test_wrong_batch_or_pid_does_not_consume_then_original_is_usable(monkeypatch):
  accepted = issue()
  with pytest.raises(Conflict): consume(accepted, batch_id="b" * 32)
  original = review.os.getpid()
  monkeypatch.setattr(review.os, "getpid", lambda: original + 1)
  with pytest.raises(Conflict): consume(accepted)
  monkeypatch.setattr(review.os, "getpid", lambda: original)
  assert consume(accepted) is None


def test_copy_deepcopy_are_same_single_approval_and_pickle_refuses():
  accepted = issue()
  assert copy(accepted) is accepted and deepcopy(accepted) is accepted
  for protocol in (0, pickle.HIGHEST_PROTOCOL):
    with pytest.raises((Conflict, TypeError)): pickle.dumps(accepted, protocol=protocol)
  consume(copy(accepted))
  with pytest.raises(Conflict): consume(deepcopy(accepted))


def test_busy_memory_lock_refuses_without_wait_or_consumption():
  accepted = issue()
  assert accepted._lock.acquire(blocking=False)
  try:
    with pytest.raises(Conflict): consume(accepted)
  finally: accepted._lock.release()
  assert consume(accepted) is None


@pytest.mark.parametrize("kind", ["dict", "bool", "object", "forged", "subclass"])
def test_user_data_forged_and_derived_objects_cannot_consume(kind):
  if kind == "dict": value = {"approved": True, "plan": make_plan()}
  elif kind == "bool": value = True
  elif kind == "object": value = object()
  elif kind == "forged": value = object.__new__(review.StopReview)
  else:
    class Derived(review.StopReview): pass
    value = object.__new__(Derived)
  with pytest.raises(Conflict) as caught: consume(value)
  assert "synthetic-private-canary" not in str(caught.value)


def test_direct_constructor_and_mutation_cannot_rearm_review():
  with pytest.raises((Conflict, TypeError)): review.StopReview({"approved": True})
  accepted = issue()
  consume(accepted)
  with pytest.raises((Conflict, AttributeError, TypeError)): accepted._used = False
  with pytest.raises(Conflict): consume(accepted)


def test_input_gateway_cancel_130_is_preserved_exactly():
  from rotom.context import InputError
  error = InputError(130)
  def cancel(plan): raise error
  with pytest.raises(InputError) as caught: issue(approve=cancel)
  assert caught.value is error and caught.value.exit_code == 130


def test_other_thread_holding_memory_lock_is_nonblocking_rejection():
  import threading
  accepted = issue()
  entered, release = threading.Event(), threading.Event()
  def held():
    with accepted._lock:
      entered.set()
      release.wait()
  worker = threading.Thread(target=held)
  worker.start()
  try:
    assert entered.wait(2)
    with pytest.raises(Conflict): consume(accepted)
  finally:
    release.set()
    worker.join(2)
  assert not worker.is_alive() and consume(accepted) is None
