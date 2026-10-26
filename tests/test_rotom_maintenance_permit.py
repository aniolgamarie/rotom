"""完整合成 Batch 与单次内存对象；不控制宿主或读写现场。"""
from copy import copy, deepcopy
import json
import pickle
from pathlib import Path
import threading

import pytest

from agentcfg import maintenance, maintenance_permit as permit, stop_review
from agentcfg.storage import Conflict
from test_rotom_maintenance_codec import batch as make_batch


GENERATION = 3
DIGEST = "a" * 64
CANARY = "synthetic-private-canary"


def batch(issued=False):
  value = make_batch("maintenance_dispatch_intent" if issued else "stopped_confirmed", operation="setup")
  if issued: value["maintenance_dispatch"]["setup_plan_digest"] = DIGEST
  return maintenance.decode_batch(maintenance.encode_batch(value))


def issue(value=None, *, issued=False, **changes):
  value = batch(issued) if value is None else value
  options = {"intent_generation": GENERATION, "setup_plan_digest": DIGEST}
  if not issued: options["approve"] = lambda view: True
  options.update(changes)
  return (permit._issue_batch_permit if issued else permit.review_setup)(value, **options)


def consume(token, value=None, *, issued=False, **changes):
  options = {"intent_generation": GENERATION, "setup_plan_digest": DIGEST}
  options.update(changes)
  return (permit.consume_batch_permit if issued else permit.consume_setup_review)(token,
    batch=batch(issued) if value is None else value, **options)


def test_review_callback_gets_detached_complete_request_and_consumes_once(capsys):
  value = batch(); before = deepcopy(value); calls = []
  def approve(view):
    assert view == {"batch": value, "intent_generation": GENERATION, "setup_plan_digest": DIGEST}
    assert view["batch"] is not value
    calls.append(view)
    view["batch"]["items"][0]["facts"]["resources_released"] = False
    view["intent_generation"] = 99
    return True
  token = issue(value, approve=approve)
  assert type(token) is permit.SetupReview and value == before and len(calls) == 1
  assert consume(token, value) is None
  with pytest.raises(Conflict): consume(token, value)
  assert capsys.readouterr() == ("", "")


def test_postcommit_permit_consumes_once_and_has_no_review_callback(capsys):
  value = batch(True); before = deepcopy(value)
  token = issue(value, issued=True)
  assert type(token) is permit.BatchPermit and value == before
  assert consume(token, value, issued=True) is None
  with pytest.raises(Conflict): consume(token, value, issued=True)
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("answer", [False, None, 1, "true", {}, []])
def test_review_requires_exact_true(answer):
  with pytest.raises(Conflict): issue(approve=lambda view: answer)


@pytest.mark.parametrize("error", [ValueError(CANARY), KeyboardInterrupt(CANARY), SystemExit(130)])
def test_approval_exceptions_propagate_unchanged(error):
  def approve(view): raise error
  with pytest.raises(type(error)) as caught: issue(approve=approve)
  assert caught.value is error


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("field,bad", [("intent_generation", True), ("intent_generation", -1),
  ("intent_generation", 2**64), ("intent_generation", 1.0), ("intent_generation", None),
  ("setup_plan_digest", "A" * 64), ("setup_plan_digest", "0" * 63),
  ("setup_plan_digest", True), ("setup_plan_digest", CANARY)])
def test_binding_fields_are_exact_and_reject_before_callback(issued, field, bad):
  calls = []
  options = {field: bad}
  if not issued: options["approve"] = lambda view: calls.append(view) or True
  with pytest.raises(Conflict) as caught: issue(issued=issued, **options)
  assert calls == [] and CANARY not in str(caught.value)


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("generation", [0, 2**64 - 1])
def test_generation_boundaries_are_allowed(issued, generation):
  token = issue(issued=issued, intent_generation=generation)
  assert consume(token, issued=issued, intent_generation=generation) is None


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("damage", ["missing", "extra", "wrong-operation", "wrong-phase", "review-required",
  "missing-exit", "missing-release", "stop-phase", "restore-mode", "restore-phase", "launch", "dispatch-id", "operation-result"])
def test_invalid_or_out_of_scope_batch_is_not_review_or_permit(issued, damage):
  value = batch(issued); calls = []
  if damage == "missing": del value["items"]
  elif damage == "extra": value[CANARY] = True
  elif damage == "wrong-operation": value = make_batch("stopped_confirmed", operation="stop_only")
  elif damage == "wrong-phase": value = batch(not issued)
  elif damage == "review-required": value["review_required"] = True
  elif damage == "missing-exit": value["items"][0]["facts"]["exit_confirmed"] = False
  elif damage == "missing-release": value["items"][0]["facts"]["resources_released"] = False
  elif damage == "stop-phase": value["items"][0]["stop_phase"] = "stop_requested"
  elif damage == "restore-mode":
    value["plan"]["runs"][0]["restore"] = {"mode": "new-location", "capability": "supported",
      "session_status": "sealed", "target_digest": "5" * 64}
    value["plan"] = maintenance._plan(value["plan"], verify=False)
    maintenance.decode_batch(maintenance.encode_batch(value))
  elif damage == "restore-phase": value["items"][0]["restore_phase"] = "restore_pending"
  elif damage == "launch": value["items"][0]["launch_dispatch"] = {
    "state": "dispatch_intent", "dispatch_id": "9" * 32, "new_run_id": "8" * 32}
  elif damage == "dispatch-id":
    value["maintenance_dispatch"]["dispatch_id"] = None if issued else "7" * 32
  else: value["operation_result"] = {"operation": "setup", "status": "succeeded", "exit_code": 0,
    "result_digest": "f" * 64}
  options = {} if issued else {"approve": lambda view: calls.append(view) or True}
  with pytest.raises(Conflict) as caught: issue(value, issued=issued, **options)
  assert calls == [] and CANARY not in str(caught.value)


def test_review_callback_must_be_callable():
  with pytest.raises(Conflict): issue(approve=None)


@pytest.mark.parametrize("stored", [None, "b" * 64])
def test_legacy_or_mismatched_persistent_setup_digest_cannot_issue_permit(stored):
  value = batch(True)
  if stored is None: del value["maintenance_dispatch"]["setup_plan_digest"]
  else: value["maintenance_dispatch"]["setup_plan_digest"] = stored
  # 旧记录仍能严格读取；格式有效不等于可发行新的内存许可。
  maintenance.decode_batch(maintenance.encode_batch(value))
  with pytest.raises(Conflict): issue(value, issued=True)


@pytest.mark.parametrize("stored", [None, "b" * 64])
def test_consumption_also_requires_persistent_setup_digest_without_consuming_on_mismatch(stored):
  original = batch(True); token = issue(original, issued=True); value = deepcopy(original)
  if stored is None: del value["maintenance_dispatch"]["setup_plan_digest"]
  else: value["maintenance_dispatch"]["setup_plan_digest"] = stored
  maintenance.decode_batch(maintenance.encode_batch(value))
  with pytest.raises(Conflict): consume(token, value, issued=True)
  assert consume(token, original, issued=True) is None


@pytest.mark.parametrize("issued", [False, True])
def test_manual_restore_and_sealed_or_unsealed_history_are_allowed(issued):
  for sealed in (False, True):
    value = batch(issued)
    for item in value["items"]:
      item["restore_phase"] = "manual"
      item["facts"]["session_sealed"] = sealed
    token = issue(value, issued=issued)
    assert consume(token, value, issued=issued) is None


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("change", ["revision", "batch-id", "fact", "deployment", "generation", "digest", "dispatch-id"])
def test_full_batch_or_binding_drift_rejects_without_consuming_original(issued, change):
  value = batch(issued); token = issue(value, issued=issued); altered = deepcopy(value); options = {}
  if change == "revision": altered["revision"] += 1
  elif change == "batch-id": altered["batch_id"] = "0" * 32
  elif change == "fact": altered["items"][0]["facts"]["session_sealed"] = True
  elif change == "deployment":
    altered["plan"]["runs"][0]["deployment_digest"] = "f" * 64
    altered["plan"] = maintenance._plan(altered["plan"], verify=False)
  elif change == "generation": options["intent_generation"] = GENERATION + 1
  elif change == "digest": options["setup_plan_digest"] = "b" * 64
  elif issued: altered["maintenance_dispatch"]["dispatch_id"] = "9" * 32
  else: altered = batch(True)
  with pytest.raises(Conflict): consume(token, altered, issued=issued, **options)
  assert consume(token, value, issued=issued) is None


@pytest.mark.parametrize("issued", [False, True])
def test_canonical_array_order_does_not_create_a_false_binding_change(issued):
  value = batch(issued); token = issue(value, issued=issued)
  value["items"].reverse(); value["accepted_runs"].reverse()
  value["plan"]["runs"].reverse(); value["plan"]["resources"].reverse()
  assert consume(token, value, issued=issued) is None


@pytest.mark.parametrize("issued", [False, True])
def test_wrong_pid_does_not_consume_and_same_process_can_still_consume(monkeypatch, issued):
  token = issue(issued=issued); pid = permit.os.getpid()
  monkeypatch.setattr(permit.os, "getpid", lambda: pid + 1)
  with pytest.raises(Conflict): consume(token, issued=issued)
  monkeypatch.setattr(permit.os, "getpid", lambda: pid)
  assert consume(token, issued=issued) is None


@pytest.mark.parametrize("issued", [False, True])
def test_busy_lock_does_not_unlock_other_owner_or_consume(issued):
  token = issue(issued=issued)
  assert token._lock.acquire(blocking=False)
  try:
    with pytest.raises(Conflict): consume(token, issued=issued)
    assert not token._lock.acquire(blocking=False)
  finally: token._lock.release()
  assert consume(token, issued=issued) is None


@pytest.mark.parametrize("issued", [False, True])
def test_two_threads_cannot_double_consume(issued):
  token = issue(issued=issued); gate = threading.Barrier(2); results = []
  def consume_once():
    gate.wait(2)
    try: consume(token, issued=issued)
    except Conflict: results.append("conflict")
    else: results.append("consumed")
  workers = [threading.Thread(target=consume_once) for _ in range(2)]
  for worker in workers: worker.start()
  for worker in workers: worker.join(2)
  assert not any(worker.is_alive() for worker in workers)
  assert sorted(results) == ["conflict", "consumed"]


@pytest.mark.parametrize("issued", [False, True])
def test_copy_is_alias_pickle_json_and_mutation_cannot_rearm(issued):
  token = issue(issued=issued)
  assert copy(token) is token and deepcopy(token) is token
  for protocol in (0, pickle.HIGHEST_PROTOCOL):
    with pytest.raises((Conflict, TypeError)): pickle.dumps(token, protocol=protocol)
  with pytest.raises(TypeError): json.dumps(token)
  consume(token, issued=issued)
  with pytest.raises((Conflict, AttributeError)): token._used = False
  with pytest.raises((Conflict, AttributeError)): del token._used
  with pytest.raises(Conflict): consume(copy(token), issued=issued)


@pytest.mark.parametrize("issued", [False, True])
@pytest.mark.parametrize("kind", ["dict", "bool", "stop-review", "other-kind", "forged", "subclass"])
def test_other_approvals_or_user_objects_cannot_be_consumed(issued, kind):
  cls = permit.BatchPermit if issued else permit.SetupReview
  if kind == "dict": token = {"approved": True, CANARY: batch(issued)}
  elif kind == "bool": token = True
  elif kind == "stop-review":
    value = batch(); plan = value["plan"]
    token = stop_review.review_stop_plan(plan, scope=plan["scope"], operation="setup",
      selected_runs=plan["selected_runs"], plan_id=plan["plan_id"], batch_id=value["batch_id"], approve=lambda p: True)
  elif kind == "other-kind": token = issue(issued=not issued)
  elif kind == "forged": token = object.__new__(cls)
  else:
    class Derived(cls): pass
    token = object.__new__(Derived)
  with pytest.raises(Conflict) as caught: consume(token, issued=issued)
  assert CANARY not in str(caught.value)


@pytest.mark.parametrize("cls_name", ["SetupReview", "BatchPermit"])
def test_direct_constructor_is_not_user_approval(cls_name):
  cls = getattr(permit, cls_name)
  with pytest.raises((Conflict, TypeError)): cls({"approved": True})
  with pytest.raises(Conflict): cls(object(), b"{}", GENERATION, DIGEST)


def test_setup_review_is_not_stop_review():
  value = batch(); token = issue(value)
  with pytest.raises(Conflict):
    stop_review.consume_stop_review(token, plan=value["plan"], batch_id=value["batch_id"])
  assert consume(token, value) is None


def test_no_own_filesystem_or_output_side_effects_after_public_codec_is_loaded(monkeypatch, capsys):
  review_batch, permit_batch = batch(), batch(True)
  def forbidden(*a, **k): pytest.fail("memory primitive attempted filesystem access")
  with monkeypatch.context() as patch:
    patch.setattr(Path, "open", forbidden)
    patch.setattr("builtins.open", forbidden)
    consume(issue(review_batch), review_batch)
    consume(issue(permit_batch, issued=True), permit_batch, issued=True)
  assert capsys.readouterr() == ("", "")
